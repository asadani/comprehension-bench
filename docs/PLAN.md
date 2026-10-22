# Comprehension Bench v0.1 implementation plan

## User job and CLI

Manage a small local study ledger, record answers and manual rubric scores, and export descriptive summaries that preserve missingness and prior task exposure.

```sh
python -m comprehension_bench validate fixtures/study.json
python -m comprehension_bench start fixtures/study.json --participant p01 --condition interactive --task trace-request --kind first --ledger run.json
python -m comprehension_bench submit fixtures/study.json --attempt <attempt-id> --answer-file fixtures/answer-p01.txt --ledger run.json
python -m comprehension_bench score fixtures/study.json --attempt <attempt-id> --scores fixtures/score-p01.json --reviewer r01 --ledger run.json
python -m comprehension_bench summarize fixtures/study.json --ledger fixtures/completed-run.json --out summary.json
python -m comprehension_bench export fixtures/study.json --ledger fixtures/completed-run.json --out observations.csv
```

`start` creates the ledger if absent and prints a generated attempt ID. `submit` reads a UTF-8 answer; blank answers are allowed and remain submitted. `score` appends a manual scoring revision (preserve old scores), never auto-grades. `summarize` and `export` are read-only. All valid commands return 0 even with missing data; invalid inputs or incompatible ledger/study return 2. CLI may support `--at` for explicit ISO 8601 timestamps on start/submit for imported observations; otherwise use actual UTC time, never fabricated fixture times.

## Study and ledger formats

Study: `{schema_version:1,id,title,conditions:[{id,label,artifact}],participants:[{id,condition_id}],tasks:[{id,prompt,rubric:[{id,description,max_points}]}]}`. Artifact is an opaque label/path/URL recorded as text, not fetched. IDs unique in each collection. Participant assignment supplies the primary condition; no demographic/identity fields are needed. Rubric max_points are positive integers, never booleans. Each task has at least one rubric item. All participants are expected to attempt every listed task once in their assigned condition; that explicit expectation defines missing task rows.

Ledger: `{schema_version:1,study_id,study_sha256,attempts:[{id,participant_id,condition_id,task_id,kind:"first"|"practice"|"repeat",started_at,submitted_at:null|timestamp,answer:null|string,scores:[{reviewer,scored_at,items:{rubric_id:points},note}]}]}`. Bind ledger to canonical study JSON SHA-256 (sorted compact keys) to avoid silently applying a changed rubric or assignment; mismatch is an error requiring a separate study/ledger. Actual source file whitespace does not change canonical hash.

Start creates a unique attempt ID (UUID is fine; real observations need uniqueness, not deterministic timestamps). A `first` attempt must match participant's assigned condition and there may be at most one first attempt per participant/task. Practice/repeat attempts may use another condition but retain that fact. Prevent overlapping unfinished attempts for the same participant/task. Submitting an attempt is one-time, requires time >= started_at, and preserves exact answer text; a duplicate submission is rejected. Empty answer and no submission are distinct. Score requires submission, known reviewer string, exact rubric keys, integer points in [0,max_points], and nonempty note explaining the judgment. Latest score revision is active; earlier revisions remain in history.

## Aggregation and learning-safe defaults

Summarize the complete participant × task expectation grid, even when no attempt exists. Primary rows use each first attempt only. Statuses are `not_started`, `in_progress`, `submitted_unscored`, `scored`. Do not turn missing/unscored answers into zero points. An explicit all-zero manual score is a scored zero. Duration is submitted_at minus started_at for submitted attempts, otherwise null. Timestamps require explicit timezone and normalize to UTC; reject negative duration. Time is an observation, not proof of comprehension.

For each condition and task, show expected participant count, started count, submitted count, scored count, missing/unscored counts, mean normalized score among scored first attempts, median duration among submitted first attempts, and each statistic's denominator. Normalize each scored task by its own maximum points. For each condition overall, show mean across scored participant-task observations plus its count; do not present it as a balanced participant-level estimate. Empty denominators yield null, never zero/NaN. Do not pool raw points across tasks with different rubric maxima.

Include separate descriptive counts for practice/repeat attempts; exclude them from primary means. Mark `prior_exposure: true` on a first attempt if any earlier-started practice/repeat attempt for that participant/task exists, especially under another condition. Summaries list exposed primary attempts and include “First-attempt results include prior-exposed participants” when present; do not silently discard them or claim a clean experiment. Also list cross-condition attempts. The tool describes observations, not causal effects; no p-values, rankings, “winner,” percentages of improvement, or invented statistical confidence.

## Core API and exports

- `validate_study(study: dict) -> None`
- `validate_ledger(study: dict, ledger: dict) -> None`
- `start_attempt(study: dict, ledger: dict, participant_id: str, condition_id: str, task_id: str, kind: str, started_at: str, attempt_id: str) -> dict`
- `submit_answer(study: dict, ledger: dict, attempt_id: str, answer: str, submitted_at: str) -> dict`
- `record_score(study: dict, ledger: dict, attempt_id: str, scores: dict, reviewer: str, scored_at: str) -> dict`
- `summarize(study: dict, ledger: dict) -> dict`
- `export_rows(study: dict, ledger: dict) -> list[dict]`

Score input file: `{items:{rubric_id:integer},note:string}`. Pure APIs return new ledger data without mutating input. CLI validates and atomically replaces ledger files. Summary has schema version, study ID/hash, primary row details, condition/task aggregates, practice/repeat counts, exposure findings, and explicit limitations.

CSV includes one row per expected primary participant/task even when missing, plus separate rows for practice/repeat attempts. Columns: participant_id, assigned_condition, observed_condition, task_id, attempt_id, kind, status, started_at, submitted_at, duration_seconds, points, max_points, normalized_score, reviewer, prior_exposure, answer, score_note. Null numeric fields are empty. Use stdlib csv quoting. Escape spreadsheet formula-leading text cells (`=`, `+`, `-`, `@`, tab, carriage return) with a leading apostrophe in CSV only; preserve exact raw answers in JSON ledger and document this export transformation.

## Fixtures and acceptance tests

1. Fixture has two conditions, four pseudonymous participants, three tasks with meaningful rubrics, and a completed-run ledger containing scored, unscored, unfinished, and never-started tasks. Summary retains all 12 expected primary rows and correct denominators.
2. A manual zero score contributes 0; missing/unscored is null and excluded from mean. Unequal task maxima produce correct normalized scores. Empty groups return null means/medians.
3. First/practice/repeat distinction is preserved. Practice before first marks prior exposure; same task in another condition is disclosed; repeats never inflate primary count/mean.
4. Submission time ordering, timezone validation, duplicate first attempts, repeated submission, overlapping unfinished attempts, unknown IDs, wrong rubric keys, out-of-range/bool scores, and changed study hash are rejected without corrupting the ledger.
5. Score revision changes the active aggregate but keeps previous scoring history. An empty submitted answer is distinguishable from an unsubmitted task.
6. CSV includes missing rows and correct quoting for multiline answers; formula-leading answers are neutralized only in CSV. Raw JSON preserves the answer exactly.
7. CLI start/submit/score/summarize works in a temp ledger using real observations or explicit controlled test timestamps. Deterministic summaries from identical ledgers contain no invented generation times or empirical claims.

## Non-goals and milestone

Required: study validation, observation ledger, manual rubric scoring, first/practice distinction, missingness-aware summary, CSV export, tests. Deferred: automatic grading, study randomization, participant web app, consent workflow, causal inference, significance testing, artifact hosting, collection of personal identities.

Build study/ledger validation and state transitions, then grid-based aggregation, then CLI/export. Done means every reported average is auditable back to the exact scored attempts and every missing task remains visible.
