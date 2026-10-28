"""Documented business rules shared by the generator and the validator."""
from __future__ import annotations

INTERVAL = 5                 # minutes between readings
STUCK_MIN_RUN = 12           # >= 12 identical consecutive (temp, rh) pairs => stuck-at sensor
GAP_ALERT_MIN_MISSING = 6    # gaps of >= 6 missing readings (30 min) raise a notification + action
ROUTE_DELAY_MIN = 120        # a leg that arrives >= 120 min late is a ROUTE_DELAY
CRITICAL_DURATION_FACTOR = 3  # duration >= 3 x permissible => CRITICAL

# Notification channel mapping (priority -> delivery channel); shared by workflow builder and validator.
CHANNEL: dict[str, str] = {"INFO": "DASHBOARD", "WARNING": "EMAIL", "CRITICAL": "SMS"}


def classify(duration_min: int, peak_dev: float, max_exc: int, crit_margin: float) -> str:
    """Severity of an excursion.

    duration = (last_out_of_range_ts - first_out_of_range_ts) + one reading interval.
    <= permissible minutes -> BRIEF (tolerated, logged); > permissible -> PROLONGED (breach);
    >= 3x permissible OR peak deviation >= critical margin -> CRITICAL.
    """
    if duration_min >= CRITICAL_DURATION_FACTOR * max_exc or peak_dev >= crit_margin:
        return "CRITICAL"
    if duration_min > max_exc:
        return "PROLONGED"
    return "BRIEF"


def final_status(severity: str, duration_min: int, peak_dev: float, max_exc: int, crit_margin: float) -> str:
    if severity == "BRIEF":
        return "CLOSED_NO_ACTION"
    if severity == "CRITICAL":
        return "REJECTED"
    return "RELEASED" if (duration_min <= 2 * max_exc and peak_dev < 0.5 * crit_margin) else "REJECTED"


def notify_roles(severity: str, metric: str, cause: str):
    """[(role, priority)] notified for an excursion."""
    if severity == "BRIEF":
        out = [("PLANT_OPERATOR", "INFO")]
    elif severity == "PROLONGED":
        out = [("PLANT_OPERATOR", "WARNING"), ("QUALITY_ENGINEER", "WARNING")]
    else:
        out = [("PLANT_OPERATOR", "CRITICAL"), ("QUALITY_ENGINEER", "CRITICAL"), ("PRODUCTION_PLANNER", "CRITICAL")]
    if severity != "BRIEF" and metric == "TEMPERATURE" and cause == "UNKNOWN_IN_TRANSIT":
        out.append(("MAINTENANCE_ENGINEER", "WARNING"))
    return out


def actions_for(severity: str, metric: str, cause: str):
    """[(action_type, role, due_hours)] raised for an excursion."""
    if severity == "BRIEF":
        out = [("LOG_AND_MONITOR", "PLANT_OPERATOR", 24)]
    elif severity == "PROLONGED":
        out = [("QUALITY_HOLD_REVIEW", "QUALITY_ENGINEER", 48)]
    else:
        out = [("QUARANTINE_AND_DISPOSITION", "QUALITY_ENGINEER", 24),
               ("REPLAN_REPLACEMENT_SHIPMENT", "PRODUCTION_PLANNER", 72)]
    if severity != "BRIEF" and metric == "TEMPERATURE" and cause == "UNKNOWN_IN_TRANSIT":
        out.append(("INSPECT_REEFER_UNIT", "MAINTENANCE_ENGINEER", 72))
    return out


ALLOWED_TRANSITIONS = {
    ("OPEN", "ACKNOWLEDGED"),
    ("ACKNOWLEDGED", "UNDER_REVIEW"),
    ("ACKNOWLEDGED", "CLOSED_NO_ACTION"),
    ("UNDER_REVIEW", "RELEASED"),
    ("UNDER_REVIEW", "REJECTED"),
}

EXPECTED_DECISION = {
    "OUT_OF_PHYSICAL_RANGE": "FLAG_SENSOR_FAULT_AND_EXCLUDE_FROM_EXCURSIONS",
    "SENSOR_DROPOUT_GAP": "FLAG_UNVERIFIED_DO_NOT_TREAT_AS_SAFE",
    "DELIVERY_BEFORE_DEPARTURE": "REJECT_RECORD_DATE_ORDER",
    "WRONG_POLICY": "REJECT_RECORD_POLICY_MISMATCH",
    "DURATION_UNDERCOUNTED": "RECOMPUTE_DURATION_FROM_READINGS",
    "CALIBRATION_FAILURE": "FLAG_LOW_TRUST_AND_RECALIBRATE",
    "ROUTE_DELAY": "NOTIFY_PLANNER_AND_REPLAN",
    "EXCURSION_BRIEF": "ACCEPT_WITHIN_TOLERANCE",
    "EXCURSION_PROLONGED": "QUALITY_HOLD_AND_REVIEW",
    "EXCURSION_CRITICAL": "REJECT_SHIPMENT",
}
