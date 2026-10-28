"""Reading simulation: physics-lite baseline + scenario events + physical-range faults."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .rules import INTERVAL, classify
from .timeutil import compact

MARGIN = 3  # readings of clean separation between injected events


@dataclass
class Sim:
    shipment_id: str
    sensor_id: str
    ts: np.ndarray
    temp: np.ndarray
    rh: np.ndarray
    stop_idx: np.ndarray
    orig_idx: np.ndarray
    occupied: list = field(default_factory=list)
    planned_exc: list = field(default_factory=list)
    planned_gaps: list = field(default_factory=list)
    planned_stuck: list = field(default_factory=list)


def _ar1(rng, n, sd, clip, phi=0.8):
    z = rng.standard_normal(n)
    s = math.sqrt(1 - phi * phi) * sd
    e = rng.standard_normal() * sd
    out = np.empty(n)
    for i in range(n):
        e = phi * e + s * z[i]
        out[i] = e
    return np.clip(out, -clip, clip)


def _place(rng, n, length, occupied, lo=2, hi=None):
    """Random start so [s, s+length) keeps MARGIN clear of every occupied interval and the trip ends."""
    hi = n - 2 - length if hi is None else hi
    if hi < lo:
        return None
    for _ in range(200):
        s = int(rng.integers(lo, hi + 1))
        if all(s + length + MARGIN <= a or s - MARGIN >= b for a, b in occupied):
            occupied.append((s, s + length))
            return s
    return None


def simulate(trip, rng) -> Sim:
    pol, dep, n = trip.policy, trip.dep, trip.n_readings
    ts = dep + INTERVAL * np.arange(n, dtype=np.int64)
    t_lo, t_hi, h_lo, h_hi = pol["temp_min_c"], pol["temp_max_c"], pol["rh_min_pct"], pol["rh_max_pct"]
    hw_t, hw_h = (t_hi - t_lo) / 2, (h_hi - h_lo) / 2
    set_t, set_h = (t_hi + t_lo) / 2, (h_hi + h_lo) / 2

    # Door-open warm-up at transit hubs: first-order lag towards a capped offset, then recovery.
    dwell = np.zeros(n, dtype=bool)
    for st in trip.stops[1:-1]:
        dwell |= (ts >= st["aa"]) & (ts <= st["ad"])
    cap = 0.3 * hw_t
    ex, exs = 0.0, np.empty(n)
    for i in range(n):
        ex += 0.10 * (cap - ex) if dwell[i] else -0.25 * ex
        exs[i] = ex
    diurnal = 0.05 * hw_t * np.sin(2 * np.pi * (ts % 1440) / 1440)
    temp = set_t + exs + diurnal + _ar1(rng, n, 0.06 * hw_t, 0.15 * hw_t)
    rh = set_h + 0.25 * hw_h * (exs / cap) + _ar1(rng, n, 0.06 * hw_h, 0.15 * hw_h)
    temp, rh = np.round(temp, 2), np.round(rh, 2)

    maxm = pol["max_excursion_minutes"] // INTERVAL
    occupied, planned_exc, gaps, stuck = [], [], [], []

    def metric_dir():
        metric = "T" if rng.random() < 0.85 else "H"
        if metric == "T":
            return metric, ("HIGH" if rng.random() < 0.7 else "LOW")
        opts = []
        if h_hi + 19 <= 99:
            opts.append("HIGH")
        if h_lo - 19 >= 1:
            opts.append("LOW")
        # Defensive fallback: if the humidity range touches both physical rails, pick the
        # side with more headroom.  This is theoretically impossible with the current
        # product table but guards against future additions.
        if not opts:
            opts = ["HIGH"] if (99 - h_hi) >= (h_lo - 1) else ["LOW"]
        return metric, opts[int(rng.integers(0, len(opts)))]

    def add_exc(start, length, metric, direction, deep, cause_hint=None):
        arr, lim = (temp, t_hi if direction == "HIGH" else t_lo) if metric == "T" else (rh, h_hi if direction == "HIGH" else h_lo)
        if metric == "T":
            peak = rng.uniform(5.5, 9.0) if deep else rng.uniform(0.5, 4.0)
            floor = 0.2
        else:
            peak = rng.uniform(12.6, 18.0) if deep else rng.uniform(2.0, 9.0)
            floor = 1.0
        k = np.arange(length)
        r = max(1, length // 4)
        shape = np.minimum(1.0, np.minimum((k + 1) / r, (length - k) / r))
        dev = np.maximum(np.maximum(floor, peak * shape) * (1 + rng.normal(0, 0.02, length)), floor)
        sign = 1 if direction == "HIGH" else -1
        arr[start:start + length] = np.round(lim + sign * dev, 2)
        seg = arr[start:start + length]
        real_dev = round(float(abs((seg.max() if direction == "HIGH" else seg.min()) - lim)), 2)
        crit = pol["critical_margin_temp_c"] if metric == "T" else pol["critical_margin_rh_pct"]
        planned_exc.append(dict(
            metric="TEMPERATURE" if metric == "T" else "HUMIDITY", direction=direction,
            start_ts=int(ts[start]), end_ts=int(ts[start + length - 1]), length=length,
            duration=length * INTERVAL, peak_deviation=real_dev,
            severity=classify(length * INTERVAL, real_dev, pol["max_excursion_minutes"], crit),
            cause_hint=cause_hint))

    sc = trip.scenario
    if sc == "BRIEF":
        for j in range(1 + int(rng.random() < 0.3)):
            length = maxm if (trip.boundary == "AT_LIMIT" and j == 0) else int(rng.integers(1, maxm + 1))
            s = _place(rng, n, length, occupied)
            if s is not None:
                m, d = metric_dir()
                add_exc(s, length, m, d, False)
    elif sc == "PROLONGED":
        length = maxm + 1 if trip.boundary == "JUST_OVER" else int(rng.integers(maxm + 1, int(2.4 * maxm) + 1))
        s = _place(rng, n, length, occupied)
        m, d = metric_dir()
        add_exc(s, length, m, d, False)
    elif sc == "CRITICAL":
        deep = rng.random() < 0.5
        length = int(rng.integers(1, 2 * maxm + 1)) if deep else int(rng.integers(3 * maxm, 5 * maxm + 1))
        s = _place(rng, n, length, occupied)
        m, d = metric_dir()
        add_exc(s, length, m, d, deep)
    elif sc == "ROUTE_DELAY" and rng.random() < 0.6:
        st = trip.stops[trip.delay_stop]
        e_idx = (st["aa"] - dep) // INTERVAL
        w0 = e_idx - trip.delay_minutes // INTERVAL           # start of the extra (delay) part of the leg
        # Guard: ensure hi >= lo+1 so rng.integers() always has a valid range.
        exc_hi = max(2, min(trip.delay_minutes // INTERVAL - 8, 2 * maxm))
        length = int(rng.integers(2, exc_hi + 1))
        s = _place(rng, n, length, occupied, lo=w0 + MARGIN, hi=min(e_idx - 3 - length, n - 2 - length))
        if s is not None:
            m, d = metric_dir()
            add_exc(s, length, m, d, False, cause_hint="ROUTE_DELAY")
    elif sc == "STUCK":
        length = int(rng.integers(24, 73))
        s = _place(rng, n, length, occupied, lo=MARGIN + 1)
        if s is not None:
            temp[s:s + length] = temp[s - 1]
            rh[s:s + length] = rh[s - 1]
            stuck.append(dict(start_ts=int(ts[s]), length=length))
    keep = np.ones(n, dtype=bool)
    if sc == "DROPOUT":
        for _ in range(int(rng.integers(1, 4))):
            length = int(rng.integers(3, 41))
            s = _place(rng, n, length, occupied)
            if s is not None:
                keep[s:s + length] = False
                gaps.append(dict(last_ts=int(ts[s - 1]), next_ts=int(ts[s + length]), missing=length))

    stop_idx = np.full(n, -1, dtype=np.int16)
    for j, st in enumerate(trip.stops):
        stop_idx[(ts >= st["aa"]) & (ts <= st["ad"])] = j
    ki = np.flatnonzero(keep)
    return Sim(trip.shipment_id, trip.sensor["sensor_id"], ts[ki], temp[ki], rh[ki], stop_idx[ki], ki,
               occupied, planned_exc, gaps, stuck)


FAULT_KINDS = [("T", -127.0), ("T", 150.0), ("H", -5.0), ("H", 110.0)]


def inject_physical_faults(rng, sims, cfg):
    """Overwrite a few readings with physically impossible values (outside any event window)."""
    total = sum(len(s.ts) for s in sims)
    target = max(3, round(cfg.rate_physical_range * total))
    chosen, records, tries = set(), [], 0
    while len(records) < target and tries < target * 200:
        tries += 1
        si = int(rng.integers(0, len(sims)))
        sim = sims[si]
        pos = int(rng.integers(MARGIN, len(sim.ts) - MARGIN))
        oi = int(sim.orig_idx[pos])
        if (si, pos) in chosen or any(a - MARGIN <= oi < b + MARGIN for a, b in sim.occupied):
            continue
        # keep faults clear of removed gap indices as well (gaps are in `occupied`)
        kind, val = FAULT_KINDS[int(rng.integers(0, len(FAULT_KINDS)))]
        (sim.temp if kind == "T" else sim.rh)[pos] = val
        chosen.add((si, pos))
        records.append(dict(shipment_id=sim.shipment_id, sensor_id=sim.sensor_id, ts=int(sim.ts[pos]),
                            kind=kind, value=val,
                            reading_id=f"RDG-{sim.sensor_id}-{compact([sim.ts[pos]])[0]}"))
    return records
