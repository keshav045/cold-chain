# Validation summary

**Overall: PASS** (hard-invariant failures: 0)

## 1. Hard invariants

| Check | Result | Failures | What it verifies |
|---|---|---|---|
| `schema.columns` | pass | 0 | every table has exactly the documented columns |
| `schema.required` | pass | 0 | required fields are never null |
| `schema.types` | pass | 0 | int/real fields parse as numbers |
| `schema.format` | pass | 0 | ID, timestamp and date fields match their regex (zero-padded, immutable formats) |
| `schema.enums` | pass | 0 | enumerated fields only hold allowed values |
| `schema.pk_unique` | pass | 0 | primary keys are unique |
| `schema.unique` | pass | 0 | unique fields (sensor.container_id, product.name) are unique |
| `schema.fk` | pass | 0 | every foreign key resolves to an existing parent row |
| `schema.no_leakage` | pass | 0 | no input table contains ground-truth / scenario / issue columns |
| `policy.sane` | pass | 0 | policy ranges ordered, durations multiple of 5, effective windows do not overlap |
| `sensor.calibration_dates` | pass | 0 | calibration_due is after calibration_date |
| `route.stops` | pass | 0 | 3-5 stops, contiguous sequence, ORIGIN first, DESTINATION last, hubs between |
| `route.times` | pass | 0 | stop times monotonic; delay_minutes = actual_arrival - planned_arrival |
| `shipment.planned_order` | pass | 0 | planned_departure < planned_arrival |
| `shipment.matches_route` | pass | 0 | shipment actual times equal first departure / last arrival of its route |
| `shipment.trip_length` | pass | 0 | trip length is 2-5 days |
| `shipment.container_no_overlap` | pass | 0 | a container is never used by two shipments at the same time |
| `shipment.status` | pass | 0 | shipment status equals the worst excursion disposition |
| `reading.shipment_known` | pass | 0 | every shipment has readings; every reading belongs to a shipment |
| `reading.sensor_matches` | pass | 0 | reading sensor = the sensor of the shipment's container |
| `reading.cadence` | pass | 0 | exact 5-minute cadence between consecutive readings (no duplicates, no overlap) |
| `reading.covers_trip` | pass | 0 | readings start at departure and end at arrival |
| `reading.id_format` | pass | 0 | reading_id = RDG-<sensor_id>-<timestamp> |
| `reading.route_stop` | pass | 0 | route_stop_id equals the stop the container is at (or NULL) |
| `reading.quality_flag` | pass | 0 | stored quality_flag equals the re-derived flag |
| `reading.no_duplicates` | pass | 0 | no two readings share the same (sensor_id, timestamp) |
| `reconcile.reading_counts` | pass | 0 | arithmetic reconciliation: readings present + missing_readings listed in data_gap = expected 5-minute slots of the trip |
| `gap.flagged` | pass | 0 | every missing interval is listed in data_gap (never silently treated as safe) |
| `gap.table_matches_readings` | pass | 0 | every data_gap row corresponds to a real missing interval |
| `excursion.recomputed` | pass | 0 | excursions in the table equal the excursions recomputed from readings |
| `excursion.values` | pass | 0 | end, peak, severity, evidence, cause, policy of each excursion equal the recomputed values |
| `excursion.duration` | pass | 0 | stored duration is not larger than / different from recomputed (shorter = DURATION_UNDERCOUNTED) |
| `workflow.notifications` | pass | 0 | notifications per trigger equal the documented routing rules |
| `workflow.actions` | pass | 0 | corrective actions per trigger equal the documented rules; dates consistent |
| `workflow.status_history` | pass | 0 | status history is append-only, contiguous, uses allowed transitions, ends at the excursion status |
| `workflow.custody` | pass | 0 | custody events are ordered, complete, consistent with route and dispositions |
| `format.consistency` | pass | 0 | CSV, JSON/JSONL and SQLite exports hold the same rows (row counts and primary-key sets) |
| `sqlite.foreign_key_check` | pass | 0 | PRAGMA foreign_key_check on coldchain.db |

## 2. Expected anomalies vs ground truth

Overall precision **1.0**, recall **1.0** (TP 45, FP 0, FN 0).

| Issue type | Expected | Detected | Precision | Recall |
|---|---|---|---|---|
| `OUT_OF_PHYSICAL_RANGE` | 5 | 5 | 1.0 | 1.0 |
| `SENSOR_DROPOUT_GAP` | 8 | 8 | 1.0 | 1.0 |
| `DELIVERY_BEFORE_DEPARTURE` | 1 | 1 | 1.0 | 1.0 |
| `WRONG_POLICY` | 1 | 1 | 1.0 | 1.0 |
| `DURATION_UNDERCOUNTED` | 1 | 1 | 1.0 | 1.0 |
| `CALIBRATION_FAILURE` | 6 | 6 | 1.0 | 1.0 |
| `ROUTE_DELAY` | 4 | 4 | 1.0 | 1.0 |
| `EXCURSION_BRIEF` | 11 | 11 | 1.0 | 1.0 |
| `EXCURSION_PROLONGED` | 6 | 6 | 1.0 | 1.0 |
| `EXCURSION_CRITICAL` | 2 | 2 | 1.0 | 1.0 |

## 3. Distributions and coverage

- Shipments: 50 on 15 containers (3.33 per container); trip length 2.02-4.96 days (mean 3.55).
- Row counts: product=8, threshold_policy=16, container=15, sensor=15, shipment=50, route_stop=188, sensor_reading=50,959, data_gap=8, excursion=19, excursion_status_history=65, notification=53, custody_event=292, corrective_action=45
- Reading coverage: 99.683% of expected 5-minute slots present; 8 dropout gaps (162 missing readings), all flagged UNVERIFIED.
- Quality flags: {'GOOD': 45820, 'LOW_TRUST': 5134, 'SENSOR_FAULT': 5}
- Excursions: 19 - by severity {'BRIEF': 11, 'PROLONGED': 6, 'CRITICAL': 2}, by metric {'TEMPERATURE': 16, 'HUMIDITY': 3}, by cause {'UNKNOWN_IN_TRANSIT': 17, 'ROUTE_DELAY': 2}.
- Excursion duration percentiles (min): {'p10': 14.0, 'p50': 55.0, 'p90': 200.0, 'p99': 331.20000000000005}
- Shipment outcomes: {'DELIVERED': 42, 'REJECTED': 5, 'RELEASED_AFTER_HOLD': 3}

| Product | Shipments | With excursion | Rate |
|---|---|---|---|
| Seasonal Flu Vaccine | 3 | 1 | 0.333 |
| Insulin Pens | 4 | 0 | 0.0 |
| Frozen Seafood | 4 | 1 | 0.25 |
| Ice Cream | 8 | 2 | 0.25 |
| Fresh Dairy | 7 | 3 | 0.429 |
| Leafy Greens | 5 | 2 | 0.4 |
| Fresh Berries | 9 | 3 | 0.333 |
| Frozen Plasma | 10 | 4 | 0.4 |
