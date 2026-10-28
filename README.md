# cold-chain-synth

A **reproducible synthetic data generator** for cold-chain monitoring: temperature and humidity readings along
storage and transport journeys, with temperature/humidity **excursions**, sensor problems, notifications,
chain-of-custody and corrective actions, plus a **validator** that proves the data is consistent and that every
deliberately injected defect is found, and only those.

It produces related tables (13 entities) as CSV, JSON and SQL, a **separate ground-truth file**, a data dictionary,
an ERD, a source manifest, checksums and a validation summary. No UI, no external data.

| | |
|---|---|
| Default seed | `20261022` |
| Full volume | 1,000 shipments, 300 containers, a reading every 5 minutes over 2-5 day trips (about 1.0 M readings) |
| Runtime | about 10 s to generate, about 40 s including export and validation |
| Dependencies | Python 3.10+, `numpy`, `pandas` (`pytest` for tests). SQLite is the standard library. |

## 1. Quick start

### Universal (Recommended for all platforms: Windows, macOS, Linux)

```bash
git clone <this repo> && cd cold-chain-synth
pip install -e .

pytest                                              # 38 tests (unit, property and mutation tests)
coldchain generate --scale starter --out data/starter
coldchain generate --scale full --out data/full
coldchain validate --data data/full --write
coldchain reproduce --scale starter
```

### With `make` (macOS / Linux)

```bash
make test               # 38 tests (unit, property and mutation tests)
make generate-starter   # 50 shipments  -> data/starter   (same code path as full)
make generate-full      # 1,000 shipments -> data/full    (writes + validates)
make validate           # re-validate data/full
make reproduce          # generate twice, compare row counts + SHA-256
```

### Direct module execution (PowerShell / Windows)

```powershell
$env:PYTHONPATH="src"
python -m pytest
python -m coldchain generate --scale full --seed 20261022 --out data/full
python -m coldchain validate --data data/full --write
python -m coldchain reproduce --scale starter
```

`generate` exits non-zero if validation fails. `--formats csv,json,sql` selects exports (CSV is always written).
`--shipments N --containers M` override the volume; `--scale starter|full` are presets of the same generator.

### Configuration and requirements

No credentials, services or network access are needed (Python 3.10+, `numpy`, `pandas`; `pytest` for the tests).
Everything tunable (seed, volumes, scenario mix, defect rates) is in [`src/coldchain/config.py`](src/coldchain/config.py)
or on the command line (`--seed`, `--scale`, `--shipments`, `--containers`, `--formats`).

### Verify key behaviour in two minutes

```bash
make test                      # 38 tests, including mutation tests that corrupt data and expect a failure
make generate-starter          # generates, exports and validates 50 shipments (about 10 s)
make validate                  # re-validates the committed full dataset: PASS, precision 1.0, recall 1.0
make reproduce                 # generates twice, compares row counts and SHA-256
```

Then look at the data itself with `sqlite3 data/starter/coldchain.db`:

```sql
-- excursions follow the threshold / duration rules (permissible minutes come from the product's policy)
SELECT e.excursion_id, e.severity, e.duration_minutes, p.max_excursion_minutes AS permissible, e.status
FROM excursion e JOIN threshold_policy p USING (policy_id) ORDER BY e.duration_minutes DESC LIMIT 3;

-- gaps are flagged, never assumed safe
SELECT gap_id, shipment_id, missing_readings, status FROM data_gap ORDER BY missing_readings DESC LIMIT 3;

-- readings link to the correct shipment and route stop
SELECT r.reading_id, r.shipment_id, s.stop_type FROM sensor_reading r JOIN route_stop s USING (route_stop_id) LIMIT 2;

-- the custody timeline is ordered (a rejected shipment: pickup, stops, hold, delivery, reject)
SELECT sequence, event_type, event_ts FROM custody_event
WHERE shipment_id = (SELECT shipment_id FROM shipment WHERE status = 'REJECTED' ORDER BY shipment_id LIMIT 1)
ORDER BY sequence;
```

The known anomalies are only in `data/starter/ground_truth.csv`; no input table contains a label.

## 2. What is in `data/<scale>/`

| File | Content |
|---|---|
| `product`, `threshold_policy`, `container`, `sensor` | master data (`*.csv`, `*.json`) |
| `shipment`, `route_stop` | transactions with planned vs actual times |
| `sensor_reading.csv.gz` / `.jsonl.gz` | the 5-minute readings (gzip, about 1 M rows at full scale) |
| `data_gap`, `excursion`, `excursion_status_history`, `notification`, `custody_event`, `corrective_action` | derived events |
| **`ground_truth.csv/json`** | known anomalies and expected decisions, **never referenced by any input table** |
| `schema.sql`, `seed.sql.gz`, `coldchain.db` | SQL: DDL with PK/FK/CHECK constraints, a full `INSERT` dump, and a ready SQLite database |
| `source_manifest.json`, `checksums.json` | provenance, command, seed, config, per-file row counts and SHA-256 |
| `validation_summary.json/.md` | result of the validation suite |

`data/full/coldchain.db` (240 MB) is git-ignored because it exceeds GitHub's 100 MB limit; run `coldchain generate --scale full --out data/full`
to rebuild it, or load `schema.sql` + `seed.sql.gz`. Everything else is committed (about 39 MB).

Documentation:
- [`docs/PROJECT_EXPLANATION.md`](docs/PROJECT_EXPLANATION.md): Complete system overview, pipeline breakdown, business workflow, and requirement compliance matrix.
- [`docs/data_dictionary.md`](docs/data_dictionary.md): type, required/optional, allowed values, units, uniqueness and validation rule for every field.
- [`docs/erd.md`](docs/erd.md): Mermaid ERD and entity cardinality relationships.
- [`ai_usage/PROMPT_HISTORY.md`](ai_usage/PROMPT_HISTORY.md): AI-use disclosure and the prompt history (company guideline 03 and FAQ 6).

Both the data dictionary and ERD are generated from `src/coldchain/schema.py`, the single source of truth that also drives the SQL DDL and the validator.

## 3. Assumptions and decisions

1. **Fully synthetic.** No external data, so no licensing, attribution or personal-data issues (see `source_manifest.json`).
2. **Determinism.** One seed (`20261022`, the example in the brief) feeds `numpy.random.default_rng` through independent
   child streams (`SeedSequence.spawn`) for master data, scheduling, each shipment's readings, defects and workflow.
   No wall-clock time, `uuid4` or unordered iteration is used. The simulation start is fixed at `2026-01-01T00:00:00Z`.
3. **One combined temperature + humidity sensor per container**, ID `SNS-CNT-000001-TEMP` as in the brief.
4. **Time.** All timestamps are ISO-8601 UTC. Readings sit on an exact 5-minute grid; a trip lasts 2-5 days.
5. **Container reuse.** About 3.4 shipments per container, never overlapping (12 h minimum turnaround).
6. **Two policy versions per product** with effective dates (v1 until 2026-06-30, v2 stricter from 2026-07-01); a
   shipment uses the version effective on its planned departure date.
7. **Notification** and **DataGap** are added as entities: the brief says "create notifications" and requires missing
   intervals to be flagged rather than assumed safe.
8. **Raw vs derived.** Readings are simulated; everything else that the brief calls "derived" (excursions, durations,
   severity, notifications, actions, status history, custody events, shipment outcome) is computed from the readings by
   `detection.py` / `workflow.py` using documented rules, never drawn as an independent random label.

9. **Relationships and cardinality.** Container-Sensor is 1:1; every other relationship is 1:N, some optional (for example
   a shipment may have no excursion, and a reading has a `route_stop_id` only while the container is at a stop).
   The only many-to-many relationship, Product N:M Container (a container carries different products over time and a
   product travels in many containers), is resolved by `shipment`, which is the bridge/association table: it carries the
   product, container, policy, route, times and status. `notification.trigger_id` and `corrective_action.trigger_id` are
   polymorphic references selected by `trigger_type` and are checked by the validator instead of a SQL foreign key.
   Details: [`docs/erd.md`](docs/erd.md).

### Key decisions and trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| Excursions are explicit, shaped events injected on a bounded baseline | The ground truth is known exactly, and every scenario (brief, prolonged, boundary, critical) is guaranteed to exist | Less physically realistic than a thermal model; the excursion rate (about 1 in 3 shipments) is higher than in real life and is a config setting |
| One detection engine used by both the generator and the validator | A single definition of "excursion", and derived values always come from readings | A bug there could hide from both. Mitigated by hand-built unit tests, a generator self-check (planned events must equal detected events) and a ground truth built from what was injected, not from detector output |
| Gaps are flagged, not filled; excursions never bridge a gap | The brief says a missing interval must not be read as safe | Coverage is 99.7 %, not 100 % |
| Independent random streams per shipment (`SeedSequence.spawn`) | Changing one feature does not reshuffle other shipments; stable, reproducible output | Relies on NumPy's `Generator` stability across versions |
| Readings shipped as gzip CSV/JSONL; the 240 MB `coldchain.db` is git-ignored | Stays under GitHub's 100 MB file limit | Reviewers rebuild the `.db` or load `seed.sql.gz` |
| Two policy versions per product with effective dates | Exercises effective-date logic and the wrong-policy edge case | More joins |
| No UI or API | The brief asks for data, validation and reproducibility | Nothing to click through; the SQL examples above are the quickest way to inspect |

## 4. Rules (all in `src/coldchain/rules.py`)

**Duration convention.** `duration = (last_out_of_range_ts - first_out_of_range_ts) + 5 min`, so one bad reading is 5 minutes.
An excursion is a maximal run of *consecutive* (exactly 5 minutes apart) readings outside the limit in one direction.
It never bridges a gap or a faulty reading.

**Severity.**

| Condition | Severity | Decision |
|---|---|---|
| `duration <= max_excursion_minutes` | `BRIEF` | tolerated, logged (`ACCEPT_WITHIN_TOLERANCE`) |
| `duration > max_excursion_minutes` | `PROLONGED` | quality hold and review |
| `duration >= 3 x max_excursion_minutes` or deviation beyond the limit `>= critical margin` (5 degC / 12 %RH) | `CRITICAL` | reject, replan |

The boundary is inclusive: exactly `max_excursion_minutes` is `BRIEF`, one more reading is `PROLONGED`. The first
`BRIEF` and first `PROLONGED` shipment are generated exactly on these boundaries.

**Reading quality.**
`SENSOR_FAULT`: value outside the sensor's physical range (temperature -50..85 degC, humidity 0..100 %), excluded from excursions.
`LOW_TRUST`: the sensor is *stuck* (12 or more identical consecutive temperature/humidity pairs) or its calibration was
overdue at departure (shipment departs after `sensor.calibration_due`). Excursions on such readings are kept with
`evidence_quality = LOW_TRUST`. Everything else is `GOOD`.

**Gaps.** A missing interval is never in-range and never out-of-range: it is written to `data_gap` as `UNVERIFIED`
(with the neighbouring reading timestamps). Gaps of 6 or more missing readings (30 min) also notify the OT/IT admin and
open an `INVESTIGATE_SENSOR_DROPOUT` action.

**Roles.**

| Role | Receives / does |
|---|---|
| Plant operator | notified of every excursion; logs and monitors brief ones |
| Quality engineer | prolonged and critical excursions: hold review, quarantine and disposition |
| Maintenance engineer | prolonged/critical *temperature* excursions with no route delay: reefer inspection |
| Production planner | critical excursions (replacement shipment) and route delays (replan delivery) |
| OT/IT admin | sensor dropouts of 30 min or more and low-trust (calibration) shipments |

**Status history** is append-only: `OPEN > ACKNOWLEDGED > UNDER_REVIEW > RELEASED | REJECTED`, or
`OPEN > ACKNOWLEDGED > CLOSED_NO_ACTION` for brief excursions. State changes are new rows, never overwrites.

**Simulation.** Baseline = product set-point (midpoint of the policy range) + diurnal term + AR(1) noise + a capped
door-open warm-up at transit hubs. The baseline is bounded to stay well inside the limits, so *every* excursion in the
dataset is an explicit, labelled event with a documented shape (ramp, plateau, recovery). Route delays add 3-12 h to a
leg; 60 % of delayed shipments get a delay-induced excursion inside the extra time (`probable_cause = ROUTE_DELAY`).

## 5. Edge cases and how each is detected

Each deliberate defect is a small share of rows, labelled in `ground_truth`, and never mixed silently into unrelated rows.
All five edge cases required by the brief are included, plus the scenarios its workflow lists.

| `issue_type` | How it is injected | Detected by | Expected decision |
|---|---|---|---|
| `OUT_OF_PHYSICAL_RANGE` (required) | a few readings set to -127 / 150 degC or -5 / 110 %RH, away from any other event | value outside sensor range; flagged `SENSOR_FAULT` and excluded from excursions | `FLAG_SENSOR_FAULT_AND_EXCLUDE_FROM_EXCURSIONS` |
| `SENSOR_DROPOUT_GAP` (required: missing interval read as safe) | 1-3 gaps of 3-40 readings in 8 % of shipments | timestamp step greater than 5 min; row in `data_gap`; the gap is never counted as in-range | `FLAG_UNVERIFIED_DO_NOT_TREAT_AS_SAFE` |
| `DELIVERY_BEFORE_DEPARTURE` (required) | `actual_departure` and `actual_arrival` swapped on 1.5 % of shipments | date-ordering check | `REJECT_RECORD_DATE_ORDER` |
| `WRONG_POLICY` (required: threshold applied to wrong product) | `policy_id` replaced by another product's (effective) policy | `policy.product_id` and effective date vs shipment | `REJECT_RECORD_POLICY_MISMATCH` |
| `DURATION_UNDERCOUNTED` (required) | stored `duration_minutes` reduced by 15-50 % on about 5 % of excursions | recomputed from readings | `RECOMPUTE_DURATION_FROM_READINGS` |
| `CALIBRATION_FAILURE` | `EXPIRED_CALIBRATION` (sensor overdue at departure) or `STUCK_AT_VALUE` (flat-lined run) | calibration date check; stuck-run detector | `FLAG_LOW_TRUST_AND_RECALIBRATE` |
| `ROUTE_DELAY` | a leg arrives 3-12 h late | stop delay increment of 120 min or more | `NOTIFY_PLANNER_AND_REPLAN` |
| `EXCURSION_BRIEF / PROLONGED / CRITICAL` | injected shaped events below / above / far above the permissible duration | recomputed from readings | per the severity table |

## 6. Validation

`python -m coldchain validate --data data/full` re-derives quality flags, gaps, excursions, durations, severity,
workflow rows and custody order **from the raw tables** (it does not trust stored derived values) and runs two groups of checks:

1. **Hard invariants** (must be 0 failures): PK uniqueness; zero-padded ID and timestamp formats; FK integrity
   (also `PRAGMA foreign_key_check` on the SQLite file); enums, units and required fields; date ordering; readings
   inside the trip window and on an exact 5-minute cadence; no duplicate readings; arithmetic reconciliation (readings present plus the gaps listed in `data_gap` equal the expected
   5-minute slots; delays, durations and counts recomputed); CSV, JSON and SQLite hold the same rows and keys; no container overlap; excursion
   counts, durations and severities equal the values recomputed from readings; notification and action routing;
   status-history transitions; custody-event order; **no ground-truth column in any input table**.
2. **Expected anomalies**: the set of anomalies the validator finds must **exactly equal** `ground_truth`
   (precision = recall = 1.0 per issue type). A finding that is not in the ground truth, or a ground-truth row that
   is not found, fails the run.

Result on `data/full` (seed 20261022): **PASS**, 0 hard failures, precision 1.0, recall 1.0 over 828 ground-truth rows.

| Issue type | Expected | Detected |
|---|---|---|
| `OUT_OF_PHYSICAL_RANGE` | 100 | 100 |
| `SENSOR_DROPOUT_GAP` | 157 | 157 |
| `DELIVERY_BEFORE_DEPARTURE` | 15 | 15 |
| `WRONG_POLICY` | 15 | 15 |
| `DURATION_UNDERCOUNTED` | 19 | 19 |
| `CALIBRATION_FAILURE` | 71 | 71 |
| `ROUTE_DELAY` | 80 | 80 |
| `EXCURSION_BRIEF / PROLONGED / CRITICAL` | 202 / 129 / 40 | 202 / 129 / 40 |

Distributions (full): 1,000 shipments on 293 containers; trips 2.0-4.98 days (mean 3.48); 999,663 readings = 99.67 %
of the expected slots (157 gaps, 3,276 missing readings); 371 excursions (320 temperature, 51 humidity; durations p50
50 min, p90 165 min); shipment outcomes 831 delivered, 72 released after hold, 97 rejected. Excursion rate by
product (28-36 %), quality-flag counts and more are in `data/full/validation_summary.md`.

The 38 tests (`make test`) cover ID formats, same-seed/different-seed behaviour, FK integrity, the duration function on
hand-built readings (including the +5 min convention and the exact boundary), gap handling, fault exclusion, stuck
sensors, no leakage, and **mutation tests**: each kind of corruption (deleted gap row, bad FK, bad ID, duplicate PK,
wrong severity, tampered reading, leaked column, missing or extra ground-truth row, container overlap) must be caught.

## 7. Reproducibility proof

`make reproduce-full` generates the full dataset twice into separate folders and compares row counts and the SHA-256
of the *uncompressed* content of every file (so gzip/zlib versions never matter):

```
[run_a] generating ... [run_b] generating ...
  OK  sensor_reading.csv.gz   rows=  999,663  67112de04135edb0...
  OK  excursion.csv           rows=      371  1cb7c7ba2460c7f3...
  OK  seed.sql.gz             rows=        0  57a9a4c374be3536...   (30 files in total)
REPRODUCIBLE: identical row counts and checksums
```

The committed `data/*/checksums.json` lists the expected hashes for seed 20261022. `numpy.random.Generator` streams are
stable across platforms; a major NumPy version change could in principle alter draws, in which case compare
against a regenerated baseline (`reproduce` always compares two runs of the *same* environment).

## 8. Repository layout

```
src/coldchain/
  config.py        seed, volumes, scenario mix, defect rates
  schema.py        tables / fields / enums / ID formats -> DDL, data dictionary, ERD
  rules.py         duration convention, severity, routing, allowed transitions
  master_data.py   products, policies (2 versions), containers, sensors
  scheduling.py    scenarios, container assignment (no overlap), route stops, delays
  readings.py      5-minute simulation, injected excursions / dropouts / stuck, physical-range faults
  detection.py     pure functions: quality flags, gaps, excursions (used by generator AND validator)
  workflow.py      notifications, corrective actions, status history, custody events
  generate.py      pipeline (brief steps 1-10) + record-level defects + ground truth
  export.py        CSV / JSON / SQLite / seed.sql.gz, manifest, checksums
  validate.py      hard invariants + ground-truth comparison + metrics
  cli.py           generate | validate | reproduce | docs
tests/             unit, property and mutation tests
ai_usage/          prompt history and AI-use disclosure (company guideline 03)
docs/              data_dictionary.md, erd.md (generated)
data/starter, data/full
```

Mapping to the brief: Step 1 `schema.py` + `docs/`; 2-3 `master_data.py`, `scheduling.py`; 4-5 `readings.py`;
6 `detection.py`, `workflow.py`; 7 defects in `readings.py` / `generate.py`; 7 ground truth `ground_truth.*`;
8 `validate.py`; 9 `export.py` + README + manifest; 10 `reproduce`.

## 9. Data provenance and lawful use

All data is generated by this repository's code. No public datasets were downloaded, so no source URLs, licences,
retrieval dates or discarded fields apply. The product names are generic; no personal or confidential information is used.
Temperature and humidity ranges (for example 2-8 degC for vaccines and insulin, -18 degC and below for frozen goods) follow
commonly published storage guidance, but no dataset was copied; every value and limit is a simplified assumption made
for synthetic data.

## 10. Limitations and future work

- Excursions are explicit events rather than the output of a thermal model; real reefer physics (compressor cycling,
  load mass, defrost) is simplified to a lag model. The excursion rate (about 1 in 3 shipments) is deliberately high so
  every scenario is well represented; it is a config setting (`scenario_mix`).
- One sensor per container; no multi-sensor disagreement or sensor swap.
- Routes are city names only (no geography, no travel-time model).
- Possible extensions: a second sensor type, correlated multi-container incidents, seasonality by lane, streaming output.
