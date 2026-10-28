"""Single source of truth: tables, fields, enums, ID formats.

Everything else (SQLite DDL, data dictionary, ERD, validator checks) is derived from this file.
"""
from __future__ import annotations

from dataclasses import dataclass

TS_RE = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
DATE_RE = r"\d{4}-\d{2}-\d{2}"

R_PRD = r"PRD-\d{4}"
R_POL = r"POL-\d{6}"
R_CNT = r"CNT-\d{6}"
R_SNS = r"SNS-CNT-\d{6}-TEMP"
R_SHP = r"SHP-2026-\d{6}"
R_RST = r"RST-SHP-2026-\d{6}-\d{2}"
R_RDG = r"RDG-SNS-CNT-\d{6}-TEMP-\d{8}T\d{6}Z"
R_GAP = r"GAP-2026-\d{6}"
R_EXC = r"EXC-2026-\d{6}"
R_ESH = r"ESH-2026-\d{6}"
R_NTF = r"NTF-2026-\d{6}"
R_CUS = r"CUS-2026-\d{6}"
R_CA = r"CA-2026-\d{6}"

ROLES = ("PLANT_OPERATOR", "QUALITY_ENGINEER", "MAINTENANCE_ENGINEER", "PRODUCTION_PLANNER", "OT_IT_ADMIN")

ENUMS = {
    "category": ("VACCINE", "PHARMA_COLD", "FROZEN_FOOD", "CHILLED_FOOD", "PRODUCE", "FROZEN_PHARMA"),
    "container_type": ("REEFER_40FT", "REEFER_20FT", "INSULATED_SHIPPER"),
    "container_status": ("ACTIVE",),
    "shipment_status": ("DELIVERED", "RELEASED_AFTER_HOLD", "REJECTED"),
    "stop_type": ("ORIGIN", "TRANSIT_HUB", "DESTINATION"),
    "quality": ("GOOD", "LOW_TRUST", "SENSOR_FAULT"),
    "metric": ("TEMPERATURE", "HUMIDITY"),
    "direction": ("HIGH", "LOW"),
    "severity": ("BRIEF", "PROLONGED", "CRITICAL"),
    "evidence": ("VERIFIED", "LOW_TRUST"),
    "cause": ("ROUTE_DELAY", "UNKNOWN_IN_TRANSIT"),
    "exc_status": ("OPEN", "ACKNOWLEDGED", "UNDER_REVIEW", "RELEASED", "REJECTED", "CLOSED_NO_ACTION"),
    "role": ROLES,
    "actor": ROLES + ("SYSTEM",),
    "trigger": ("EXCURSION", "DATA_GAP", "CALIBRATION", "ROUTE_DELAY"),
    "priority": ("INFO", "WARNING", "CRITICAL"),
    "channel": ("DASHBOARD", "EMAIL", "SMS"),
    "custody": ("PICKUP", "STOP_ARRIVAL", "STOP_DEPARTURE", "QUALITY_HOLD", "DELIVERY", "RELEASE", "REJECT"),
    "action_type": ("LOG_AND_MONITOR", "QUALITY_HOLD_REVIEW", "QUARANTINE_AND_DISPOSITION",
                    "REPLAN_REPLACEMENT_SHIPMENT", "INSPECT_REEFER_UNIT", "INVESTIGATE_SENSOR_DROPOUT",
                    "RECALIBRATE_SENSOR", "REPLAN_DELIVERY"),
    "outcome": ("COMPLETED", "OPEN"),
    "gap_status": ("UNVERIFIED",),
}

FORBIDDEN_INPUT_COLUMNS = {"issue_type", "ground_truth", "scenario", "expected_decision", "injected", "subtype", "gt_id"}


@dataclass(frozen=True)
class Field:
    name: str
    type: str  # id | text | int | real | ts | date
    required: bool = True
    allowed: tuple | None = None
    unit: str = ""
    rule: str = ""
    fk: str | None = None  # "table.column"
    regex: str | None = None
    unique: bool = False


@dataclass(frozen=True)
class Table:
    name: str
    title: str
    pk: str
    description: str
    fields: tuple


def F(name, type_, *, req=True, allowed=None, unit="", rule="", fk=None, regex=None, unique=False):
    return Field(name, type_, req, allowed, unit, rule, fk, regex, unique)


TABLES: tuple[Table, ...] = (
    Table("product", "Product", "product_id", "Cold-chain product with its target storage conditions.", (
        F("product_id", "id", regex=R_PRD, rule="PRD-0001 format; zero-padded, immutable"),
        F("name", "text", unique=True),
        F("category", "text", allowed=ENUMS["category"]),
        F("target_temp_c", "real", unit="degC", rule="midpoint of the policy range"),
        F("target_rh_pct", "real", unit="%RH", rule="midpoint of the policy range"),
    )),
    Table("threshold_policy", "ThresholdPolicy", "policy_id",
          "Product-specific limits and permissible excursion duration, with effective dates (2 versions per product).", (
        F("policy_id", "id", regex=R_POL),
        F("product_id", "id", fk="product.product_id", regex=R_PRD),
        F("version", "int", rule="1 or 2; v2 is stricter (shorter permissible duration)"),
        F("temp_min_c", "real", unit="degC", rule="< temp_max_c"),
        F("temp_max_c", "real", unit="degC"),
        F("rh_min_pct", "real", unit="%RH", rule="< rh_max_pct"),
        F("rh_max_pct", "real", unit="%RH"),
        F("max_excursion_minutes", "int", unit="min", rule="multiple of 5; permissible out-of-range duration"),
        F("critical_margin_temp_c", "real", unit="degC", rule="deviation beyond limit that makes an excursion CRITICAL"),
        F("critical_margin_rh_pct", "real", unit="%RH", rule="same, for humidity"),
        F("effective_from", "date", regex=DATE_RE),
        F("effective_to", "date", req=False, regex=DATE_RE, rule="NULL = open-ended; windows of a product never overlap"),
    )),
    Table("container", "Container", "container_id", "Reefer container or insulated shipper.", (
        F("container_id", "id", regex=R_CNT),
        F("container_type", "text", allowed=ENUMS["container_type"]),
        F("status", "text", allowed=ENUMS["container_status"]),
    )),
    Table("sensor", "Sensor", "sensor_id", "Combined temperature/humidity logger, one per container (1:1).", (
        F("sensor_id", "id", regex=R_SNS, rule="SNS-CNT-<container number>-TEMP"),
        F("container_id", "id", fk="container.container_id", regex=R_CNT, unique=True),
        F("calibration_date", "date", regex=DATE_RE),
        F("calibration_due", "date", regex=DATE_RE, rule="> calibration_date; shipments departing after this date are LOW_TRUST"),
        F("valid_temp_min_c", "real", unit="degC", rule="physical range of the probe"),
        F("valid_temp_max_c", "real", unit="degC"),
        F("valid_rh_min_pct", "real", unit="%RH"),
        F("valid_rh_max_pct", "real", unit="%RH"),
    )),
    Table("shipment", "Shipment", "shipment_id", "A product moving in one container from origin to destination.", (
        F("shipment_id", "id", regex=R_SHP),
        F("product_id", "id", fk="product.product_id", regex=R_PRD),
        F("container_id", "id", fk="container.container_id", regex=R_CNT, rule="no two shipments of a container overlap in time"),
        F("policy_id", "id", fk="threshold_policy.policy_id", regex=R_POL,
          rule="policy.product_id = shipment.product_id and effective on planned_departure date"),
        F("origin", "text"),
        F("destination", "text"),
        F("planned_departure", "ts", regex=TS_RE, rule="< planned_arrival"),
        F("planned_arrival", "ts", regex=TS_RE),
        F("actual_departure", "ts", regex=TS_RE, rule="< actual_arrival"),
        F("actual_arrival", "ts", regex=TS_RE, rule="trip length 2-5 days"),
        F("status", "text", allowed=ENUMS["shipment_status"], rule="derived from excursion dispositions"),
    )),
    Table("route_stop", "RouteStop", "route_stop_id", "Ordered stops of a shipment (origin, 1-3 transit hubs, destination).", (
        F("route_stop_id", "id", regex=R_RST),
        F("shipment_id", "id", fk="shipment.shipment_id", regex=R_SHP),
        F("sequence", "int", rule="1..n contiguous per shipment"),
        F("stop_type", "text", allowed=ENUMS["stop_type"]),
        F("location", "text"),
        F("planned_arrival", "ts", regex=TS_RE),
        F("planned_departure", "ts", regex=TS_RE),
        F("actual_arrival", "ts", regex=TS_RE),
        F("actual_departure", "ts", regex=TS_RE),
        F("delay_minutes", "int", unit="min", rule="= actual_arrival - planned_arrival"),
    )),
    Table("sensor_reading", "SensorReading", "reading_id", "One temperature/humidity reading every 5 minutes.", (
        F("reading_id", "id", regex=R_RDG, rule="RDG-<sensor_id>-<UTC timestamp yyyymmddThhmmssZ>"),
        F("sensor_id", "id", fk="sensor.sensor_id", regex=R_SNS),
        F("shipment_id", "id", fk="shipment.shipment_id", regex=R_SHP),
        F("route_stop_id", "id", req=False, fk="route_stop.route_stop_id", regex=R_RST,
          rule="set while the container is at that stop, else NULL"),
        F("timestamp", "ts", regex=TS_RE, rule="exact 5-minute cadence; gaps are listed in data_gap"),
        F("temperature_c", "real", unit="degC", rule="outside sensor valid range => SENSOR_FAULT"),
        F("humidity_pct", "real", unit="%RH"),
        F("quality_flag", "text", allowed=ENUMS["quality"],
          rule="SENSOR_FAULT: outside physical range; LOW_TRUST: stuck-at run or expired calibration; else GOOD"),
    )),
    Table("data_gap", "DataGap", "gap_id",
          "Missing-reading interval. Always flagged UNVERIFIED; a gap is never treated as in-range.", (
        F("gap_id", "id", regex=R_GAP),
        F("shipment_id", "id", fk="shipment.shipment_id", regex=R_SHP),
        F("sensor_id", "id", fk="sensor.sensor_id", regex=R_SNS),
        F("last_reading_ts", "ts", regex=TS_RE, rule="last reading before the gap"),
        F("next_reading_ts", "ts", regex=TS_RE, rule="first reading after the gap"),
        F("missing_readings", "int", rule="= (next - last) / 5 min - 1"),
        F("status", "text", allowed=ENUMS["gap_status"]),
    )),
    Table("excursion", "Excursion", "excursion_id",
          "Maximal run of consecutive readings outside the policy range, derived from readings.", (
        F("excursion_id", "id", regex=R_EXC),
        F("shipment_id", "id", fk="shipment.shipment_id", regex=R_SHP),
        F("sensor_id", "id", fk="sensor.sensor_id", regex=R_SNS),
        F("policy_id", "id", fk="threshold_policy.policy_id", regex=R_POL, rule="policy effective for the shipment"),
        F("metric", "text", allowed=ENUMS["metric"]),
        F("direction", "text", allowed=ENUMS["direction"]),
        F("start_ts", "ts", regex=TS_RE, rule="first out-of-range reading"),
        F("end_ts", "ts", regex=TS_RE, rule="last out-of-range reading"),
        F("duration_minutes", "int", unit="min", rule="= (end_ts - start_ts) + 5 min"),
        F("peak_value", "real", unit="degC or %RH", rule="max (HIGH) / min (LOW) in the run"),
        F("peak_deviation", "real", unit="degC or %RH", rule="|peak_value - violated limit|"),
        F("severity", "text", allowed=ENUMS["severity"], rule="see rules.classify"),
        F("evidence_quality", "text", allowed=ENUMS["evidence"], rule="LOW_TRUST if any reading in the run is LOW_TRUST"),
        F("probable_cause", "text", allowed=ENUMS["cause"], rule="ROUTE_DELAY if it starts inside a leg delayed >= 120 min"),
        F("detected_at", "ts", regex=TS_RE, rule="= end_ts + 5 min"),
        F("status", "text", allowed=ENUMS["exc_status"], rule="latest status in excursion_status_history"),
    )),
    Table("excursion_status_history", "ExcursionStatusHistory", "history_id",
          "Append-only status log: state changes are rows, history is never overwritten.", (
        F("history_id", "id", regex=R_ESH),
        F("excursion_id", "id", fk="excursion.excursion_id", regex=R_EXC),
        F("sequence", "int", rule="1..n contiguous per excursion"),
        F("status", "text", allowed=ENUMS["exc_status"], rule="only OPEN>ACKNOWLEDGED>UNDER_REVIEW>RELEASED|REJECTED or >CLOSED_NO_ACTION"),
        F("changed_at", "ts", regex=TS_RE, rule="non-decreasing within an excursion"),
        F("actor_role", "text", allowed=ENUMS["actor"]),
    )),
    Table("notification", "Notification", "notification_id", "Alert sent to a role when something needs attention.", (
        F("notification_id", "id", regex=R_NTF),
        F("trigger_type", "text", allowed=ENUMS["trigger"]),
        F("trigger_id", "id", rule="excursion_id | gap_id | shipment_id (CALIBRATION) | route_stop_id (ROUTE_DELAY)"),
        F("shipment_id", "id", fk="shipment.shipment_id", regex=R_SHP),
        F("recipient_role", "text", allowed=ENUMS["role"]),
        F("priority", "text", allowed=ENUMS["priority"]),
        F("channel", "text", allowed=ENUMS["channel"]),
        F("sent_at", "ts", regex=TS_RE),
    )),
    Table("custody_event", "CustodyEvent", "custody_id", "Chain-of-custody log per shipment.", (
        F("custody_id", "id", regex=R_CUS),
        F("shipment_id", "id", fk="shipment.shipment_id", regex=R_SHP),
        F("sequence", "int", rule="1..n contiguous; timestamps non-decreasing"),
        F("event_type", "text", allowed=ENUMS["custody"]),
        F("event_ts", "ts", regex=TS_RE),
        F("from_party", "text"),
        F("to_party", "text"),
    )),
    Table("corrective_action", "CorrectiveAction", "action_id", "Task assigned to a role in response to a trigger.", (
        F("action_id", "id", regex=R_CA),
        F("trigger_type", "text", allowed=ENUMS["trigger"]),
        F("trigger_id", "id"),
        F("shipment_id", "id", fk="shipment.shipment_id", regex=R_SHP),
        F("action_type", "text", allowed=ENUMS["action_type"]),
        F("assigned_role", "text", allowed=ENUMS["role"]),
        F("created_at", "ts", regex=TS_RE),
        F("due_at", "ts", regex=TS_RE, rule="> created_at"),
        F("completed_at", "ts", req=False, regex=TS_RE, rule="NULL iff outcome = OPEN; >= created_at"),
        F("outcome", "text", allowed=ENUMS["outcome"]),
    )),
)

TABLE_MAP = {t.name: t for t in TABLES}
SQL_TYPE = {"id": "TEXT", "text": "TEXT", "ts": "TEXT", "date": "TEXT", "int": "INTEGER", "real": "REAL"}


def columns(table: str) -> list[str]:
    return [f.name for f in TABLE_MAP[table].fields]


def ddl() -> str:
    out = ["PRAGMA foreign_keys = ON;", ""]
    for t in TABLES:
        cols, fks = [], []
        for f in t.fields:
            parts = [f.name, SQL_TYPE[f.type]]
            if f.name == t.pk:
                parts.append("PRIMARY KEY")
            elif f.required:
                parts.append("NOT NULL")
            if f.unique and f.name != t.pk:
                parts.append("UNIQUE")
            if f.allowed:
                vals = ", ".join(f"'{v}'" for v in f.allowed)
                parts.append(f"CHECK ({f.name} IN ({vals}))")
            cols.append("  " + " ".join(parts))
            if f.fk:
                pt, pc = f.fk.split(".")
                fks.append(f"  FOREIGN KEY ({f.name}) REFERENCES {pt}({pc})")
        out.append(f"CREATE TABLE {t.name} (\n" + ",\n".join(cols + fks) + "\n);")
        out.append("")
    out.append("CREATE INDEX idx_reading_shipment_ts ON sensor_reading (shipment_id, timestamp);")
    out.append("CREATE INDEX idx_excursion_shipment ON excursion (shipment_id);")
    return "\n".join(out) + "\n"


def data_dictionary_md() -> str:
    L = ["# Data dictionary", "",
         "Generated from `src/coldchain/schema.py` (`python -m coldchain docs`). All timestamps are ISO-8601 UTC.",
         "`NULL` is written as an empty CSV cell.", ""]
    for t in TABLES:
        L += [f"## {t.title} (`{t.name}`)", "", t.description, "",
              "| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |",
              "|---|---|---|---|---|---|---|"]
        for f in t.fields:
            fmt = ", ".join(f.allowed) if f.allowed else (f"`{f.regex}`" if f.regex else "")
            link = []
            if f.name == t.pk:
                link.append("PK")
            if f.unique and f.name != t.pk:
                link.append("unique")
            if f.fk:
                link.append(f"FK > {f.fk}")
            L.append(f"| `{f.name}` | {f.type} | {'yes' if f.required else 'no'} | {fmt} | {f.unit} | {', '.join(link)} | {f.rule} |")
        L.append("")
    return "\n".join(L)


def erd_md() -> str:
    L = ["# Entity-relationship diagram", "", "```mermaid", "erDiagram"]
    for t in TABLES:
        for f in t.fields:
            if f.fk:
                pt = f.fk.split(".")[0]
                card = "||--o|" if f.unique else "||--o{"
                L.append(f"    {pt.upper()} {card} {t.name.upper()} : \"{f.name}\"")
    for t in TABLES:
        L.append(f"    {t.name.upper()} {{")
        for f in t.fields:
            tag = " PK" if f.name == t.pk else (" FK" if f.fk else "")
            L.append(f"        {f.type} {f.name}{tag}")
        L.append("    }")
    L += [
        "```", "",
        "`notification.trigger_id` and `corrective_action.trigger_id` are polymorphic references "
        "(excursion / data gap / shipment / route stop) selected by `trigger_type`; they are validated by "
        "`coldchain validate` instead of a SQL foreign key.", "",
        "---", "",
        "## Entity Relationships & Cardinality Summary", "",
        "| Parent Entity | Child Entity | Foreign Key | Cardinality | Relationship Nature / Description |",
        "|---|---|---|---|---|",
        "| `PRODUCT` | `THRESHOLD_POLICY` | `product_id` | **1 : N** | One product has multiple policy versions (v1, v2) with effective date windows. |",
        "| `CONTAINER` | `SENSOR` | `container_id` | **1 : 1** | One combined temp/humidity logger attached per container. |",
        "| `PRODUCT` | `SHIPMENT` | `product_id` | **1 : N** | One product type is transported across many shipments. |",
        "| `CONTAINER` | `SHIPMENT` | `container_id` | **1 : N** | A physical container is reused across ~3.4 sequential shipments (non-overlapping). |",
        "| `THRESHOLD_POLICY` | `SHIPMENT` | `policy_id` | **1 : N** | Bound by `product_id` and effective date at shipment planned departure. |",
        "| `SHIPMENT` | `ROUTE_STOP` | `shipment_id` | **1 : N** | Ordered route sequence (origin, 1–3 transit hubs, destination). |",
        "| `SENSOR` | `SENSOR_READING` | `sensor_id` | **1 : N** | Continuous 5-minute telemetry readings recorded by the container's probe. |",
        "| `SHIPMENT` | `SENSOR_READING` | `shipment_id` | **1 : N** | Readings scoped to the active transit window of the shipment. |",
        "| `ROUTE_STOP` | `SENSOR_READING` | `route_stop_id` | **1 : N (optional)** | Set while container is dwell-logged at a stop; `NULL` while in transit. |",
        "| `SHIPMENT` | `DATA_GAP` | `shipment_id` | **1 : N (optional)** | Gaps where reading cadence > 5 min; flagged `UNVERIFIED`. |",
        "| `SHIPMENT` | `EXCURSION` | `shipment_id` | **1 : N (optional)** | Maximal consecutive out-of-range runs detected for the shipment. |",
        "| `EXCURSION` | `EXCURSION_STATUS_HISTORY` | `excursion_id` | **1 : N** | Append-only audit log tracking lifecycle state transitions over time. |",
        "| `SHIPMENT` | `NOTIFICATION` | `shipment_id` | **1 : N** | Role alerts routed to plant operator, quality, maintenance, planner, OT/IT. |",
        "| `SHIPMENT` | `CUSTODY_EVENT` | `shipment_id` | **1 : N** | Chronological chain-of-custody handoffs and disposition milestones. |",
        "| `SHIPMENT` | `CORRECTIVE_ACTION` | `shipment_id` | **1 : N** | Tracked remedial tasks with roles, due dates, and completion status. |",
        "",
        "---", "",
        "## Many-to-many relationships", "",
        "- **Product N:M Container** (a container carries different products over time; a product travels in many containers) is "
        "resolved by `SHIPMENT`, the bridge/association table. It carries `product_id`, `container_id`, `policy_id`, the route, "
        "times and status, so no separate join table is needed.",
        "- All other relationships are 1:1 (`CONTAINER`-`SENSOR`) or 1:N, some optional (`SHIPMENT` > `EXCURSION`, "
        "`DATA_GAP`, `NOTIFICATION`, `CORRECTIVE_ACTION`).",
        "", "---", "",
        "## Lifecycle States & Effective Dates", "",
        "### Effective Dates",
        "- **`threshold_policy.effective_from` & `effective_to`**: Version 1 is active from `2025-01-01` to `2026-06-30`. Version 2 introduces tighter tolerance windows active from `2026-07-01` onwards. Each shipment binds to the policy version effective on its `planned_departure`.",
        "- **`sensor.calibration_date` & `calibration_due`**: Most sensors carry a long calibration interval; about 5 % have a lapsed calibration during the year. If `shipment.actual_departure > sensor.calibration_due`, readings are downgraded to `LOW_TRUST` and trigger a `RECALIBRATE_SENSOR` corrective action.",
        "",
        "### Lifecycle States",
        "- **Shipment Lifecycle**: `DELIVERED` (normal completed journey) | `RELEASED_AFTER_HOLD` (excursion reviewed and approved by quality team) | `REJECTED` (critical excursion or damaged product rejected and replanned).",
        "- **Excursion Status Transitions (Append-Only History)**:",
        "  - Brief Excursion: `OPEN` → `ACKNOWLEDGED` → `CLOSED_NO_ACTION`",
        "  - Prolonged / Critical Excursion: `OPEN` → `ACKNOWLEDGED` → `UNDER_REVIEW` → `RELEASED` or `REJECTED`",
        "- **Corrective Action Outcomes**: `OPEN` → `COMPLETED`",
        "- **Sensor Reading Quality Codes**: `GOOD` | `LOW_TRUST` (sensor stuck or calibration overdue) | `SENSOR_FAULT` (out of physical hardware range)",
        "- **Data Gap Status**: `UNVERIFIED` (missing intervals never assumed safe)",
        ""
    ]
    return "\n".join(L)
