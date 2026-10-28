"""End-to-end generation pipeline (maps to the brief's Steps 1-10)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import master_data, readings, scheduling, schema, workflow
from .detection import derive_excursions, find_gaps, quality_codes
from .rules import EXPECTED_DECISION, ROUTE_DELAY_MIN
from .timeutil import compact, date_of, iso


class GeneratorConsistencyError(RuntimeError):
    """Raised when the generator's internal self-check fails.

    This always indicates a code bug — the planned (injected) events did not match
    what the detection engine found.  It is never caused by user input.
    """


@dataclass
class Result:
    tables: dict
    ground_truth: pd.DataFrame
    config: dict


def _df(name, rows):
    return pd.DataFrame(rows, columns=schema.columns(name))


def _seq_ids(prefix, n, year):
    return [f"{prefix}-{year}-{i:06d}" for i in range(1, n + 1)]


def generate(cfg) -> Result:
    Y = cfg.sim_year
    ss = np.random.SeedSequence(cfg.seed)
    # Six independent root children: master_data, scheduling, readings, defect-injection,
    # workflow, and a second defect pass (record-level defects on derived tables).
    s_master, s_sched, s_read, s_defect, s_flow, s_defect2 = ss.spawn(6)

    # Steps 1-3: master data, scheduling, route stops (parents before children)
    M = master_data.build(cfg, np.random.default_rng(s_master))
    trips = scheduling.build_trips(cfg, M, np.random.default_rng(s_sched))

    # Step 4-5: scenario plan + baseline readings with injected excursions / dropouts / stuck sensors
    sims = [readings.simulate(t, np.random.default_rng(c)) for t, c in zip(trips, s_read.spawn(len(trips)))]

    # Step 7a: reading-level defects (physical-range faults), injected after clean data exists
    rng_d = np.random.default_rng(s_defect)
    fault_records = readings.inject_physical_faults(rng_d, sims, cfg)

    # Step 6: detection engine derives quality, gaps, excursions from the readings
    r_cols = {k: [] for k in ("reading_id", "sensor_id", "shipment_id", "route_stop_id", "timestamp",
                              "temperature_c", "humidity_pct", "quality_flag")}
    gap_rows, exc_rows, lowtrust_first, stuck_ships, delays = [], [], {}, set(), []
    for t, sim in zip(trips, sims):
        limits = (t.sensor["valid_temp_min_c"], t.sensor["valid_temp_max_c"],
                  t.sensor["valid_rh_min_pct"], t.sensor["valid_rh_max_pct"])
        codes, stuck = quality_codes(sim.ts, sim.temp, sim.rh, limits, t.expired)
        if stuck.any():
            stuck_ships.add(t.shipment_id)
        lt = np.flatnonzero(codes == "LOW_TRUST")
        if lt.size:
            lowtrust_first[t.shipment_id] = int(sim.ts[lt[0]])
        stop_ids = np.array([None] + [s["id"] for s in t.stops], dtype=object)[sim.stop_idx.astype(int) + 1]
        r_cols["reading_id"].append(np.array([f"RDG-{sim.sensor_id}-{c}" for c in compact(sim.ts)], dtype=object))
        r_cols["sensor_id"].append(np.full(len(sim.ts), sim.sensor_id, dtype=object))
        r_cols["shipment_id"].append(np.full(len(sim.ts), t.shipment_id, dtype=object))
        r_cols["route_stop_id"].append(stop_ids)
        r_cols["timestamp"].append(iso(sim.ts))
        r_cols["temperature_c"].append(sim.temp)
        r_cols["humidity_pct"].append(sim.rh)
        r_cols["quality_flag"].append(codes.astype(object))
        for last, nxt, miss in find_gaps(sim.ts):
            gap_rows.append(dict(shipment_id=t.shipment_id, sensor_id=sim.sensor_id, last_ts=last, next_ts=nxt, missing=miss))
        # delayed legs (>= 120 min late relative to the previous stop)
        windows = []
        for j in range(1, len(t.stops)):
            if t.stops[j]["delay"] - t.stops[j - 1]["delay"] >= ROUTE_DELAY_MIN:
                windows.append((t.stops[j - 1]["ad"], t.stops[j]["aa"]))
                delays.append(dict(shipment_id=t.shipment_id, route_stop_id=t.stops[j]["id"], arrival=t.stops[j]["aa"],
                                   leg_delay=t.stops[j]["delay"] - t.stops[j - 1]["delay"]))
        for e in derive_excursions(sim.ts, sim.temp, sim.rh, codes, t.policy):
            e.update(shipment_id=t.shipment_id, sensor_id=sim.sensor_id, policy=t.policy,
                     cause="ROUTE_DELAY" if any(a <= e["start_ts"] <= b for a, b in windows) else "UNKNOWN_IN_TRANSIT")
            exc_rows.append(e)

    # Self-check: planned (injected) events must be exactly what the detector finds
    planned = {(s.shipment_id, p["metric"], p["start_ts"]): p for s in sims for p in s.planned_exc}
    found = {(e["shipment_id"], e["metric"], e["start_ts"]): e for e in exc_rows}
    if set(planned) != set(found):
        raise GeneratorConsistencyError(
            f"planned vs detected excursions differ: "
            f"missing={sorted(set(planned) - set(found))[:3]} "
            f"extra={sorted(set(found) - set(planned))[:3]}"
        )
    for k, p in planned.items():
        f = found[k]
        if (f["duration"], f["severity"]) != (p["duration"], p["severity"]):
            raise GeneratorConsistencyError(
                f"excursion mismatch {k}: planned {p['duration']}/{p['severity']} "
                f"vs {f['duration']}/{f['severity']}"
            )
    planned_gaps = {(s.shipment_id, g["last_ts"], g["next_ts"]) for s in sims for g in s.planned_gaps}
    if planned_gaps != {(g["shipment_id"], g["last_ts"], g["next_ts"]) for g in gap_rows}:
        raise GeneratorConsistencyError("planned vs detected gaps differ")

    # IDs: deterministic ordering (shipment, time)
    exc_rows.sort(key=lambda e: (e["shipment_id"], e["start_ts"], e["metric"]))
    for i, e in enumerate(exc_rows, start=1):
        e["exc_id"] = f"EXC-{Y}-{i:06d}"
    gap_rows.sort(key=lambda g: (g["shipment_id"], g["last_ts"]))
    for i, g in enumerate(gap_rows, start=1):
        g["gap_id"] = f"GAP-{Y}-{i:06d}"

    # Workflow: notifications, actions, status history, custody, shipment status
    wf = workflow.build(np.random.default_rng(s_flow), trips, exc_rows, gap_rows, delays, lowtrust_first)
    wf["notifications"].sort(key=lambda r: (r["sent_at"], r["shipment_id"], r["recipient_role"], r["trigger_id"]))
    wf["actions"].sort(key=lambda r: (r["created_at"], r["shipment_id"], r["action_type"], r["trigger_id"]))
    for name, lst in (("notifications", "NTF"), ("actions", "CA"), ("history", "ESH"), ("custody", "CUS")):
        key = {"notifications": "notification_id", "actions": "action_id", "history": "history_id", "custody": "custody_id"}[name]
        for i, r in enumerate(wf[name], start=1):
            r[key] = f"{lst}-{Y}-{i:06d}"

    # ---- assemble tables (minutes -> ISO strings) ----
    def ts_or_none(m):
        return None if m is None else str(iso([m])[0])

    shipments = []
    for t in trips:
        shipments.append(dict(
            shipment_id=t.shipment_id, product_id=t.product["product_id"], container_id=t.container_id,
            policy_id=t.policy["policy_id"], origin=t.stops[0]["loc"], destination=t.stops[-1]["loc"],
            planned_departure=ts_or_none(t.planned_dep), planned_arrival=ts_or_none(t.stops[-1]["pa"]),
            actual_departure=ts_or_none(t.dep), actual_arrival=ts_or_none(t.end),
            status=wf["shipment_status"][t.shipment_id]))
    stops = [dict(route_stop_id=s["id"], shipment_id=t.shipment_id, sequence=s["seq"], stop_type=s["type"],
                  location=s["loc"], planned_arrival=ts_or_none(s["pa"]), planned_departure=ts_or_none(s["pd"]),
                  actual_arrival=ts_or_none(s["aa"]), actual_departure=ts_or_none(s["ad"]), delay_minutes=s["delay"])
             for t in trips for s in t.stops]
    gaps_t = [dict(gap_id=g["gap_id"], shipment_id=g["shipment_id"], sensor_id=g["sensor_id"],
                   last_reading_ts=ts_or_none(g["last_ts"]), next_reading_ts=ts_or_none(g["next_ts"]),
                   missing_readings=g["missing"], status="UNVERIFIED") for g in gap_rows]
    excs = [dict(excursion_id=e["exc_id"], shipment_id=e["shipment_id"], sensor_id=e["sensor_id"],
                 policy_id=e["policy"]["policy_id"], metric=e["metric"], direction=e["direction"],
                 start_ts=ts_or_none(e["start_ts"]), end_ts=ts_or_none(e["end_ts"]), duration_minutes=e["duration"],
                 peak_value=e["peak_value"], peak_deviation=e["peak_deviation"], severity=e["severity"],
                 evidence_quality=e["evidence"], probable_cause=e["cause"], detected_at=ts_or_none(e["detected_at"]),
                 status=e["status"]) for e in exc_rows]
    hist = [dict(r, changed_at=ts_or_none(r["changed_at"])) for r in wf["history"]]
    notes = [dict(r, sent_at=ts_or_none(r["sent_at"])) for r in wf["notifications"]]
    cust = [dict(r, event_ts=ts_or_none(r["event_ts"])) for r in wf["custody"]]
    acts = [dict(r, created_at=ts_or_none(r["created_at"]), due_at=ts_or_none(r["due_at"]),
                 completed_at=ts_or_none(r["completed_at"])) for r in wf["actions"]]
    rd = pd.DataFrame({k: np.concatenate(v) for k, v in r_cols.items()})

    # Step 7b: record-level defects on derived tables (after clean data + derivation exist).
    # Uses an independent root seed child (s_defect2) so the RNG state is fully explicit.
    rng = np.random.default_rng(s_defect2)
    gt = []

    def gt_add(issue, entity_type, entity_id, shipment_id, subtype="", **details):
        gt.append(dict(issue_type=issue, subtype=subtype, entity_type=entity_type, entity_id=entity_id,
                       shipment_id=shipment_id, expected_decision=EXPECTED_DECISION[issue], details=details))

    n = len(shipments)
    k1 = max(1, round(cfg.rate_delivery_before_departure * n))
    k2 = max(1, round(cfg.rate_wrong_policy * n))
    pick = [int(x) for x in rng.permutation(n)[:k1 + k2]]
    for i in pick[:k1]:
        s = shipments[i]
        s["actual_departure"], s["actual_arrival"] = s["actual_arrival"], s["actual_departure"]
        gt_add("DELIVERY_BEFORE_DEPARTURE", "SHIPMENT", s["shipment_id"], s["shipment_id"],
               actual_departure=s["actual_departure"], actual_arrival=s["actual_arrival"])
    for i in pick[k1:]:
        s = shipments[i]
        d = s["planned_departure"][:10]
        cands = [p for p in M.policies if p["product_id"] != s["product_id"] and p["effective_from"] <= d
                 and (p["effective_to"] is None or d <= p["effective_to"])]
        wrong = cands[int(rng.integers(0, len(cands)))]
        gt_add("WRONG_POLICY", "SHIPMENT", s["shipment_id"], s["shipment_id"],
               correct_policy_id=s["policy_id"], assigned_policy_id=wrong["policy_id"])
        s["policy_id"] = wrong["policy_id"]
    k3 = max(1, round(cfg.rate_duration_undercounted * len(excs)))
    elig = [i for i, e in enumerate(excs) if e["duration_minutes"] >= 15]
    for i in [elig[int(j)] for j in rng.permutation(len(elig))[:k3]]:
        e = excs[i]
        true = e["duration_minutes"]
        new = max(5, int(round(true * rng.uniform(0.5, 0.85) / 5) * 5))
        new = new if new < true else true - 5
        e["duration_minutes"] = new
        gt_add("DURATION_UNDERCOUNTED", "EXCURSION", e["excursion_id"], e["shipment_id"],
               stored_duration_minutes=new, true_duration_minutes=true)

    # Ground truth derived from what was *injected* (independent of the validator)
    for r in fault_records:
        gt_add("OUT_OF_PHYSICAL_RANGE", "READING", r["reading_id"], r["shipment_id"],
               field="temperature_c" if r["kind"] == "T" else "humidity_pct", value=r["value"])
    for g in gap_rows:
        gt_add("SENSOR_DROPOUT_GAP", "DATA_GAP", g["gap_id"], g["shipment_id"], missing_readings=g["missing"])
    for t in trips:
        if t.expired:
            gt_add("CALIBRATION_FAILURE", "SHIPMENT", t.shipment_id, t.shipment_id, "EXPIRED_CALIBRATION",
                   calibration_due=t.sensor["calibration_due"])
        if t.shipment_id in stuck_ships:
            gt_add("CALIBRATION_FAILURE", "SHIPMENT", t.shipment_id, t.shipment_id, "STUCK_AT_VALUE")
    for d in delays:
        gt_add("ROUTE_DELAY", "ROUTE_STOP", d["route_stop_id"], d["shipment_id"], leg_delay_minutes=d["leg_delay"])
    exc_id_of = {(e["shipment_id"], e["metric"], e["start_ts"]): e["exc_id"] for e in exc_rows}
    for (sid, metric, start), p in planned.items():
        gt_add(f"EXCURSION_{p['severity']}", "EXCURSION", exc_id_of[(sid, metric, start)], sid,
               metric=metric, direction=p["direction"], duration_minutes=p["duration"],
               peak_deviation=p["peak_deviation"], cause_hint=p["cause_hint"] or "")
    gt.sort(key=lambda r: (r["issue_type"], r["subtype"], r["entity_id"]))
    for i, r in enumerate(gt, start=1):
        r["gt_id"] = f"GT-{i:06d}"
    gt_df = pd.DataFrame(gt, columns=["gt_id", "issue_type", "subtype", "entity_type", "entity_id", "shipment_id",
                                      "expected_decision", "details"])

    tables = {
        "product": _df("product", M.products), "threshold_policy": _df("threshold_policy", M.policies),
        "container": _df("container", M.containers), "sensor": _df("sensor", M.sensors),
        "shipment": _df("shipment", shipments), "route_stop": _df("route_stop", stops),
        "sensor_reading": rd[schema.columns("sensor_reading")], "data_gap": _df("data_gap", gaps_t),
        "excursion": _df("excursion", excs), "excursion_status_history": _df("excursion_status_history", hist),
        "notification": _df("notification", notes), "custody_event": _df("custody_event", cust),
        "corrective_action": _df("corrective_action", acts),
    }
    return Result(tables, gt_df, cfg.to_dict())
