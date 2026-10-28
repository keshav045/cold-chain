# Data dictionary

Generated from `src/coldchain/schema.py` (`python -m coldchain docs`). All timestamps are ISO-8601 UTC.
`NULL` is written as an empty CSV cell.

## Product (`product`)

Cold-chain product with its target storage conditions.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `product_id` | id | yes | `PRD-\d{4}` |  | PK | PRD-0001 format; zero-padded, immutable |
| `name` | text | yes |  |  | unique |  |
| `category` | text | yes | VACCINE, PHARMA_COLD, FROZEN_FOOD, CHILLED_FOOD, PRODUCE, FROZEN_PHARMA |  |  |  |
| `target_temp_c` | real | yes |  | degC |  | midpoint of the policy range |
| `target_rh_pct` | real | yes |  | %RH |  | midpoint of the policy range |

## ThresholdPolicy (`threshold_policy`)

Product-specific limits and permissible excursion duration, with effective dates (2 versions per product).

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `policy_id` | id | yes | `POL-\d{6}` |  | PK |  |
| `product_id` | id | yes | `PRD-\d{4}` |  | FK > product.product_id |  |
| `version` | int | yes |  |  |  | 1 or 2; v2 is stricter (shorter permissible duration) |
| `temp_min_c` | real | yes |  | degC |  | < temp_max_c |
| `temp_max_c` | real | yes |  | degC |  |  |
| `rh_min_pct` | real | yes |  | %RH |  | < rh_max_pct |
| `rh_max_pct` | real | yes |  | %RH |  |  |
| `max_excursion_minutes` | int | yes |  | min |  | multiple of 5; permissible out-of-range duration |
| `critical_margin_temp_c` | real | yes |  | degC |  | deviation beyond limit that makes an excursion CRITICAL |
| `critical_margin_rh_pct` | real | yes |  | %RH |  | same, for humidity |
| `effective_from` | date | yes | `\d{4}-\d{2}-\d{2}` |  |  |  |
| `effective_to` | date | no | `\d{4}-\d{2}-\d{2}` |  |  | NULL = open-ended; windows of a product never overlap |

## Container (`container`)

Reefer container or insulated shipper.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `container_id` | id | yes | `CNT-\d{6}` |  | PK |  |
| `container_type` | text | yes | REEFER_40FT, REEFER_20FT, INSULATED_SHIPPER |  |  |  |
| `status` | text | yes | ACTIVE |  |  |  |

## Sensor (`sensor`)

Combined temperature/humidity logger, one per container (1:1).

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `sensor_id` | id | yes | `SNS-CNT-\d{6}-TEMP` |  | PK | SNS-CNT-<container number>-TEMP |
| `container_id` | id | yes | `CNT-\d{6}` |  | unique, FK > container.container_id |  |
| `calibration_date` | date | yes | `\d{4}-\d{2}-\d{2}` |  |  |  |
| `calibration_due` | date | yes | `\d{4}-\d{2}-\d{2}` |  |  | > calibration_date; shipments departing after this date are LOW_TRUST |
| `valid_temp_min_c` | real | yes |  | degC |  | physical range of the probe |
| `valid_temp_max_c` | real | yes |  | degC |  |  |
| `valid_rh_min_pct` | real | yes |  | %RH |  |  |
| `valid_rh_max_pct` | real | yes |  | %RH |  |  |

## Shipment (`shipment`)

A product moving in one container from origin to destination.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `shipment_id` | id | yes | `SHP-2026-\d{6}` |  | PK |  |
| `product_id` | id | yes | `PRD-\d{4}` |  | FK > product.product_id |  |
| `container_id` | id | yes | `CNT-\d{6}` |  | FK > container.container_id | no two shipments of a container overlap in time |
| `policy_id` | id | yes | `POL-\d{6}` |  | FK > threshold_policy.policy_id | policy.product_id = shipment.product_id and effective on planned_departure date |
| `origin` | text | yes |  |  |  |  |
| `destination` | text | yes |  |  |  |  |
| `planned_departure` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | < planned_arrival |
| `planned_arrival` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  |  |
| `actual_departure` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | < actual_arrival |
| `actual_arrival` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | trip length 2-5 days |
| `status` | text | yes | DELIVERED, RELEASED_AFTER_HOLD, REJECTED |  |  | derived from excursion dispositions |

## RouteStop (`route_stop`)

Ordered stops of a shipment (origin, 1-3 transit hubs, destination).

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `route_stop_id` | id | yes | `RST-SHP-2026-\d{6}-\d{2}` |  | PK |  |
| `shipment_id` | id | yes | `SHP-2026-\d{6}` |  | FK > shipment.shipment_id |  |
| `sequence` | int | yes |  |  |  | 1..n contiguous per shipment |
| `stop_type` | text | yes | ORIGIN, TRANSIT_HUB, DESTINATION |  |  |  |
| `location` | text | yes |  |  |  |  |
| `planned_arrival` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  |  |
| `planned_departure` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  |  |
| `actual_arrival` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  |  |
| `actual_departure` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  |  |
| `delay_minutes` | int | yes |  | min |  | = actual_arrival - planned_arrival |

## SensorReading (`sensor_reading`)

One temperature/humidity reading every 5 minutes.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `reading_id` | id | yes | `RDG-SNS-CNT-\d{6}-TEMP-\d{8}T\d{6}Z` |  | PK | RDG-<sensor_id>-<UTC timestamp yyyymmddThhmmssZ> |
| `sensor_id` | id | yes | `SNS-CNT-\d{6}-TEMP` |  | FK > sensor.sensor_id |  |
| `shipment_id` | id | yes | `SHP-2026-\d{6}` |  | FK > shipment.shipment_id |  |
| `route_stop_id` | id | no | `RST-SHP-2026-\d{6}-\d{2}` |  | FK > route_stop.route_stop_id | set while the container is at that stop, else NULL |
| `timestamp` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | exact 5-minute cadence; gaps are listed in data_gap |
| `temperature_c` | real | yes |  | degC |  | outside sensor valid range => SENSOR_FAULT |
| `humidity_pct` | real | yes |  | %RH |  |  |
| `quality_flag` | text | yes | GOOD, LOW_TRUST, SENSOR_FAULT |  |  | SENSOR_FAULT: outside physical range; LOW_TRUST: stuck-at run or expired calibration; else GOOD |

## DataGap (`data_gap`)

Missing-reading interval. Always flagged UNVERIFIED; a gap is never treated as in-range.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `gap_id` | id | yes | `GAP-2026-\d{6}` |  | PK |  |
| `shipment_id` | id | yes | `SHP-2026-\d{6}` |  | FK > shipment.shipment_id |  |
| `sensor_id` | id | yes | `SNS-CNT-\d{6}-TEMP` |  | FK > sensor.sensor_id |  |
| `last_reading_ts` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | last reading before the gap |
| `next_reading_ts` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | first reading after the gap |
| `missing_readings` | int | yes |  |  |  | = (next - last) / 5 min - 1 |
| `status` | text | yes | UNVERIFIED |  |  |  |

## Excursion (`excursion`)

Maximal run of consecutive readings outside the policy range, derived from readings.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `excursion_id` | id | yes | `EXC-2026-\d{6}` |  | PK |  |
| `shipment_id` | id | yes | `SHP-2026-\d{6}` |  | FK > shipment.shipment_id |  |
| `sensor_id` | id | yes | `SNS-CNT-\d{6}-TEMP` |  | FK > sensor.sensor_id |  |
| `policy_id` | id | yes | `POL-\d{6}` |  | FK > threshold_policy.policy_id | policy effective for the shipment |
| `metric` | text | yes | TEMPERATURE, HUMIDITY |  |  |  |
| `direction` | text | yes | HIGH, LOW |  |  |  |
| `start_ts` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | first out-of-range reading |
| `end_ts` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | last out-of-range reading |
| `duration_minutes` | int | yes |  | min |  | = (end_ts - start_ts) + 5 min |
| `peak_value` | real | yes |  | degC or %RH |  | max (HIGH) / min (LOW) in the run |
| `peak_deviation` | real | yes |  | degC or %RH |  | |peak_value - violated limit| |
| `severity` | text | yes | BRIEF, PROLONGED, CRITICAL |  |  | see rules.classify |
| `evidence_quality` | text | yes | VERIFIED, LOW_TRUST |  |  | LOW_TRUST if any reading in the run is LOW_TRUST |
| `probable_cause` | text | yes | ROUTE_DELAY, UNKNOWN_IN_TRANSIT |  |  | ROUTE_DELAY if it starts inside a leg delayed >= 120 min |
| `detected_at` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | = end_ts + 5 min |
| `status` | text | yes | OPEN, ACKNOWLEDGED, UNDER_REVIEW, RELEASED, REJECTED, CLOSED_NO_ACTION |  |  | latest status in excursion_status_history |

## ExcursionStatusHistory (`excursion_status_history`)

Append-only status log: state changes are rows, history is never overwritten.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `history_id` | id | yes | `ESH-2026-\d{6}` |  | PK |  |
| `excursion_id` | id | yes | `EXC-2026-\d{6}` |  | FK > excursion.excursion_id |  |
| `sequence` | int | yes |  |  |  | 1..n contiguous per excursion |
| `status` | text | yes | OPEN, ACKNOWLEDGED, UNDER_REVIEW, RELEASED, REJECTED, CLOSED_NO_ACTION |  |  | only OPEN>ACKNOWLEDGED>UNDER_REVIEW>RELEASED|REJECTED or >CLOSED_NO_ACTION |
| `changed_at` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | non-decreasing within an excursion |
| `actor_role` | text | yes | PLANT_OPERATOR, QUALITY_ENGINEER, MAINTENANCE_ENGINEER, PRODUCTION_PLANNER, OT_IT_ADMIN, SYSTEM |  |  |  |

## Notification (`notification`)

Alert sent to a role when something needs attention.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `notification_id` | id | yes | `NTF-2026-\d{6}` |  | PK |  |
| `trigger_type` | text | yes | EXCURSION, DATA_GAP, CALIBRATION, ROUTE_DELAY |  |  |  |
| `trigger_id` | id | yes |  |  |  | excursion_id | gap_id | shipment_id (CALIBRATION) | route_stop_id (ROUTE_DELAY) |
| `shipment_id` | id | yes | `SHP-2026-\d{6}` |  | FK > shipment.shipment_id |  |
| `recipient_role` | text | yes | PLANT_OPERATOR, QUALITY_ENGINEER, MAINTENANCE_ENGINEER, PRODUCTION_PLANNER, OT_IT_ADMIN |  |  |  |
| `priority` | text | yes | INFO, WARNING, CRITICAL |  |  |  |
| `channel` | text | yes | DASHBOARD, EMAIL, SMS |  |  |  |
| `sent_at` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  |  |

## CustodyEvent (`custody_event`)

Chain-of-custody log per shipment.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `custody_id` | id | yes | `CUS-2026-\d{6}` |  | PK |  |
| `shipment_id` | id | yes | `SHP-2026-\d{6}` |  | FK > shipment.shipment_id |  |
| `sequence` | int | yes |  |  |  | 1..n contiguous; timestamps non-decreasing |
| `event_type` | text | yes | PICKUP, STOP_ARRIVAL, STOP_DEPARTURE, QUALITY_HOLD, DELIVERY, RELEASE, REJECT |  |  |  |
| `event_ts` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  |  |
| `from_party` | text | yes |  |  |  |  |
| `to_party` | text | yes |  |  |  |  |

## CorrectiveAction (`corrective_action`)

Task assigned to a role in response to a trigger.

| Field | Type | Req. | Allowed values / format | Unit | Unique / FK | Validation rule |
|---|---|---|---|---|---|---|
| `action_id` | id | yes | `CA-2026-\d{6}` |  | PK |  |
| `trigger_type` | text | yes | EXCURSION, DATA_GAP, CALIBRATION, ROUTE_DELAY |  |  |  |
| `trigger_id` | id | yes |  |  |  |  |
| `shipment_id` | id | yes | `SHP-2026-\d{6}` |  | FK > shipment.shipment_id |  |
| `action_type` | text | yes | LOG_AND_MONITOR, QUALITY_HOLD_REVIEW, QUARANTINE_AND_DISPOSITION, REPLAN_REPLACEMENT_SHIPMENT, INSPECT_REEFER_UNIT, INVESTIGATE_SENSOR_DROPOUT, RECALIBRATE_SENSOR, REPLAN_DELIVERY |  |  |  |
| `assigned_role` | text | yes | PLANT_OPERATOR, QUALITY_ENGINEER, MAINTENANCE_ENGINEER, PRODUCTION_PLANNER, OT_IT_ADMIN |  |  |  |
| `created_at` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  |  |
| `due_at` | ts | yes | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | > created_at |
| `completed_at` | ts | no | `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` |  |  | NULL iff outcome = OPEN; >= created_at |
| `outcome` | text | yes | COMPLETED, OPEN |  |  |  |
