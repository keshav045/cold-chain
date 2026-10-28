PRAGMA foreign_keys = ON;

CREATE TABLE product (
  product_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL CHECK (category IN ('VACCINE', 'PHARMA_COLD', 'FROZEN_FOOD', 'CHILLED_FOOD', 'PRODUCE', 'FROZEN_PHARMA')),
  target_temp_c REAL NOT NULL,
  target_rh_pct REAL NOT NULL
);

CREATE TABLE threshold_policy (
  policy_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  temp_min_c REAL NOT NULL,
  temp_max_c REAL NOT NULL,
  rh_min_pct REAL NOT NULL,
  rh_max_pct REAL NOT NULL,
  max_excursion_minutes INTEGER NOT NULL,
  critical_margin_temp_c REAL NOT NULL,
  critical_margin_rh_pct REAL NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  FOREIGN KEY (product_id) REFERENCES product(product_id)
);

CREATE TABLE container (
  container_id TEXT PRIMARY KEY,
  container_type TEXT NOT NULL CHECK (container_type IN ('REEFER_40FT', 'REEFER_20FT', 'INSULATED_SHIPPER')),
  status TEXT NOT NULL CHECK (status IN ('ACTIVE'))
);

CREATE TABLE sensor (
  sensor_id TEXT PRIMARY KEY,
  container_id TEXT NOT NULL UNIQUE,
  calibration_date TEXT NOT NULL,
  calibration_due TEXT NOT NULL,
  valid_temp_min_c REAL NOT NULL,
  valid_temp_max_c REAL NOT NULL,
  valid_rh_min_pct REAL NOT NULL,
  valid_rh_max_pct REAL NOT NULL,
  FOREIGN KEY (container_id) REFERENCES container(container_id)
);

CREATE TABLE shipment (
  shipment_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  container_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  origin TEXT NOT NULL,
  destination TEXT NOT NULL,
  planned_departure TEXT NOT NULL,
  planned_arrival TEXT NOT NULL,
  actual_departure TEXT NOT NULL,
  actual_arrival TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('DELIVERED', 'RELEASED_AFTER_HOLD', 'REJECTED')),
  FOREIGN KEY (product_id) REFERENCES product(product_id),
  FOREIGN KEY (container_id) REFERENCES container(container_id),
  FOREIGN KEY (policy_id) REFERENCES threshold_policy(policy_id)
);

CREATE TABLE route_stop (
  route_stop_id TEXT PRIMARY KEY,
  shipment_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  stop_type TEXT NOT NULL CHECK (stop_type IN ('ORIGIN', 'TRANSIT_HUB', 'DESTINATION')),
  location TEXT NOT NULL,
  planned_arrival TEXT NOT NULL,
  planned_departure TEXT NOT NULL,
  actual_arrival TEXT NOT NULL,
  actual_departure TEXT NOT NULL,
  delay_minutes INTEGER NOT NULL,
  FOREIGN KEY (shipment_id) REFERENCES shipment(shipment_id)
);

CREATE TABLE sensor_reading (
  reading_id TEXT PRIMARY KEY,
  sensor_id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  route_stop_id TEXT,
  timestamp TEXT NOT NULL,
  temperature_c REAL NOT NULL,
  humidity_pct REAL NOT NULL,
  quality_flag TEXT NOT NULL CHECK (quality_flag IN ('GOOD', 'LOW_TRUST', 'SENSOR_FAULT')),
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id),
  FOREIGN KEY (shipment_id) REFERENCES shipment(shipment_id),
  FOREIGN KEY (route_stop_id) REFERENCES route_stop(route_stop_id)
);

CREATE TABLE data_gap (
  gap_id TEXT PRIMARY KEY,
  shipment_id TEXT NOT NULL,
  sensor_id TEXT NOT NULL,
  last_reading_ts TEXT NOT NULL,
  next_reading_ts TEXT NOT NULL,
  missing_readings INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('UNVERIFIED')),
  FOREIGN KEY (shipment_id) REFERENCES shipment(shipment_id),
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id)
);

CREATE TABLE excursion (
  excursion_id TEXT PRIMARY KEY,
  shipment_id TEXT NOT NULL,
  sensor_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  metric TEXT NOT NULL CHECK (metric IN ('TEMPERATURE', 'HUMIDITY')),
  direction TEXT NOT NULL CHECK (direction IN ('HIGH', 'LOW')),
  start_ts TEXT NOT NULL,
  end_ts TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL,
  peak_value REAL NOT NULL,
  peak_deviation REAL NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('BRIEF', 'PROLONGED', 'CRITICAL')),
  evidence_quality TEXT NOT NULL CHECK (evidence_quality IN ('VERIFIED', 'LOW_TRUST')),
  probable_cause TEXT NOT NULL CHECK (probable_cause IN ('ROUTE_DELAY', 'UNKNOWN_IN_TRANSIT')),
  detected_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'UNDER_REVIEW', 'RELEASED', 'REJECTED', 'CLOSED_NO_ACTION')),
  FOREIGN KEY (shipment_id) REFERENCES shipment(shipment_id),
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id),
  FOREIGN KEY (policy_id) REFERENCES threshold_policy(policy_id)
);

CREATE TABLE excursion_status_history (
  history_id TEXT PRIMARY KEY,
  excursion_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'UNDER_REVIEW', 'RELEASED', 'REJECTED', 'CLOSED_NO_ACTION')),
  changed_at TEXT NOT NULL,
  actor_role TEXT NOT NULL CHECK (actor_role IN ('PLANT_OPERATOR', 'QUALITY_ENGINEER', 'MAINTENANCE_ENGINEER', 'PRODUCTION_PLANNER', 'OT_IT_ADMIN', 'SYSTEM')),
  FOREIGN KEY (excursion_id) REFERENCES excursion(excursion_id)
);

CREATE TABLE notification (
  notification_id TEXT PRIMARY KEY,
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('EXCURSION', 'DATA_GAP', 'CALIBRATION', 'ROUTE_DELAY')),
  trigger_id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  recipient_role TEXT NOT NULL CHECK (recipient_role IN ('PLANT_OPERATOR', 'QUALITY_ENGINEER', 'MAINTENANCE_ENGINEER', 'PRODUCTION_PLANNER', 'OT_IT_ADMIN')),
  priority TEXT NOT NULL CHECK (priority IN ('INFO', 'WARNING', 'CRITICAL')),
  channel TEXT NOT NULL CHECK (channel IN ('DASHBOARD', 'EMAIL', 'SMS')),
  sent_at TEXT NOT NULL,
  FOREIGN KEY (shipment_id) REFERENCES shipment(shipment_id)
);

CREATE TABLE custody_event (
  custody_id TEXT PRIMARY KEY,
  shipment_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('PICKUP', 'STOP_ARRIVAL', 'STOP_DEPARTURE', 'QUALITY_HOLD', 'DELIVERY', 'RELEASE', 'REJECT')),
  event_ts TEXT NOT NULL,
  from_party TEXT NOT NULL,
  to_party TEXT NOT NULL,
  FOREIGN KEY (shipment_id) REFERENCES shipment(shipment_id)
);

CREATE TABLE corrective_action (
  action_id TEXT PRIMARY KEY,
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('EXCURSION', 'DATA_GAP', 'CALIBRATION', 'ROUTE_DELAY')),
  trigger_id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  action_type TEXT NOT NULL CHECK (action_type IN ('LOG_AND_MONITOR', 'QUALITY_HOLD_REVIEW', 'QUARANTINE_AND_DISPOSITION', 'REPLAN_REPLACEMENT_SHIPMENT', 'INSPECT_REEFER_UNIT', 'INVESTIGATE_SENSOR_DROPOUT', 'RECALIBRATE_SENSOR', 'REPLAN_DELIVERY')),
  assigned_role TEXT NOT NULL CHECK (assigned_role IN ('PLANT_OPERATOR', 'QUALITY_ENGINEER', 'MAINTENANCE_ENGINEER', 'PRODUCTION_PLANNER', 'OT_IT_ADMIN')),
  created_at TEXT NOT NULL,
  due_at TEXT NOT NULL,
  completed_at TEXT,
  outcome TEXT NOT NULL CHECK (outcome IN ('COMPLETED', 'OPEN')),
  FOREIGN KEY (shipment_id) REFERENCES shipment(shipment_id)
);

CREATE INDEX idx_reading_shipment_ts ON sensor_reading (shipment_id, timestamp);
CREATE INDEX idx_excursion_shipment ON excursion (shipment_id);
