"""Detection engine: pure functions over reading arrays. Used by the generator AND the validator.

Everything derived (quality flags, gaps, excursions, durations, severity) comes from here, so derived
values are always computed from source readings, never drawn independently.
"""
from __future__ import annotations

import numpy as np

from .rules import INTERVAL, STUCK_MIN_RUN, classify


def run_lengths(mask: np.ndarray):
    """Starts and lengths of the True-runs of a boolean array."""
    m = np.concatenate(([False], mask, [False])).astype(np.int8)
    d = np.diff(m)
    s = np.flatnonzero(d == 1)
    e = np.flatnonzero(d == -1)
    return s, e - s


def stuck_mask(ts, temp, rh, min_run: int = STUCK_MIN_RUN) -> np.ndarray:
    """True for readings inside a run of >= min_run identical consecutive (temp, rh) pairs."""
    out = np.zeros(len(ts), dtype=bool)
    if len(ts) < 2:
        return out
    same = (temp[1:] == temp[:-1]) & (rh[1:] == rh[:-1]) & (np.diff(ts) == INTERVAL)
    starts, lens = run_lengths(same)
    for a, ln in zip(starts, lens):
        if ln + 1 >= min_run:
            out[a:a + ln + 1] = True
    return out


def quality_codes(ts, temp, rh, limits, expired: bool):
    """limits = (tmin, tmax, rhmin, rhmax) physical sensor range. Returns (codes, stuck_mask)."""
    tmin, tmax, rmin, rmax = limits
    fault = (temp < tmin) | (temp > tmax) | (rh < rmin) | (rh > rmax) | np.isnan(temp) | np.isnan(rh)
    stuck = stuck_mask(ts, temp, rh)
    codes = np.where(fault, "SENSOR_FAULT", np.where(stuck | expired, "LOW_TRUST", "GOOD"))
    return codes, stuck


def find_gaps(ts):
    """[(last_ts, next_ts, missing_readings)] wherever consecutive readings are > 1 interval apart."""
    d = np.diff(ts)
    return [(int(ts[i]), int(ts[i + 1]), int(d[i] // INTERVAL - 1)) for i in np.flatnonzero(d > INTERVAL)]


def find_runs(ts, values, lo, hi, valid):
    """Maximal runs of consecutive (exactly one interval apart) out-of-range readings.

    A run never bridges a gap or a faulty reading, and never mixes HIGH and LOW breaches.
    Returns [(first_idx, last_idx, is_high)].
    """
    out = ((values < lo) | (values > hi)) & valid
    idx = np.flatnonzero(out)
    if idx.size == 0:
        return []
    high = values[idx] > hi
    brk = np.ones(idx.size, dtype=bool)
    brk[1:] = (np.diff(ts[idx]) != INTERVAL) | (high[1:] != high[:-1])
    starts = np.flatnonzero(brk)
    ends = np.concatenate((starts[1:], [idx.size])) - 1
    return [(int(idx[s]), int(idx[e]), bool(high[s])) for s, e in zip(starts, ends)]


def derive_excursions(ts, temp, rh, codes, policy: dict):
    """Excursion dicts (no IDs) for one shipment, ordered by (start, metric)."""
    valid = codes != "SENSOR_FAULT"
    out = []
    for metric, vals, lo, hi, crit in (
            ("TEMPERATURE", temp, policy["temp_min_c"], policy["temp_max_c"], policy["critical_margin_temp_c"]),
            ("HUMIDITY", rh, policy["rh_min_pct"], policy["rh_max_pct"], policy["critical_margin_rh_pct"])):
        for i0, i1, high in find_runs(ts, vals, lo, hi, valid):
            seg = vals[i0:i1 + 1]
            peak = float(seg.max() if high else seg.min())
            dev = round(abs(peak - (hi if high else lo)), 2)
            dur = int(ts[i1] - ts[i0]) + INTERVAL
            out.append(dict(
                metric=metric, direction="HIGH" if high else "LOW", start_ts=int(ts[i0]), end_ts=int(ts[i1]),
                duration=dur, peak_value=round(peak, 2), peak_deviation=dev,
                severity=classify(dur, dev, policy["max_excursion_minutes"], crit),
                evidence="LOW_TRUST" if (codes[i0:i1 + 1] == "LOW_TRUST").any() else "VERIFIED"))
    out.sort(key=lambda e: (e["start_ts"], e["metric"]))
    return out
