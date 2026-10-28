"""Validation suite.

Two groups of checks (see README):
  1. HARD INVARIANTS - must pass on every dataset (keys, FKs, enums, cadence, derived-value consistency ...).
  2. EXPECTED ANOMALIES - defect/scenario detectors. The set they find must EXACTLY equal ground_truth
     (precision = recall = 1.0). Anything found but not in ground truth, or in ground truth but not found,
     is a failure.

The validator re-derives quality flags, gaps, excursions, durations, severity, workflow rows and custody
order from the raw tables; it never trusts stored derived values.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd

from . import schema
from .detection import derive_excursions, find_gaps, quality_codes
from .rules import (ALLOWED_TRANSITIONS, CHANNEL, GAP_ALERT_MIN_MISSING, INTERVAL, ROUTE_DELAY_MIN,
                    actions_for, final_status, notify_roles)
from .timeutil import compact, date_of, to_minutes

ISSUES = ["OUT_OF_PHYSICAL_RANGE", "SENSOR_DROPOUT_GAP", "DELIVERY_BEFORE_DEPARTURE", "WRONG_POLICY",
          "DURATION_UNDERCOUNTED", "CALIBRATION_FAILURE", "ROUTE_DELAY",
          "EXCURSION_BRIEF", "EXCURSION_PROLONGED", "EXCURSION_CRITICAL"]


class Checks:
    def __init__(self):
        self.items = {}

    def reg(self, name, desc):
        self.items.setdefault(name, {"description": desc, "failures": 0, "examples": []})

    def fail(self, name, item):
        it = self.items[name]
        it["failures"] += 1
        if len(it["examples"]) < 5:
            it["examples"].append(str(item))

    def summary(self):
        return {k: dict(v, passed=v["failures"] == 0) for k, v in self.items.items()}


def load_dir(path):
    """Load exported CSVs back into typed DataFrames (what a reviewer would do)."""
    T = {}
    for t in schema.TABLES:
        fn = os.path.join(path, f"{t.name}.csv")
        if not os.path.exists(fn):
            fn += ".gz"
        dtypes = {f.name: ("float64" if f.type == "real" else "Int64" if f.type == "int" else "str") for f in t.fields}
        T[t.name] = pd.read_csv(fn, dtype=dtypes, na_values=[""], keep_default_na=False)
    gt = pd.read_csv(os.path.join(path, "ground_truth.csv"), dtype=str, na_values=[""], keep_default_na=False)
    return T, gt


def _format_consistency(path, T):
    """Row counts (and PK sets for the small tables) must agree across CSV, JSON and SQLite."""
    import gzip
    fails = []
    con = None
    db = os.path.join(path, "coldchain.db")
    if os.path.exists(db):
        con = sqlite3.connect(db)
    for t in schema.TABLES:
        n_csv = len(T[t.name])
        pks = set(T[t.name][t.pk])
        big = t.name == "sensor_reading"
        jp = os.path.join(path, f"{t.name}.jsonl.gz" if big else f"{t.name}.json")
        if os.path.exists(jp):
            if big:
                with gzip.open(jp, "rt", encoding="utf-8") as f:
                    n_json = sum(1 for line in f if line.strip())
            else:
                with open(jp, encoding="utf-8") as f:
                    rows = json.load(f)
                n_json = len(rows)
                if {r[t.pk] for r in rows} != pks:
                    fails.append(f"{t.name}: JSON primary keys differ from CSV")
            if n_json != n_csv:
                fails.append(f"{t.name}: CSV {n_csv} rows vs JSON {n_json}")
        if con is not None:
            n_db = con.execute(f"SELECT COUNT(*) FROM {t.name}").fetchone()[0]
            if n_db != n_csv:
                fails.append(f"{t.name}: CSV {n_csv} rows vs SQLite {n_db}")
            elif not big and {r[0] for r in con.execute(f"SELECT {t.pk} FROM {t.name}")} != pks:
                fails.append(f"{t.name}: SQLite primary keys differ from CSV")
    if con is not None:
        con.close()
    return fails


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def validate_dir(path):
    T, gt = load_dir(path)
    rep = validate_tables(T, gt)
    fails = _format_consistency(path, T)
    rep["checks"]["format.consistency"] = {
        "description": "CSV, JSON/JSONL and SQLite exports hold the same rows (row counts and primary-key sets)",
        "failures": len(fails), "examples": fails[:5], "passed": not fails}
    rep["ok"] = rep["ok"] and not fails
    db = os.path.join(path, "coldchain.db")
    if os.path.exists(db):
        con = sqlite3.connect(db)
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        con.close()
        rep["checks"]["sqlite.foreign_key_check"] = {"description": "PRAGMA foreign_key_check on coldchain.db",
                                                      "failures": len(bad), "examples": [str(b) for b in bad[:5]],
                                                      "passed": not bad}
        rep["ok"] = rep["ok"] and not bad
    return rep


def validate_tables(T, gt=None):
    C = Checks()
    found = set()  # (issue_type, subtype, entity_id)

    def reg(name, desc):
        C.reg(name, desc)

    # ------------------------------------------------------------------ 1. schema-level invariants
    reg("schema.columns", "every table has exactly the documented columns")
    reg("schema.required", "required fields are never null")
    reg("schema.types", "int/real fields parse as numbers")
    reg("schema.format", "ID, timestamp and date fields match their regex (zero-padded, immutable formats)")
    reg("schema.enums", "enumerated fields only hold allowed values")
    reg("schema.pk_unique", "primary keys are unique")
    reg("schema.unique", "unique fields (sensor.container_id, product.name) are unique")
    reg("schema.fk", "every foreign key resolves to an existing parent row")
    reg("schema.no_leakage", "no input table contains ground-truth / scenario / issue columns")
    for t in schema.TABLES:
        df = T[t.name]
        want = [f.name for f in t.fields]
        leak = set(df.columns) & schema.FORBIDDEN_INPUT_COLUMNS
        if leak:
            C.fail("schema.no_leakage", f"{t.name}: {sorted(leak)}")
        if set(df.columns) != set(want):
            C.fail("schema.columns", f"{t.name}: missing={set(want) - set(df.columns)} extra={set(df.columns) - set(want)}")
            continue
        for f in t.fields:
            s = df[f.name]
            nn = s.dropna()
            if f.required and s.isna().any():
                C.fail("schema.required", f"{t.name}.{f.name}: {int(s.isna().sum())} nulls")
            if f.type in ("int", "real") and (_num(nn).isna().any()):
                C.fail("schema.types", f"{t.name}.{f.name}")
            if f.regex and len(nn):
                bad = ~nn.astype(str).str.fullmatch(f.regex)
                if bad.any():
                    C.fail("schema.format", f"{t.name}.{f.name}: {int(bad.sum())} bad e.g. {nn[bad].iloc[0]!r}")
            if f.allowed and len(nn):
                bad = ~nn.isin(f.allowed)
                if bad.any():
                    C.fail("schema.enums", f"{t.name}.{f.name}: {nn[bad].iloc[0]!r}")
            if (f.name == t.pk or f.unique) and s.duplicated().any():
                C.fail("schema.pk_unique" if f.name == t.pk else "schema.unique", f"{t.name}.{f.name}")
            if f.fk and len(nn):
                pt, pc = f.fk.split(".")
                miss = ~nn.isin(set(T[pt][pc].dropna()))
                if miss.any():
                    C.fail("schema.fk", f"{t.name}.{f.name} -> {f.fk}: {nn[miss].iloc[0]!r}")

    # ------------------------------------------------------------------ 2. lookups
    pol = T["threshold_policy"].to_dict("records")
    pol_by_id = {p["policy_id"]: p for p in pol}
    sensors = {r["container_id"]: r for r in T["sensor"].to_dict("records")}
    sensor_by_id = {r["sensor_id"]: r for r in T["sensor"].to_dict("records")}
    ships = {r["shipment_id"]: r for r in T["shipment"].to_dict("records")}

    reg("policy.sane", "policy ranges ordered, durations multiple of 5, effective windows do not overlap")
    byprod = defaultdict(list)
    for p in pol:
        if not (p["temp_min_c"] < p["temp_max_c"] and p["rh_min_pct"] < p["rh_max_pct"]) or p["max_excursion_minutes"] % 5:
            C.fail("policy.sane", p["policy_id"])
        byprod[p["product_id"]].append(p)
    for pid, lst in byprod.items():
        lst.sort(key=lambda p: p["effective_from"])
        for a, b in zip(lst, lst[1:]):
            if a["effective_to"] is None or isinstance(a["effective_to"], float) or a["effective_to"] >= b["effective_from"]:
                C.fail("policy.sane", f"{pid}: overlapping windows")

    def resolve(product_id, date):
        for p in byprod.get(product_id, []):
            et = p["effective_to"]
            if p["effective_from"] <= date and (et is None or (isinstance(et, float) and np.isnan(et)) or date <= et):
                return p
        return None

    reg("sensor.calibration_dates", "calibration_due is after calibration_date")
    for r in sensor_by_id.values():
        if not r["calibration_due"] > r["calibration_date"]:
            C.fail("sensor.calibration_dates", r["sensor_id"])

    # ------------------------------------------------------------------ 3. shipments / route stops
    RS = T["route_stop"].copy()
    for c in ("planned_arrival", "planned_departure", "actual_arrival", "actual_departure"):
        RS[c + "_m"] = to_minutes(RS[c])
    RS = RS.sort_values(["shipment_id", "sequence"])
    stops_by = {sid: g.to_dict("records") for sid, g in RS.groupby("shipment_id", sort=False)}

    for n_, d_ in [("route.stops", "3-5 stops, contiguous sequence, ORIGIN first, DESTINATION last, hubs between"),
                   ("route.times", "stop times monotonic; delay_minutes = actual_arrival - planned_arrival"),
                   ("shipment.planned_order", "planned_departure < planned_arrival"),
                   ("shipment.matches_route", "shipment actual times equal first departure / last arrival of its route"),
                   ("shipment.trip_length", "trip length is 2-5 days"),
                   ("shipment.container_no_overlap", "a container is never used by two shipments at the same time"),
                   ("shipment.status", "shipment status equals the worst excursion disposition"),
                   ("reading.shipment_known", "every shipment has readings; every reading belongs to a shipment"),
                   ("reading.sensor_matches", "reading sensor = the sensor of the shipment's container"),
                   ("reading.cadence", "exact 5-minute cadence between consecutive readings (no duplicates, no overlap)"),
                   ("reading.covers_trip", "readings start at departure and end at arrival"),
                   ("reading.id_format", "reading_id = RDG-<sensor_id>-<timestamp>"),
                   ("reading.route_stop", "route_stop_id equals the stop the container is at (or NULL)"),
                   ("reading.quality_flag", "stored quality_flag equals the re-derived flag"),
                   ("reading.no_duplicates", "no two readings share the same (sensor_id, timestamp)"),
                   ("reconcile.reading_counts",
                    "arithmetic reconciliation: readings present + missing_readings listed in data_gap = expected 5-minute slots of the trip"),
                   ("gap.flagged", "every missing interval is listed in data_gap (never silently treated as safe)"),
                   ("gap.table_matches_readings", "every data_gap row corresponds to a real missing interval"),
                   ("excursion.recomputed", "excursions in the table equal the excursions recomputed from readings"),
                   ("excursion.values", "end, peak, severity, evidence, cause, policy of each excursion equal the recomputed values"),
                   ("excursion.duration", "stored duration is not larger than / different from recomputed (shorter = DURATION_UNDERCOUNTED)"),
                   ("workflow.notifications", "notifications per trigger equal the documented routing rules"),
                   ("workflow.actions", "corrective actions per trigger equal the documented rules; dates consistent"),
                   ("workflow.status_history", "status history is append-only, contiguous, uses allowed transitions, ends at the excursion status"),
                   ("workflow.custody", "custody events are ordered, complete, consistent with route and dispositions")]:
        reg(n_, d_)

    windows_by_ship, trip = {}, {}
    cont_windows = defaultdict(list)
    for sid, s in ships.items():
        st = stops_by.get(sid)
        if not st:
            C.fail("route.stops", f"{sid}: no stops")
            continue
        k = len(st)
        if not (3 <= k <= 5 and [x["sequence"] for x in st] == list(range(1, k + 1)) and st[0]["stop_type"] == "ORIGIN"
                and st[-1]["stop_type"] == "DESTINATION" and all(x["stop_type"] == "TRANSIT_HUB" for x in st[1:-1])):
            C.fail("route.stops", sid)
        ok = True
        for j, x in enumerate(st):
            if x["actual_departure_m"] < x["actual_arrival_m"] or x["delay_minutes"] != x["actual_arrival_m"] - x["planned_arrival_m"]:
                ok = False
            if j and x["actual_arrival_m"] < st[j - 1]["actual_departure_m"]:
                ok = False
        if not ok:
            C.fail("route.times", sid)
        start, end = st[0]["actual_departure_m"], st[-1]["actual_arrival_m"]
        trip[sid] = (start, end)
        cont_windows[s["container_id"]].append((start, end, sid))
        if not (end - start >= 2 * 1440 and end - start <= 5 * 1440):
            C.fail("shipment.trip_length", sid)
        pdm, pam = to_minutes(pd.Series([s["planned_departure"], s["planned_arrival"]]))
        if not pdm < pam:
            C.fail("shipment.planned_order", sid)
        adm, aam = to_minutes(pd.Series([s["actual_departure"], s["actual_arrival"]]))
        if aam <= adm:
            found.add(("DELIVERY_BEFORE_DEPARTURE", "", sid))
        elif (adm, aam) != (start, end):
            C.fail("shipment.matches_route", sid)
        res = resolve(s["product_id"], s["planned_departure"][:10])
        pol_row = pol_by_id.get(s["policy_id"])
        if res is None:
            C.fail("policy.sane", f"{sid}: no policy effective")
        elif pol_row is None or pol_row["policy_id"] != res["policy_id"]:
            found.add(("WRONG_POLICY", "", sid))
        windows_by_ship[sid] = [(st[j - 1]["actual_departure_m"], st[j]["actual_arrival_m"])
                                for j in range(1, k) if st[j]["delay_minutes"] - st[j - 1]["delay_minutes"] >= ROUTE_DELAY_MIN]
        for j in range(1, k):
            if st[j]["delay_minutes"] - st[j - 1]["delay_minutes"] >= ROUTE_DELAY_MIN:
                found.add(("ROUTE_DELAY", "", st[j]["route_stop_id"]))
    for cid, w in cont_windows.items():
        w.sort()
        for a, b in zip(w, w[1:]):
            if b[0] < a[1]:
                C.fail("shipment.container_no_overlap", f"{cid}: {a[2]} / {b[2]}")

    # ------------------------------------------------------------------ 4. readings (re-derive everything)
    R = T["sensor_reading"].copy()
    R["tm"] = to_minutes(R["timestamp"])
    R = R.sort_values(["shipment_id", "tm"], kind="stable").reset_index(drop=True)
    groups = R.groupby("shipment_id", sort=False).indices
    dups = R.duplicated(["sensor_id", "timestamp"], keep=False)
    for rid in R.loc[dups, "reading_id"].head(5):
        C.fail("reading.no_duplicates", rid)
    gap_missing = T["data_gap"].groupby("shipment_id")["missing_readings"].sum().to_dict()
    for sid in ships:
        if sid not in groups:
            C.fail("reading.shipment_known", f"{sid}: no readings")
    for sid in groups:
        if sid not in ships:
            C.fail("reading.shipment_known", f"readings for unknown {sid}")

    gap_tab = {(g["shipment_id"], int(a), int(b)): g for g, a, b in zip(
        T["data_gap"].to_dict("records"), to_minutes(T["data_gap"]["last_reading_ts"]), to_minutes(T["data_gap"]["next_reading_ts"]))}
    gap_seen = set()
    exc_tab = {}
    ET = T["excursion"].copy()
    ET["s_m"], ET["e_m"], ET["d_m"] = (to_minutes(ET["start_ts"]), to_minutes(ET["end_ts"]), to_minutes(ET["detected_at"]))
    for r in ET.to_dict("records"):
        exc_tab[(r["shipment_id"], r["metric"], int(r["s_m"]))] = r
    exc_seen, exc_info = set(), {}          # excursion_id -> recomputed dict
    lowtrust_ships, gap_info = set(), {}
    cov = {}
    sev_by_ship = defaultdict(list)

    tmv, tv, hv = R["tm"].to_numpy(), R["temperature_c"].to_numpy(dtype=float), R["humidity_pct"].to_numpy(dtype=float)
    qv, rv = R["quality_flag"].to_numpy(dtype=object), R["reading_id"].to_numpy(dtype=object)
    sens_v, rsv = R["sensor_id"].to_numpy(dtype=object), R["route_stop_id"].to_numpy(dtype=object)
    for sid, pos in groups.items():
        if sid not in ships or sid not in trip:
            continue
        s = ships[sid]
        st = stops_by[sid]
        start, end = trip[sid]
        sensor = sensors.get(s["container_id"])
        if sensor is None:      # broken container FK: already reported by schema.fk
            continue
        ts, temp, rh = tmv[pos], tv[pos], hv[pos]
        if not (sens_v[pos] == sensor["sensor_id"]).all():
            C.fail("reading.sensor_matches", sid)
        d = np.diff(ts)
        if (d <= 0).any() or (d % INTERVAL != 0).any():
            C.fail("reading.cadence", sid)
        if ts[0] != start or ts[-1] != end:
            C.fail("reading.covers_trip", sid)
        exp_ids = np.array([f"RDG-{sensor['sensor_id']}-{c}" for c in compact(ts)], dtype=object)
        if not (exp_ids == rv[pos]).all():
            C.fail("reading.id_format", sid)
        exp_stop = np.full(len(ts), None, dtype=object)
        for x in st:
            exp_stop[(ts >= x["actual_arrival_m"]) & (ts <= x["actual_departure_m"])] = x["route_stop_id"]
        stored_stop = np.where(pd.isna(rsv[pos]), None, rsv[pos])
        if not (exp_stop == stored_stop).all():
            C.fail("reading.route_stop", sid)

        limits = (sensor["valid_temp_min_c"], sensor["valid_temp_max_c"], sensor["valid_rh_min_pct"], sensor["valid_rh_max_pct"])
        expired = date_of(start) > sensor["calibration_due"]
        codes, stuck = quality_codes(ts, temp, rh, limits, expired)
        mism = codes.astype(object) != qv[pos]
        if mism.any():
            C.fail("reading.quality_flag", f"{sid}: {int(mism.sum())} rows e.g. {rv[pos][np.flatnonzero(mism)[0]]}")
        for i in np.flatnonzero(codes == "SENSOR_FAULT"):
            found.add(("OUT_OF_PHYSICAL_RANGE", "", rv[pos][i]))
        if expired:
            found.add(("CALIBRATION_FAILURE", "EXPIRED_CALIBRATION", sid))
        if stuck.any():
            found.add(("CALIBRATION_FAILURE", "STUCK_AT_VALUE", sid))
        if (codes == "LOW_TRUST").any():
            lowtrust_ships.add(sid)
        cov[sid] = (len(ts), (end - start) // INTERVAL + 1)
        if len(ts) + int(gap_missing.get(sid, 0)) != (end - start) // INTERVAL + 1:
            C.fail("reconcile.reading_counts",
                   f"{sid}: {len(ts)} readings + {int(gap_missing.get(sid, 0))} missing != {(end - start) // INTERVAL + 1} slots")

        for last, nxt, miss in find_gaps(ts):
            key = (sid, last, nxt)
            if key in gap_tab:
                gap_seen.add(key)
                g = gap_tab[key]
                if g["missing_readings"] != miss:
                    C.fail("gap.table_matches_readings", f"{g['gap_id']}: missing_readings")
                found.add(("SENSOR_DROPOUT_GAP", "", g["gap_id"]))
                gap_info[g["gap_id"]] = (sid, miss)
            else:
                C.fail("gap.flagged", f"{sid}: gap {last}->{nxt} not in data_gap")

        polr = resolve(s["product_id"], s["planned_departure"][:10])
        if polr is None:
            continue
        wins = windows_by_ship.get(sid, [])
        for e in derive_excursions(ts, temp, rh, codes, polr):
            key = (sid, e["metric"], e["start_ts"])
            row = exc_tab.get(key)
            if row is None:
                C.fail("excursion.recomputed", f"missing in table: {key}")
                continue
            exc_seen.add(key)
            eid = row["excursion_id"]
            cause = "ROUTE_DELAY" if any(a <= e["start_ts"] <= b for a, b in wins) else "UNKNOWN_IN_TRANSIT"
            bad = []
            if int(row["e_m"]) != e["end_ts"]: bad.append("end_ts")
            if abs(row["peak_value"] - e["peak_value"]) > 0.006 or abs(row["peak_deviation"] - e["peak_deviation"]) > 0.006: bad.append("peak")
            if row["severity"] != e["severity"]: bad.append("severity")
            if row["evidence_quality"] != e["evidence"]: bad.append("evidence")
            if row["probable_cause"] != cause: bad.append("cause")
            if row["policy_id"] != polr["policy_id"]: bad.append("policy")
            if row["direction"] != e["direction"]: bad.append("direction")
            if row["sensor_id"] != sensor["sensor_id"]: bad.append("sensor")
            if int(row["d_m"]) != e["end_ts"] + INTERVAL: bad.append("detected_at")
            if bad:
                C.fail("excursion.values", f"{eid}: {bad}")
            if row["duration_minutes"] < e["duration"]:
                found.add(("DURATION_UNDERCOUNTED", "", eid))
            elif row["duration_minutes"] != e["duration"]:
                C.fail("excursion.duration", f"{eid}: stored {row['duration_minutes']} vs recomputed {e['duration']}")
            found.add((f"EXCURSION_{e['severity']}", "", eid))
            crit = polr["critical_margin_temp_c"] if e["metric"] == "TEMPERATURE" else polr["critical_margin_rh_pct"]
            e.update(cause=cause, policy=polr, crit=crit, shipment_id=sid,
                     final=final_status(e["severity"], e["duration"], e["peak_deviation"], polr["max_excursion_minutes"], crit))
            exc_info[eid] = e
            sev_by_ship[sid].append(e)
    for key in exc_tab:
        if key not in exc_seen:
            C.fail("excursion.recomputed", f"in table but not in readings: {key}")
    for key, g in gap_tab.items():
        if key not in gap_seen:
            C.fail("gap.table_matches_readings", f"{g['gap_id']} has no matching missing interval")

    # ------------------------------------------------------------------ 5. workflow tables
    exp_notes, exp_acts = defaultdict(set), defaultdict(set)
    for eid, e in exc_info.items():
        for role, _ in notify_roles(e["severity"], e["metric"], e["cause"]):
            exp_notes[("EXCURSION", eid)].add(role)
        for at, role, _ in actions_for(e["severity"], e["metric"], e["cause"]):
            exp_acts[("EXCURSION", eid)].add((at, role))
    for gid, (sid, miss) in gap_info.items():
        if miss >= GAP_ALERT_MIN_MISSING:
            exp_notes[("DATA_GAP", gid)].add("OT_IT_ADMIN")
            exp_acts[("DATA_GAP", gid)].add(("INVESTIGATE_SENSOR_DROPOUT", "OT_IT_ADMIN"))
    for sid in lowtrust_ships:
        exp_notes[("CALIBRATION", sid)].add("OT_IT_ADMIN")
        exp_acts[("CALIBRATION", sid)].add(("RECALIBRATE_SENSOR", "OT_IT_ADMIN"))
    for sid, st in stops_by.items():
        for j in range(1, len(st)):
            if st[j]["delay_minutes"] - st[j - 1]["delay_minutes"] >= ROUTE_DELAY_MIN:
                exp_notes[("ROUTE_DELAY", st[j]["route_stop_id"])].add("PRODUCTION_PLANNER")
                exp_acts[("ROUTE_DELAY", st[j]["route_stop_id"])].add(("REPLAN_DELIVERY", "PRODUCTION_PLANNER"))
    act_notes, act_acts = defaultdict(set), defaultdict(set)
    for n in T["notification"].to_dict("records"):
        act_notes[(n["trigger_type"], n["trigger_id"])].add(n["recipient_role"])
        if CHANNEL[n["priority"]] != n["channel"]:
            C.fail("workflow.notifications", f"{n['notification_id']}: channel/priority")
    for key in set(exp_notes) | set(act_notes):
        if exp_notes.get(key, set()) != act_notes.get(key, set()):
            C.fail("workflow.notifications", f"{key}: expected {sorted(exp_notes.get(key, []))} got {sorted(act_notes.get(key, []))}")
    for a in T["corrective_action"].to_dict("records"):
        act_acts[(a["trigger_type"], a["trigger_id"])].add((a["action_type"], a["assigned_role"]))
        c_, d_ = to_minutes(pd.Series([a["created_at"], a["due_at"]]))
        comp = a["completed_at"]
        done = not (comp is None or (isinstance(comp, float) and np.isnan(comp)))
        if not d_ > c_ or done != (a["outcome"] == "COMPLETED") or (done and to_minutes(pd.Series([comp]))[0] < c_):
            C.fail("workflow.actions", f"{a['action_id']}: dates/outcome")
    for key in set(exp_acts) | set(act_acts):
        if exp_acts.get(key, set()) != act_acts.get(key, set()):
            C.fail("workflow.actions", f"{key}: expected {sorted(exp_acts.get(key, []))} got {sorted(act_acts.get(key, []))}")

    H = T["excursion_status_history"].copy()
    H["m"] = to_minutes(H["changed_at"])
    hist = {eid: g.sort_values("sequence").to_dict("records") for eid, g in H.groupby("excursion_id", sort=False)}
    for eid, e in exc_info.items():
        rows = hist.get(eid, [])
        row = exc_tab[(e["shipment_id"], e["metric"], e["start_ts"])]
        ok = bool(rows) and [r["sequence"] for r in rows] == list(range(1, len(rows) + 1)) and rows[0]["status"] == "OPEN"
        if ok:
            ok = all((a["status"], b["status"]) in ALLOWED_TRANSITIONS and b["m"] >= a["m"] for a, b in zip(rows, rows[1:]))
            ok = ok and rows[-1]["status"] == row["status"] == e["final"] and (e["severity"] == "BRIEF") == (rows[-1]["status"] == "CLOSED_NO_ACTION")
        if not ok:
            C.fail("workflow.status_history", eid)
    for eid in hist:
        if eid not in exc_info:
            C.fail("workflow.status_history", f"{eid}: history without excursion")

    cu = T["custody_event"].copy()
    cu["m"] = to_minutes(cu["event_ts"])
    cust = {sid: g.sort_values("sequence").to_dict("records") for sid, g in cu.groupby("shipment_id", sort=False)}
    for sid, s in ships.items():
        ev = cust.get(sid)
        if not ev or sid not in trip:
            C.fail("workflow.custody", f"{sid}: no events")
            continue
        start, end = trip[sid]
        types = [x["event_type"] for x in ev]
        ok = [x["sequence"] for x in ev] == list(range(1, len(ev) + 1)) and all(b["m"] >= a["m"] for a, b in zip(ev, ev[1:]))
        ok = ok and types[0] == "PICKUP" and ev[0]["m"] == start and types.count("DELIVERY") == 1 and types.count("PICKUP") == 1
        deliv = next((x for x in ev if x["event_type"] == "DELIVERY"), None)
        ok = ok and deliv is not None and deliv["m"] == end
        nh = len(stops_by[sid]) - 2
        ok = ok and types.count("STOP_ARRIVAL") == nh and types.count("STOP_DEPARTURE") == nh
        exc_here = sev_by_ship.get(sid, [])
        hold = [e for e in exc_here if e["severity"] != "BRIEF"]
        rej = any(e["final"] == "REJECTED" for e in hold)
        exp_status = "REJECTED" if rej else ("RELEASED_AFTER_HOLD" if hold else "DELIVERED")
        ok = ok and (types.count("QUALITY_HOLD") == (1 if hold else 0)) and types.count("REJECT") == (1 if rej else 0) \
            and types.count("RELEASE") == (1 if (hold and not rej) else 0)
        disp = [x for x in ev if x["event_type"] in ("RELEASE", "REJECT")]
        if disp and deliv is not None:
            ok = ok and disp[0]["m"] >= deliv["m"]
        if not ok:
            C.fail("workflow.custody", sid)
        if s["status"] != exp_status:
            C.fail("shipment.status", f"{sid}: stored {s['status']} expected {exp_status}")

    # ------------------------------------------------------------------ 6. compare with ground truth
    result = {"ok": False, "checks": C.summary()}
    hard_fail = sum(v["failures"] for v in C.items.values())
    gt_keys, per_issue = set(), {}
    if gt is not None:
        g = gt.copy()
        g["subtype"] = g["subtype"].fillna("")
        gt_keys = set(zip(g["issue_type"], g["subtype"], g["entity_id"]))
        for issue in ISSUES:
            f_ = {k for k in found if k[0] == issue}
            g_ = {k for k in gt_keys if k[0] == issue}
            tp, fp, fn = len(f_ & g_), len(f_ - g_), len(g_ - f_)
            per_issue[issue] = dict(expected=len(g_), detected=len(f_), true_positive=tp, false_positive=fp, false_negative=fn,
                                    precision=round(tp / (tp + fp), 4) if tp + fp else 1.0,
                                    recall=round(tp / (tp + fn), 4) if tp + fn else 1.0,
                                    examples_fp=sorted(f_ - g_)[:3], examples_fn=sorted(g_ - f_)[:3])
        tp = sum(v["true_positive"] for v in per_issue.values())
        fp = sum(v["false_positive"] for v in per_issue.values())
        fn = sum(v["false_negative"] for v in per_issue.values())
        overall = dict(precision=round(tp / (tp + fp), 4) if tp + fp else 1.0, recall=round(tp / (tp + fn), 4) if tp + fn else 1.0,
                       true_positive=tp, false_positive=fp, false_negative=fn)
        result["ground_truth_comparison"] = {"overall": overall, "by_issue_type": per_issue}
        result["ok"] = hard_fail == 0 and fp == 0 and fn == 0
    else:
        result["ok"] = hard_fail == 0
    result["hard_failures"] = hard_fail
    result["metrics"] = metrics(T, cov, exc_info)
    return result


# ---------------------------------------------------------------------- distributions / realism
def metrics(T, cov, exc_info):
    ship, exc = T["shipment"], T["excursion"]
    prod = T["product"].set_index("product_id")["name"].to_dict()
    n_ship = len(ship)
    ex_ships = set(exc["shipment_id"])
    by_prod = {}
    for pid, g in ship.groupby("product_id"):
        n_ex = g["shipment_id"].isin(ex_ships).sum()
        by_prod[prod.get(pid, str(pid))] = dict(shipments=int(len(g)), shipments_with_excursion=int(n_ex), excursion_rate=round(n_ex / len(g), 3))
    dur = exc["duration_minutes"].astype(float)
    got = sum(a for a, _ in cov.values())
    exp = sum(b for _, b in cov.values())
    rd = T["sensor_reading"]
    t0 = to_minutes(ship["actual_departure"])
    t1 = to_minutes(ship["actual_arrival"])
    trip_days = np.abs(t1 - t0) / 1440
    return {
        "row_counts": {k: int(len(v)) for k, v in T.items()},
        "shipments": n_ship, "containers_used": int(ship["container_id"].nunique()),
        "shipments_per_container_mean": round(n_ship / max(1, ship["container_id"].nunique()), 2),
        "trip_days": {"min": round(float(trip_days.min()), 2), "mean": round(float(trip_days.mean()), 2), "max": round(float(trip_days.max()), 2)},
        "reading_coverage_pct": round(100 * got / exp, 3) if exp else None,
        "quality_flags": rd["quality_flag"].value_counts().to_dict(),
        "dropout_gaps": int(len(T["data_gap"])), "missing_readings_total": int(T["data_gap"]["missing_readings"].sum()),
        "excursions": {"total": int(len(exc)), "by_severity": exc["severity"].value_counts().to_dict(),
                       "by_metric": exc["metric"].value_counts().to_dict(),
                       "by_cause": exc["probable_cause"].value_counts().to_dict(),
                       "duration_minutes_percentiles": {f"p{q}": float(dur.quantile(q / 100)) for q in (10, 50, 90, 99)} if len(dur) else {}},
        "excursion_rate_by_product": by_prod,
        "shipment_status": ship["status"].value_counts().to_dict(),
        "temperature_c_by_product": {
            prod.get(pid, str(pid)): {"mean": round(float(g.mean()), 2), "std": round(float(g.std()), 2)}
            for pid, g in rd[rd["quality_flag"] == "GOOD"].assign(_p=rd["shipment_id"].map(ship.set_index("shipment_id")["product_id"]))
            .groupby("_p")["temperature_c"]},
    }


def to_markdown(rep) -> str:
    L = ["# Validation summary", "", f"**Overall: {'PASS' if rep['ok'] else 'FAIL'}** "
         f"(hard-invariant failures: {rep['hard_failures']})", "", "## 1. Hard invariants", "",
         "| Check | Result | Failures | What it verifies |", "|---|---|---|---|"]
    for k, v in rep["checks"].items():
        L.append(f"| `{k}` | {'pass' if v['passed'] else '**FAIL**'} | {v['failures']} | {v['description']} |")
    gtc = rep.get("ground_truth_comparison")
    if gtc:
        o = gtc["overall"]
        L += ["", "## 2. Expected anomalies vs ground truth", "",
              f"Overall precision **{o['precision']}**, recall **{o['recall']}** "
              f"(TP {o['true_positive']}, FP {o['false_positive']}, FN {o['false_negative']}).", "",
              "| Issue type | Expected | Detected | Precision | Recall |", "|---|---|---|---|---|"]
        for k, v in gtc["by_issue_type"].items():
            L.append(f"| `{k}` | {v['expected']} | {v['detected']} | {v['precision']} | {v['recall']} |")
    m = rep["metrics"]
    L += ["", "## 3. Distributions and coverage", "",
          f"- Shipments: {m['shipments']} on {m['containers_used']} containers "
          f"({m['shipments_per_container_mean']} per container); trip length {m['trip_days']['min']}-{m['trip_days']['max']} days "
          f"(mean {m['trip_days']['mean']}).",
          f"- Row counts: " + ", ".join(f"{k}={v:,}" for k, v in m["row_counts"].items()),
          f"- Reading coverage: {m['reading_coverage_pct']}% of expected 5-minute slots present; "
          f"{m['dropout_gaps']} dropout gaps ({m['missing_readings_total']} missing readings), all flagged UNVERIFIED.",
          f"- Quality flags: {m['quality_flags']}",
          f"- Excursions: {m['excursions']['total']} - by severity {m['excursions']['by_severity']}, "
          f"by metric {m['excursions']['by_metric']}, by cause {m['excursions']['by_cause']}.",
          f"- Excursion duration percentiles (min): {m['excursions']['duration_minutes_percentiles']}",
          f"- Shipment outcomes: {m['shipment_status']}", "", "| Product | Shipments | With excursion | Rate |", "|---|---|---|---|"]
    for k, v in m["excursion_rate_by_product"].items():
        L.append(f"| {k} | {v['shipments']} | {v['shipments_with_excursion']} | {v['excursion_rate']} |")
    return "\n".join(L) + "\n"


def write_reports(rep, out_dir):
    with open(os.path.join(out_dir, "validation_summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, indent=2, sort_keys=True, default=str)
        f.write("\n")
    with open(os.path.join(out_dir, "validation_summary.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(to_markdown(rep))
