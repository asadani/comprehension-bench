<p align="center">
  <img src="assets/logo.svg" alt="Comprehension Bench — Measure understanding, openly" width="400" height="160">
</p>

Comprehension Bench keeps small explanation studies auditable. It stores exact answers, manually reviewed rubric scores, first/practice/repeat attempts, and the full expected participant-by-task grid. Missing work stays missing; an explicit zero score stays a scored zero.

The bundled study about a document preview flow uses four pseudonymous participants, two synthetic artifact conditions, and three tasks. Every participant, answer, timestamp, and score in the fixtures is synthetic demonstration data.

## Quickstart

Run from this repository directory with Python 3.11 or newer:

```sh
python -m comprehension_bench --help
python -m comprehension_bench validate fixtures/study.json
python -m comprehension_bench summarize fixtures/study.json --ledger fixtures/completed-run.json --out /tmp/comprehension-summary.json
python -m comprehension_bench export fixtures/study.json --ledger fixtures/completed-run.json --out /tmp/comprehension-observations.csv
```

Expected result: help and validation exit `0`; summary and CSV export exit `0`. The summary contains all 12 expected primary rows. For the docs condition's `trace-request` task, its mean normalized score is `0.375` across 2 scored observations: p01's latest manual score is 3/4 and p02's explicit score is 0/4. A task with no scored answers has a null mean and denominator 0. The p01 authorization answer is submitted but unscored; p02's change-location task is in progress; never-started tasks remain in the summary and CSV.

The fixture also records earlier practice for p01 before their first attempt. The summary marks that primary row `prior_exposure: true`, lists the earlier practice attempt and reports that first-attempt results include prior-exposed participants. Practice and repeat counts remain separate from primary averages.

## Record a small run

This shell example creates a fresh temporary ledger, records one first attempt, submits the supplied answer, and appends a manual score. The `start` command prints an attempt ID, which the shell passes to the following commands:

```sh
LEDGER="/tmp/comprehension-run-$$.json"
ATTEMPT_ID=$(python -m comprehension_bench start fixtures/study.json --participant p04 --condition interactive --task trace-request --kind first --ledger "$LEDGER")
python -m comprehension_bench submit fixtures/study.json --attempt "$ATTEMPT_ID" --answer-file fixtures/answer-p01.txt --ledger "$LEDGER"
python -m comprehension_bench score fixtures/study.json --attempt "$ATTEMPT_ID" --scores fixtures/score-p01.json --reviewer demo-reviewer --ledger "$LEDGER"
```

Expected result: all three commands exit `0`; the first creates a UUID attempt. Timestamps are actual UTC observations by default. Imported observations may supply explicit timezone-aware `--at` values to `start` and `submit`. Scores require a submitted answer, all rubric IDs, integer values within each item maximum, a non-empty rationale, and a reviewer label. Scoring again appends a revision; the previous score remains in the ledger.

Run the acceptance tests:

```sh
python -m unittest discover -s tests -v
```

Expected result: all tests pass with exit `0`. They cover the 12-row grid, score denominators, explicit zero, blank versus unsubmitted answers, practice exposure, cross-condition attempts, timestamp order, one-time submission, overlapping attempts, score revisions, study-hash changes, CSV quoting/formula escaping, and the CLI lifecycle.

## Data and interpretation

The ledger binds to a SHA-256 of canonical study JSON with sorted object keys and compact separators. Whitespace and object-key order do not alter the binding; a changed rubric or assignment does. Use a separate ledger for a changed study. Artifact labels, paths, or URLs are stored as text and never fetched. The ledger is written atomically for each state change.

Summary means use normalized task scores, so a 4-point task and a 6-point task are not pooled as raw points. Condition-level means are across scored participant-task observations and are not balanced participant-level estimates. Median duration uses submitted first attempts only; time is not evidence of comprehension. CSV text cells beginning with `=`, `+`, `-`, `@`, tab, or carriage return receive a leading apostrophe to reduce spreadsheet formula execution risk. JSON ledger answers are preserved exactly.

## Limits

Scoring is manual; the tool does not auto-grade, randomize, collect identity or demographic data, establish causality, report p-values, rank a winner, or infer comprehension from reading time. The fixture is synthetic, not study evidence. Results are descriptive observations with explicit denominators and missingness. A reviewer label is recorded as supplied; this v0.1 format does not maintain a reviewer roster.

## Data integrity

Every attempt must explicitly contain `answer` and `submitted_at`, using null before submission. Summaries and exports refuse to overwrite the study or ledger; observation mutations also protect answer and score input files.

See [verification coverage](docs/VERIFICATION.md) and [the design plan](docs/PLAN.md) for tested behavior and remaining limits.

## License

Licensed under the [MIT License](LICENSE). Copyright (c) 2026 Anuj Sadani.
