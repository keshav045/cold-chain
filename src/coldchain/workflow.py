"""Derives notifications, corrective actions, status history and custody events from detected facts."""
from __future__ import annotations

from .rules import (CHANNEL, GAP_ALERT_MIN_MISSING, actions_for, final_status, notify_roles)

# Custody-event sort priority: lower number = appears earlier in the sequence.
PRIO = {"PICKUP": 0, "STOP_ARRIVAL": 1, "STOP_DEPARTURE": 2, "QUALITY_HOLD": 3, "DELIVERY": 4, "RELEASE": 5, "REJECT": 5}


def build(rng, trips, excursions, gaps, delays, lowtrust_first):
    """Inputs use epoch-minutes. Returns dict of row-lists (still in minutes, without IDs).

    excursions: dicts with exc_id, shipment_id, severity, metric, cause, start_ts, end_ts, duration,
                peak_deviation, policy (dict)
    gaps: dicts with gap_id, shipment_id, next_ts, missing
    delays: dicts with shipment_id, route_stop_id, arrival
    lowtrust_first: {shipment_id: first LOW_TRUST reading ts}
    """
    notes, acts, hist, cust = [], [], [], []
    holds = {}  # shipment_id -> list[(detected_at, final_ts, final_status)]
    trip_by = {t.shipment_id: t for t in trips}

    def notify(ttype, tid, sid, role, prio, t):
        notes.append(dict(trigger_type=ttype, trigger_id=tid, shipment_id=sid, recipient_role=role,
                          priority=prio, channel=CHANNEL[prio], sent_at=t + int(rng.integers(1, 10))))

    def act(ttype, tid, sid, atype, role, due_h, t):
        created = t + int(rng.integers(5, 31))
        due = created + due_h * 60
        done = rng.random() < 0.9
        acts.append(dict(trigger_type=ttype, trigger_id=tid, shipment_id=sid, action_type=atype, assigned_role=role,
                         created_at=created, due_at=due,
                         completed_at=(created + int(rng.integers(30, due_h * 60))) if done else None,
                         outcome="COMPLETED" if done else "OPEN"))

    for e in excursions:
        sid, det = e["shipment_id"], e["end_ts"] + 5
        e["detected_at"] = det
        for role, prio in notify_roles(e["severity"], e["metric"], e["cause"]):
            notify("EXCURSION", e["exc_id"], sid, role, prio, det)
        for atype, role, due_h in actions_for(e["severity"], e["metric"], e["cause"]):
            act("EXCURSION", e["exc_id"], sid, atype, role, due_h, det)
        pol = e["policy"]
        crit = pol["critical_margin_temp_c"] if e["metric"] == "TEMPERATURE" else pol["critical_margin_rh_pct"]
        fin = final_status(e["severity"], e["duration"], e["peak_deviation"], pol["max_excursion_minutes"], crit)
        t_ack = det + int(rng.integers(5, 61))
        rows = [("OPEN", det, "SYSTEM"), ("ACKNOWLEDGED", t_ack, "PLANT_OPERATOR")]
        if e["severity"] == "BRIEF":
            rows.append((fin, t_ack + int(rng.integers(30, 241)), "PLANT_OPERATOR"))
        else:
            t_rev = t_ack + int(rng.integers(30, 241))
            t_fin = max(t_rev + int(rng.integers(60, 1441)), trip_by[sid].end + int(rng.integers(15, 121)))
            rows += [("UNDER_REVIEW", t_rev, "QUALITY_ENGINEER"), (fin, t_fin, "QUALITY_ENGINEER")]
            holds.setdefault(sid, []).append((det, t_fin, fin))
        e["status"] = fin
        for k, (st, t, who) in enumerate(rows, start=1):
            hist.append(dict(excursion_id=e["exc_id"], sequence=k, status=st, changed_at=t, actor_role=who))

    for g in gaps:
        if g["missing"] >= GAP_ALERT_MIN_MISSING:
            notify("DATA_GAP", g["gap_id"], g["shipment_id"], "OT_IT_ADMIN", "WARNING", g["next_ts"])
            act("DATA_GAP", g["gap_id"], g["shipment_id"], "INVESTIGATE_SENSOR_DROPOUT", "OT_IT_ADMIN", 72, g["next_ts"])
    for sid, t in lowtrust_first.items():
        notify("CALIBRATION", sid, sid, "OT_IT_ADMIN", "WARNING", t + 5)
        act("CALIBRATION", sid, sid, "RECALIBRATE_SENSOR", "OT_IT_ADMIN", 120, t + 5)
    for d in delays:
        notify("ROUTE_DELAY", d["route_stop_id"], d["shipment_id"], "PRODUCTION_PLANNER", "WARNING", d["arrival"])
        act("ROUTE_DELAY", d["route_stop_id"], d["shipment_id"], "REPLAN_DELIVERY", "PRODUCTION_PLANNER", 24, d["arrival"])

    status = {}
    for t in trips:
        ev = [(t.dep, "PICKUP", "PLANT", "CARRIER")]
        for st in t.stops[1:-1]:
            ev.append((st["aa"], "STOP_ARRIVAL", "CARRIER", st["loc"].upper().replace(" ", "_")))
            ev.append((st["ad"], "STOP_DEPARTURE", st["loc"].upper().replace(" ", "_"), "CARRIER"))
        ev.append((t.end, "DELIVERY", "CARRIER", "CUSTOMER"))
        h = holds.get(t.shipment_id)
        if h:
            ev.append((min(x[0] for x in h), "QUALITY_HOLD", "CARRIER", "QUALITY_TEAM"))
            rejected = any(x[2] == "REJECTED" for x in h)
            ev.append((max(x[1] for x in h), "REJECT" if rejected else "RELEASE", "QUALITY_TEAM",
                       "DISPOSAL" if rejected else "CUSTOMER"))
            status[t.shipment_id] = "REJECTED" if rejected else "RELEASED_AFTER_HOLD"
        else:
            status[t.shipment_id] = "DELIVERED"
        ev.sort(key=lambda x: (x[0], PRIO.get(x[1], 99)))
        for k, (ts_, typ, fr, to) in enumerate(ev, start=1):
            cust.append(dict(shipment_id=t.shipment_id, sequence=k, event_type=typ, event_ts=ts_, from_party=fr, to_party=to))
    return dict(notifications=notes, actions=acts, history=hist, custody=cust, shipment_status=status)
