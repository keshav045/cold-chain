"""Shipment scheduling: scenarios, containers (no overlap), route stops with delays."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .timeutil import T0, date_of, iso1

CITIES = ["Mumbai", "Delhi", "Chennai", "Kolkata", "Bengaluru", "Hyderabad", "Pune", "Ahmedabad",
          "Jaipur", "Lucknow", "Kochi", "Nagpur"]
SCENARIOS = ("CLEAN", "BRIEF", "PROLONGED", "CRITICAL", "DROPOUT", "STUCK", "ROUTE_DELAY")


@dataclass
class Trip:
    idx: int
    shipment_id: str
    product: dict
    policy: dict
    container_id: str
    sensor: dict
    scenario: str
    boundary: str | None          # "AT_LIMIT" | "JUST_OVER" | None
    dep: int                      # actual departure (epoch-min)
    planned_dep: int
    n_readings: int
    stops: list = field(default_factory=list)
    delay_stop: int | None = None  # index of the stop whose arrival was delayed by a long leg
    delay_minutes: int = 0
    expired: bool = False

    @property
    def end(self) -> int:
        return self.stops[-1]["aa"]


def assign_scenarios(rng, n: int, mix: dict) -> list[str]:
    counts = {k: max(1, round(p * n)) for k, p in mix.items()}
    if sum(counts.values()) > n:
        raise ValueError("too few shipments for the scenario quotas (need >= 8)")
    labels = ["CLEAN"] * (n - sum(counts.values()))
    for k, c in counts.items():
        labels += [k] * c
    return [labels[i] for i in rng.permutation(n)]


def build_trips(cfg, M, rng) -> list[Trip]:
    n = cfg.n_shipments
    scen = assign_scenarios(rng, n, cfg.scenario_mix)
    slots_per_day = 1440 // cfg.interval_min
    deps = np.sort(rng.integers(cfg.first_departure_day * slots_per_day,
                                cfg.last_departure_day * slots_per_day + 1, size=n)) * cfg.interval_min + T0
    free_at = np.full(cfg.n_containers, -10**9, dtype=np.int64)
    seen_boundary = {"BRIEF": False, "PROLONGED": False}
    trips = []
    for i in range(n):
        s = scen[i]
        dep = int(deps[i])
        delta = int(rng.integers(36, 145)) * 5 if s == "ROUTE_DELAY" else 0   # 180..720 min
        dur_max = cfg.max_trip_days * 1440 - delta - 45
        dur = int(rng.integers(cfg.min_trip_days * 288, dur_max // 5 + 1)) * 5
        k = int(rng.integers(1, 4))                                           # transit hubs
        dwell = rng.integers(6, 25, size=k) * 5                               # 30..120 min
        travel = dur - int(dwell.sum())
        frac = 0.4 / (k + 1) + 0.6 * rng.dirichlet(np.ones(k + 1))
        legs = (np.floor(frac * travel / 5) * 5).astype(int)
        legs[-1] = travel - legs[:-1].sum()
        jitter = rng.integers(0, 3, size=k + 1) * 5
        extra = jitter.copy()
        delay_leg = None
        if delta:
            delay_leg = int(rng.integers(0, k + 1))
            extra[delay_leg] += delta
        cum = np.cumsum(extra)
        actual_dur = dur + int(cum[-1])

        elig = np.flatnonzero(free_at <= dep)
        if elig.size == 0:                       # shift departure to the earliest free container
            c = int(np.argmin(free_at))
            dep = int(-(-int(free_at[c]) // 5) * 5)
        else:
            c = int(elig[int(rng.integers(0, elig.size))])
        free_at[c] = dep + actual_dur + cfg.turnaround_min

        product = M.products[int(rng.integers(0, len(M.products)))]
        policy = M.policy_for(product["product_id"], date_of(dep))
        o, d = rng.choice(len(CITIES), size=2, replace=False)
        sid = f"SHP-{cfg.sim_year}-{i + 1:06d}"
        stops = [dict(seq=1, type="ORIGIN", loc=CITIES[int(o)], pa=dep, pd=dep, aa=dep, ad=dep, delay=0)]
        pd_prev = dep
        for j in range(k + 1):
            pa = pd_prev + int(legs[j])
            last = j == k
            pdp = pa if last else pa + int(dwell[j])
            shift = int(cum[j])
            stops.append(dict(seq=j + 2, type="DESTINATION" if last else "TRANSIT_HUB",
                              loc=CITIES[int(d)] if last else f"{CITIES[int(rng.integers(0, len(CITIES)))]} Hub",
                              pa=pa, pd=pdp, aa=pa + shift, ad=pdp + shift, delay=shift))
            pd_prev = pdp
        for st in stops:
            st["id"] = f"RST-{sid}-{st['seq']:02d}"
        boundary = None
        if s in seen_boundary and not seen_boundary[s]:
            seen_boundary[s] = True
            boundary = "AT_LIMIT" if s == "BRIEF" else "JUST_OVER"
        sensor = M.sensors[c]
        t = Trip(idx=i, shipment_id=sid, product=product, policy=policy, container_id=M.containers[c]["container_id"],
                 sensor=sensor, scenario=s, boundary=boundary, dep=dep, planned_dep=dep,
                 n_readings=actual_dur // 5 + 1, stops=stops,
                 delay_stop=(delay_leg + 1) if delay_leg is not None else None, delay_minutes=delta,
                 expired=date_of(dep) > sensor["calibration_due"])
        trips.append(t)
    return trips
