# Entity-relationship diagram

```mermaid
erDiagram
    PRODUCT ||--o{ THRESHOLD_POLICY : "product_id"
    CONTAINER ||--o| SENSOR : "container_id"
    PRODUCT ||--o{ SHIPMENT : "product_id"
    CONTAINER ||--o{ SHIPMENT : "container_id"
    THRESHOLD_POLICY ||--o{ SHIPMENT : "policy_id"
    SHIPMENT ||--o{ ROUTE_STOP : "shipment_id"
    SENSOR ||--o{ SENSOR_READING : "sensor_id"
    SHIPMENT ||--o{ SENSOR_READING : "shipment_id"
    ROUTE_STOP ||--o{ SENSOR_READING : "route_stop_id"
    SHIPMENT ||--o{ DATA_GAP : "shipment_id"
    SENSOR ||--o{ DATA_GAP : "sensor_id"
    SHIPMENT ||--o{ EXCURSION : "shipment_id"
    SENSOR ||--o{ EXCURSION : "sensor_id"
    THRESHOLD_POLICY ||--o{ EXCURSION : "policy_id"
    EXCURSION ||--o{ EXCURSION_STATUS_HISTORY : "excursion_id"
    SHIPMENT ||--o{ NOTIFICATION : "shipment_id"
    SHIPMENT ||--o{ CUSTODY_EVENT : "shipment_id"
    SHIPMENT ||--o{ CORRECTIVE_ACTION : "shipment_id"
    PRODUCT {
        id product_id PK
        text name
        text category
        real target_temp_c
        real target_rh_pct
    }
    THRESHOLD_POLICY {
        id policy_id PK
        id product_id FK
        int version
        real temp_min_c
        real temp_max_c
        real rh_min_pct
        real rh_max_pct
        int max_excursion_minutes
        real critical_margin_temp_c
        real critical_margin_rh_pct
        date effective_from
        date effective_to
    }
    CONTAINER {
        id container_id PK
        text container_type
        text status
    }
    SENSOR {
        id sensor_id PK
        id container_id FK
        date calibration_date
        date calibration_due
        real valid_temp_min_c
        real valid_temp_max_c
        real valid_rh_min_pct
        real valid_rh_max_pct
    }
    SHIPMENT {
        id shipment_id PK
        id product_id FK
        id container_id FK
        id policy_id FK
        text origin
        text destination
        ts planned_departure
        ts planned_arrival
        ts actual_departure
        ts actual_arrival
        text status
    }
    ROUTE_STOP {
        id route_stop_id PK
        id shipment_id FK
        int sequence
        text stop_type
        text location
        ts planned_arrival
        ts planned_departure
        ts actual_arrival
        ts actual_departure
        int delay_minutes
    }
    SENSOR_READING {
        id reading_id PK
        id sensor_id FK
        id shipment_id FK
        id route_stop_id FK
        ts timestamp
        real temperature_c
        real humidity_pct
        text quality_flag
    }
    DATA_GAP {
        id gap_id PK
        id shipment_id FK
        id sensor_id FK
        ts last_reading_ts
        ts next_reading_ts
        int missing_readings
        text status
    }
    EXCURSION {
        id excursion_id PK
        id shipment_id FK
        id sensor_id FK
        id policy_id FK
        text metric
        text direction
        ts start_ts
        ts end_ts
        int duration_minutes
        real peak_value
        real peak_deviation
        text severity
        text evidence_quality
        text probable_cause
        ts detected_at
        text status
    }
    EXCURSION_STATUS_HISTORY {
        id history_id PK
        id excursion_id FK
        int sequence
        text status
        ts changed_at
        text actor_role
    }
    NOTIFICATION {
        id notification_id PK
        text trigger_type
        id trigger_id
        id shipment_id FK
        text recipient_role
        text priority
        text channel
        ts sent_at
    }
    CUSTODY_EVENT {
        id custody_id PK
        id shipment_id FK
        int sequence
        text event_type
        ts event_ts
        text from_party
        text to_party
    }
    CORRECTIVE_ACTION {
        id action_id PK
        text trigger_type
        id trigger_id
        id shipment_id FK
        text action_type
        text assigned_role
        ts created_at
        ts due_at
        ts completed_at
        text outcome
    }
```

`notification.trigger_id` and `corrective_action.trigger_id` are polymorphic references (excursion / data gap / shipment / route stop) selected by `trigger_type`; they are validated by `coldchain validate` instead of a SQL foreign key.

---

## Entity Relationships & Cardinality Summary

| Parent Entity | Child Entity | Foreign Key | Cardinality | Relationship Nature / Description |
|---|---|---|---|---|
| `PRODUCT` | `THRESHOLD_POLICY` | `product_id` | **1 : N** | One product has multiple policy versions (v1, v2) with effective date windows. |
| `CONTAINER` | `SENSOR` | `container_id` | **1 : 1** | One combined temp/humidity logger attached per container. |
| `PRODUCT` | `SHIPMENT` | `product_id` | **1 : N** | One product type is transported across many shipments. |
| `CONTAINER` | `SHIPMENT` | `container_id` | **1 : N** | A physical container is reused across ~3.4 sequential shipments (non-overlapping). |
| `THRESHOLD_POLICY` | `SHIPMENT` | `policy_id` | **1 : N** | Bound by `product_id` and effective date at shipment planned departure. |
| `SHIPMENT` | `ROUTE_STOP` | `shipment_id` | **1 : N** | Ordered route sequence (origin, 1–3 transit hubs, destination). |
| `SENSOR` | `SENSOR_READING` | `sensor_id` | **1 : N** | Continuous 5-minute telemetry readings recorded by the container's probe. |
| `SHIPMENT` | `SENSOR_READING` | `shipment_id` | **1 : N** | Readings scoped to the active transit window of the shipment. |
| `ROUTE_STOP` | `SENSOR_READING` | `route_stop_id` | **1 : N (optional)** | Set while container is dwell-logged at a stop; `NULL` while in transit. |
| `SHIPMENT` | `DATA_GAP` | `shipment_id` | **1 : N (optional)** | Gaps where reading cadence > 5 min; flagged `UNVERIFIED`. |
| `SHIPMENT` | `EXCURSION` | `shipment_id` | **1 : N (optional)** | Maximal consecutive out-of-range runs detected for the shipment. |
| `EXCURSION` | `EXCURSION_STATUS_HISTORY` | `excursion_id` | **1 : N** | Append-only audit log tracking lifecycle state transitions over time. |
| `SHIPMENT` | `NOTIFICATION` | `shipment_id` | **1 : N** | Role alerts routed to plant operator, quality, maintenance, planner, OT/IT. |
| `SHIPMENT` | `CUSTODY_EVENT` | `shipment_id` | **1 : N** | Chronological chain-of-custody handoffs and disposition milestones. |
| `SHIPMENT` | `CORRECTIVE_ACTION` | `shipment_id` | **1 : N** | Tracked remedial tasks with roles, due dates, and completion status. |

---

## Many-to-many relationships

- **Product N:M Container** (a container carries different products over time; a product travels in many containers) is resolved by `SHIPMENT`, the bridge/association table. It carries `product_id`, `container_id`, `policy_id`, the route, times and status, so no separate join table is needed.
- All other relationships are 1:1 (`CONTAINER`-`SENSOR`) or 1:N, some optional (`SHIPMENT` > `EXCURSION`, `DATA_GAP`, `NOTIFICATION`, `CORRECTIVE_ACTION`).

---

## Lifecycle States & Effective Dates

### Effective Dates
- **`threshold_policy.effective_from` & `effective_to`**: Version 1 is active from `2025-01-01` to `2026-06-30`. Version 2 introduces tighter tolerance windows active from `2026-07-01` onwards. Each shipment binds to the policy version effective on its `planned_departure`.
- **`sensor.calibration_date` & `calibration_due`**: Most sensors carry a long calibration interval; about 5 % have a lapsed calibration during the year. If `shipment.actual_departure > sensor.calibration_due`, readings are downgraded to `LOW_TRUST` and trigger a `RECALIBRATE_SENSOR` corrective action.

### Lifecycle States
- **Shipment Lifecycle**: `DELIVERED` (normal completed journey) | `RELEASED_AFTER_HOLD` (excursion reviewed and approved by quality team) | `REJECTED` (critical excursion or damaged product rejected and replanned).
- **Excursion Status Transitions (Append-Only History)**:
  - Brief Excursion: `OPEN` → `ACKNOWLEDGED` → `CLOSED_NO_ACTION`
  - Prolonged / Critical Excursion: `OPEN` → `ACKNOWLEDGED` → `UNDER_REVIEW` → `RELEASED` or `REJECTED`
- **Corrective Action Outcomes**: `OPEN` → `COMPLETED`
- **Sensor Reading Quality Codes**: `GOOD` | `LOW_TRUST` (sensor stuck or calibration overdue) | `SENSOR_FAULT` (out of physical hardware range)
- **Data Gap Status**: `UNVERIFIED` (missing intervals never assumed safe)
