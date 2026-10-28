# AI Use Disclosure and Prompt History

Written for company guideline 03 ("use LLMs transparently") and FAQ 6 ("include all prompts submitted to every AI tool you
used"). It describes what actually happened; it is not a reconstruction.

## 1. Summary

| Item | Details |
|---|---|
| AI tool used for planning and implementation | Claude (Anthropic), in the claude.ai chat interface |
| Period | October 2026, inside the 72-hour window |
| Where AI accelerated the work | Everything technical: reading the problem statement from screenshots, the implementation plan, all modules under `src/coldchain/`, the tests, the Makefile and CI file, the generated documentation, the generated datasets, and the review of the final repository |
| Where I relied heavily on it | The whole first implementation (generator, exporter, validator, CLI, tests) was written by Claude and accepted by me |
| Other AI tools | [CANDIDATE TO COMPLETE BEFORE SUBMITTING: list every other AI tool you used on this project. FAQ 6 requires the prompts you sent to each of them to be included in this folder. If you used none, write "None".] |
| Limitation of this record | AI responses are not included (optional under FAQ 6). The prompts below are copied exactly, including typing errors |

## 2. Prompt log: every prompt sent to Claude, verbatim

| # | Prompt | What came back |
|---|---|---|
| 1 | *(two screenshots of the problem statement attached)* "this is the problem statement which is give by a company i am appling for so they assign me that tasks to complete and submit it in 2 days so i want you  to make it proper and make a full implementation plan" | A written implementation plan: data model, pipeline, edge cases, validation, tests, timeline, README outline, checklist |
| 2 | "ok so the implementation plan is ready now what we have to do is make it" | The build started |
| 3 | "continue" | The generator, exporter, validator, CLI, tests, docs and README; both datasets generated and validated; the reproducibility check run; `cold-chain-synth.zip` delivered |
| 4 | *(uploaded `cold-chain-synth.zip`)* "check this zip file accoring to the project details that the project is completed or not" | A review of the uploaded copy against the brief: tests run, generator run, copy compared with the delivered version |
| 5 | "and make it in submittion process" | Fixes and a submission-ready package |
| 6 | *(three more screenshots of the problem statement, plus the company's Submission Guidelines PDF and Candidate FAQ PDF attached)* "this is the everything that given by the company and now you can veerify and check eveything are done or need to change" | An audit against the brief, the guidelines and the FAQ, and the changes in section 4 |

## 3. Who decided what

- The architecture, the rules (for example the duration convention `(last - first) + 5 minutes`, the inclusive boundary at
  `max_excursion_minutes`, keeping ground truth out of every input table) and the first implementation were **proposed and
  written by Claude** and accepted by me.
- After the first delivery, my local copy was edited outside the Claude conversation: cross-platform run instructions in
  the README, two extra documents, defensive guards and UTF-8 encodings in several modules, an `.gitattributes` file and a
  larger `.gitignore`. Claude reviewed those edits in prompt 4, kept the useful ones and fixed the defects in section 4.
- **Git history.** The commits in this repository were assembled in logical steps (skeleton, schema, scheduling, simulation,
  workflow, export, validator, CLI, tests, docs, data, disclosure) from the finished code. They are an organised view of the
  work, not a live record of how it was written.

## 4. Review findings and fixes

| Finding | Fix |
|---|---|
| `timeutil.to_minutes` assumed nanosecond datetimes. On pandas 3 every timestamp collapsed to one value and validation failed (946 hard-invariant failures) | Rewritten to be resolution-independent; regression test added |
| `.gitignore` excluded `data/`, so the exported datasets required by Step 9 of the brief would be missing | Only the 240 MB `coldchain.db` is ignored; `data/starter` and `data/full` are committed |
| README said "four" required edge cases; the brief lists five | Corrected |
| Wrong statements in the documentation (policy v1 start date, "cryptographic evidence", wrong-policy "caught by FK validation", local file paths, stale checksums and test counts) | Corrected |
| An earlier draft of this file described prompts and "interventions" that did not take place | Replaced by this log |
| Step 8 of the brief asks for arithmetic reconciliation and duplicate checks, and "IDs exactly consistent across files"; none was an explicit validator check | Added `reconcile.reading_counts`, `reading.no_duplicates` and `format.consistency` (CSV = JSON = SQLite), each with a mutation test |
| The new cross-format check found that `sensor_reading.jsonl.gz` ended with a blank line | Exporter fixed |
| The brief asks to document many-to-many relationships with bridge tables; the docs did not say how they are handled | Documented: `shipment` is the bridge for Product N:M Container |
| Guideline 04 asks for trade-offs and limitations; guideline 01 asks for steps to verify key behaviour | README gained a trade-offs table and a "verify key behaviour in two minutes" section |

## 5. Verification performed by Claude during the session

- 38 automated tests pass (unit, property and mutation tests).
- `data/full` (1,000 shipments, 300 containers, 999,663 readings): 0 hard-invariant failures, precision 1.0 and recall 1.0
  against 828 ground-truth rows.
- Two independent generations with seed `20261022` give identical row counts and SHA-256 checksums for all 30 files, and match the
  committed `checksums.json`.
- A fresh virtual environment installs the package, runs the tests and regenerates the starter dataset.

## 6. What I personally reviewed, changed and validated

[CANDIDATE TO COMPLETE BEFORE SUBMITTING, in your own words and only with things you actually did: for example the files you read
and can explain, parameters you changed and what happened, a deliberate corruption you tried and how the validator reacted, the
date you cloned the public repository fresh and ran `make test` and `make generate-starter`.]

I am responsible for understanding this code and being able to explain it.
