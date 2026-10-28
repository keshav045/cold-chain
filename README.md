# Cold Chain Telemetry & Excursion Synth

A reproducible synthetic telemetry generator and validation engine for cold-chain logistics (temperature and humidity monitoring during storage and transit).

This project simulates refrigerated shipments, models multi-actor operational workflows (plant operators, quality managers, maintenance, planners), deliberately injects real-world anomalies and failure modes, and includes an automated validator that verifies data integrity and catches 100% of injected defects without leaking ground truth into input data.

---

## Highlights

- **Scale**: Generates up to 1,000 shipments, 300 refrigerated containers, and ~1,000,000 5-minute telemetry readings across 13 relational entities.
- **Strict Determinism**: Uses a fixed seed (`20261022`) and isolated RNG streams (`numpy.random.SeedSequence.spawn`). Same seed always produces byte-identical uncompressed data across platforms.
- **Zero External Dependencies**: Runs entirely offline using standard Python 3.10+, `numpy`, `pandas`, and built-in `sqlite3`. No external APIs, cloud services, or credentials needed.
- **Multi-Format Export**: Writes data as CSV, JSON, and SQLite database (`coldchain.db` / compressed `seed.sql.gz`).
- **Complete Invariant Validator**: Re-derives derived values and checks PK/FK constraints, enum validity, date sequencing, arithmetic consistency, container non-overlap, and achieves **Precision = 1.0, Recall = 1.0** against ground truth.

---

## Quick Start

### 1. Installation

Clone the repository and install in editable mode:

```bash
git clone https://github.com/keshav045/cold-chain.git
cd cold-chain
pip install -e .
```

*Requirements: Python 3.10+, numpy>=1.26, pandas>=2.1, pytest>=8.0.*

---

### 2. Verify Key Behavior in Under 2 Minutes

Run the test suite and quick validation commands:

```bash
# 1. Run the test suite (38 unit, property, and mutation tests)
pytest

# 2. Generate and validate a quick starter dataset (50 shipments, ~10 seconds)
coldchain generate --scale starter --out data/starter

# 3. Validate the pre-generated full dataset (1,000 shipments, ~1M readings)
coldchain validate --data data/full --write

# 4. Prove determinism (generates twice, compares row counts & SHA-256 hashes)
coldchain reproduce --scale starter
```

> **For macOS / Linux users**: A `Makefile` is included (`make test`, `make generate-starter`, `make validate`, `make reproduce`).

---

## How It Works: The 10-Step Pipeline

The generator strictly follows a 10-step hierarchical generation process:

1. **Schema & Data Dictionary**: Defines 13 entities with strict data types, units, and regex-validated primary/foreign keys (`docs/data_dictionary.md`).
2. **Master Data First**: Generates parent master entities (`product`, `threshold_policy`, `container`, `sensor`) before any child records.
3. **Deterministic Nomenclature**:
   - Shipments: `SHP-2026-000001`
   - Containers: `CNT-000001`
   - Sensors: `SNS-CNT-000001-TEMP`
   - Readings: `RDG-<sensor_id>-<timestamp>`
   - Excursions: `EXC-2026-000001`
4. **Baseline Volume & Trips**: Simulates 2–5 day trips with readings on an exact 5-minute grid. Reefer containers are reused sequentially with a mandatory 12-hour turnaround window.
5. **Edge Case Injection**: Injects the 5 mandatory anomalies and operational defects on baseline records.
6. **Recomputed Derived Values**: Excursion durations, severity levels, custody milestones, and corrective actions are calculated directly from telemetry—never assigned randomly.
7. **Decoupled Ground Truth**: Injected defects and expected actions are written to separate `ground_truth.csv` and `ground_truth.json` files. No ground-truth label ever leaks into input tables.
8. **Automated Validation**: Re-runs the full detection engine against the generated tables and asserts zero invariant violations and perfect defect detection.
9. **Multi-Format Export**: Exports CSV, JSON, SQLite DDL (`schema.sql`), compressed database dumps (`seed.sql.gz`), source manifest, and checksums.
10. **Reproducibility**: Runs independent generations from the same seed and compares uncompressed SHA-256 checksums to prove consistency.

---

## The 5 Mandatory Edge Cases

The project specifically models and validates the five core defect scenarios required by the brief:

| # | Edge Case | How It Is Injected | How the Validator Catches It | Expected Disposition |
|---|---|---|---|---|
| **1** | **Physical Range Violation** | Telemetry spikes set to impossible values (-127 °C or 150 °C). | Flagged by `reading.physical_range` check. | Marked `SENSOR_FAULT`; excluded from excursion logic. |
| **2** | **Missing Interval Interpreted as Safe** | Random telemetry dropouts (15 min to several hours) in ~8% of trips. | Step detector finds intervals > 5 min; recorded in `data_gap`. | Flagged as `UNVERIFIED`; never treated as safe. |
| **3** | **Shipment Delivered Before Departure** | Timestamps corrupted so `actual_arrival < actual_departure`. | Date-ordering validation check on shipments. | Record rejected due to invalid lifecycle order. |
| **4** | **Threshold Applied to Wrong Product** | Policy assigned to a product it does not govern. | Joined threshold policy checked against `shipment.product_id`. | Record rejected due to policy mismatch. |
| **5** | **Excursion Duration Undercounted** | Stored excursion duration shortened by 15–50% vs raw readings. | Arithmetic reconciliation recomputes duration from readings: `(last - first) + 5 min`. | Stored duration overwritten with true recomputed duration. |

*Additional realistic scenarios included: sensor calibration expirations, stuck flat-line sensors, and route delays.*

---

## Data Model & Relational Architecture

The system models 13 relational tables organized into three tiers:

```
[ Master Tables ]
  ├── product (8 categories: vaccines, biologics, chilled, frozen)
  ├── threshold_policy (v1 and stricter v2 policies with effective dates)
  ├── container (reefer units & insulated shippers)
  └── sensor (calibrated temp/humidity loggers, 1:1 with containers)

[ Transaction Tables ]
  ├── shipment (connects container, product, policy, route, & status)
  ├── route_stop (planned vs actual transit stops, dwell times, and delays)
  └── sensor_reading (5-minute telemetry: temp, humidity, battery, quality flag)

[ Operational & Event Tables ]
  ├── data_gap (flagged unmonitored intervals)
  ├── excursion (out-of-threshold runs: BRIEF, PROLONGED, CRITICAL)
  ├── excursion_status_history (audit log of review decisions)
  ├── notification (routed alerts to operators, engineers, admins)
  ├── custody_event (pickup, departure, hold, release, reject milestones)
  └── corrective_action (quarantine, inspection, replanning actions)
```

- **Data Dictionary**: See [`docs/data_dictionary.md`](docs/data_dictionary.md) for full field definitions, types, constraints, and validation rules.
- **Entity Relationship Diagram (ERD)**: See [`docs/erd.md`](docs/erd.md) for Mermaid ERD and cardinality details.

---

## Multi-Actor Operational Workflow

Telemetry events trigger specific, auditable operational workflows based on severity:

- **Plant Operator**: Acknowledges initial alarms, logs minor excursions within tolerance (`BRIEF`).
- **Quality Engineer**: Places shipments on hold upon `PROLONGED` or `CRITICAL` excursions, reviews thermal history, and makes final release or disposal decisions (`RELEASE` vs `REJECT`).
- **Maintenance Engineer**: Dispatched to inspect cooling units when temperature deviations occur without corresponding route delays.
- **Production Planner**: Automatically notified on critical shipment rejections to arrange immediate replacement shipments.
- **IT / OT Administrator**: Receives alerts for prolonged telemetry dropouts (gaps >= 30 min) and sensors overdue for calibration.

---

## Validation & Test Results

### Validation Performance (`data/full` with 1,000 shipments & 999,663 readings)

```
============================================================
COLD-CHAIN VALIDATION SUMMARY
============================================================
Hard Invariant Checks : PASS (0 failures)
Precision             : 1.0000 (100% of flagged issues were real)
Recall                : 1.0000 (100% of injected defects found)
Ground Truth Matches  : 828 / 828 anomalies detected
============================================================
```

### Automated Test Suite (`pytest`)

The project includes **38 automated tests** covering:
- Unit tests for duration math, boundary inclusivity, and timestamp parsing.
- Determinism tests verifying identical RNG sequences for matching seeds.
- Foreign key integrity and container non-overlap scheduling rules.
- **Mutation tests**: Deliberately corrupts data (tampered PK, bad FK, leaked columns, altered gap records) to guarantee the validator catches failures.

---

## Exploring the Data (SQL Examples)

You can inspect the generated SQLite database directly using `sqlite3`:

```bash
sqlite3 data/starter/coldchain.db
```

```sql
-- 1. View the longest temperature excursions and their status
SELECT excursion_id, metric, duration_minutes, severity, status
FROM excursion
ORDER BY duration_minutes DESC
LIMIT 5;

-- 2. Inspect flagged telemetry gaps (missing intervals)
SELECT gap_id, shipment_id, missing_readings, status
FROM data_gap
ORDER BY missing_readings DESC
LIMIT 5;

-- 3. Trace the chronological audit trail for a rejected shipment
SELECT sequence, event_type, event_ts, actor_role, notes
FROM custody_event
WHERE shipment_id = (SELECT shipment_id FROM shipment WHERE status = 'REJECTED' LIMIT 1)
ORDER BY sequence;
```

---

## Repository Structure

```
cold-chain/
├── src/coldchain/          # Core package
│   ├── schema.py           # 13 entities, DDL generator, dictionary & ERD generator
│   ├── config.py           # Simulation volumes, default seed (20261022), defect rates
│   ├── master_data.py      # Products, policies (v1/v2), containers, sensors
│   ├── scheduling.py       # Non-overlapping container schedules & route generation
│   ├── readings.py         # 5-minute physics-inspired telemetry generator
│   ├── detection.py        # Core excursion, gap, and fault detection algorithms
│   ├── rules.py            # Business logic, severity formulas, and workflow transitions
│   ├── workflow.py         # Notifications, custody logs, actions, status history
│   ├── generate.py         # 10-step orchestrator & ground-truth builder
│   ├── export.py           # Multi-format export (CSV, JSON, SQLite, Gzip, Checksums)
│   ├── validate.py         # Hard invariant checker & Precision/Recall evaluator
│   └── cli.py              # CLI entry point (generate, validate, reproduce, docs)
├── tests/                  # 38 unit, property, and mutation tests
├── docs/                   # Full system documentation, data dictionary, and ERD
│   ├── PROJECT_EXPLANATION.md
│   ├── data_dictionary.md
│   └── erd.md
├── ai_usage/               # AI disclosure and prompt logs (Company Guideline 03)
│   └── PROMPT_HISTORY.md
├── data/
│   ├── starter/            # 50 shipments (committed with coldchain.db)
│   └── full/               # 1,000 shipments (committed CSV/JSON/SQL; 240MB db generated locally)
├── .github/workflows/      # GitHub Actions CI workflow
├── Makefile                # Convenient build and test commands
├── pyproject.toml          # Build configuration and CLI script mapping
├── requirements.txt        # Minimal dependencies (numpy, pandas, pytest)
└── README.md
```

---

## Key Decisions & Trade-Offs

1. **One Sensor per Container**: The specification assigns one combined temperature/humidity sensor per container (`SNS-CNT-000001-TEMP`). Multi-sensor redundancy was excluded to stay aligned with the brief's nomenclature.
2. **Flagging Gaps vs Filling Them**: The prompt explicitly specifies that missing intervals must never be assumed safe. The engine flags gaps in `data_gap` as `UNVERIFIED` and never bridges excursions across missing data.
3. **Decoupled Ground Truth**: No input table includes defect labels or cheat flags. The validator recomputes everything from raw telemetry and matches its findings against the separate `ground_truth.csv` to ensure an authentic evaluation.
4. **Git Storage Hygiene**: The full SQLite file (`data/full/coldchain.db`) is ~240 MB and exceeds GitHub's 100 MB per-file limit. It is git-ignored and can be regenerated on demand (`coldchain generate --scale full --out data/full`) or loaded instantly from the committed `data/full/seed.sql.gz` dump. The 50-shipment starter database is committed directly for quick review.

---

## Author & Submission Context

- **Author**: Keshav Agarwal
- **Repository**: [https://github.com/keshav045/cold-chain](https://github.com/keshav045/cold-chain)
- **Challenge**: YottaFlex AI Recruitment Drive Candidate Project
- **AI Disclosure**: Completed in accordance with Guideline 03 and FAQ 6 in [`ai_usage/PROMPT_HISTORY.md`](ai_usage/PROMPT_HISTORY.md).
