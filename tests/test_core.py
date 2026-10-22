import copy
import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from comprehension_bench.core import StudyError, export_csv, export_rows, new_ledger, record_score, start_attempt, study_sha256, submit_answer, summarize, validate_ledger, validate_study


def fixture(name):
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


class ComprehensionBenchTests(unittest.TestCase):
    def setUp(self):
        self.study = fixture("study.json")
        self.ledger = fixture("completed-run.json")

    def test_study_hash_is_canonical_and_validation_rejects_bad_schema(self):
        changed_key_order = json.loads(json.dumps(self.study, sort_keys=True))
        self.assertEqual(study_sha256(self.study), study_sha256(changed_key_order))
        bad = copy.deepcopy(self.study)
        bad["tasks"][0]["rubric"][0]["max_points"] = True
        with self.assertRaisesRegex(StudyError, "positive integer"):
            validate_study(bad)
        bad = copy.deepcopy(self.study)
        bad["schema_version"] = 1.0
        with self.assertRaisesRegex(StudyError, "integer 1"):
            validate_study(bad)

    def test_fixture_has_all_expected_rows_and_missingness_aware_denominators(self):
        result = summarize(self.study, self.ledger)
        self.assertEqual(len(result["primary_rows"]), 12)
        rows = {(r["participant_id"], r["task_id"]): r for r in result["primary_rows"]}
        self.assertEqual(rows[("p01", "authorization-boundary")]["status"], "submitted_unscored")
        self.assertEqual(rows[("p02", "change-location")]["status"], "in_progress")
        self.assertEqual(rows[("p01", "change-location")]["status"], "not_started")
        self.assertEqual(rows[("p03", "change-location")]["answer"], "")
        self.assertIsNotNone(rows[("p03", "change-location")]["submitted_at"])
        self.assertEqual(rows[("p02", "trace-request")]["points"], 0)
        self.assertEqual(rows[("p02", "trace-request")]["normalized_score"], 0)
        self.assertEqual(rows[("p01", "trace-request")]["points"], 3)
        self.assertTrue(rows[("p01", "trace-request")]["prior_exposure"])
        docs_trace = next(x for x in result["condition_task"] if x["condition_id"] == "docs" and x["task_id"] == "trace-request")
        self.assertEqual((docs_trace["expected_count"], docs_trace["started_count"], docs_trace["submitted_count"], docs_trace["scored_count"]), (2, 2, 2, 2))
        self.assertEqual(docs_trace["mean_normalized_score"], 0.375)
        self.assertEqual(docs_trace["mean_score_denominator"], 2)
        docs_auth = next(x for x in result["condition_task"] if x["condition_id"] == "docs" and x["task_id"] == "authorization-boundary")
        self.assertEqual((docs_auth["missing_count"], docs_auth["unscored_count"], docs_auth["scored_count"]), (1, 1, 0))
        self.assertIsNone(docs_auth["mean_normalized_score"])
        self.assertEqual(docs_auth["median_duration_seconds"], 480)
        self.assertEqual(docs_auth["median_duration_denominator"], 1)
        docs_change = next(x for x in result["condition_task"] if x["condition_id"] == "docs" and x["task_id"] == "change-location")
        self.assertIsNone(docs_change["median_duration_seconds"])
        self.assertEqual(docs_change["median_duration_denominator"], 0)
        self.assertEqual(len(result["prior_exposure"]), 1)
        self.assertEqual(result["prior_exposure"][0]["prior_attempts"][0]["condition_id"], "interactive")
        self.assertEqual(len(result["cross_condition_attempts"]), 3)
        self.assertIn("First-attempt results include prior-exposed participants.", result["limitations"])
        interactive_trace = next(x for x in result["condition_task"] if x["condition_id"] == "interactive" and x["task_id"] == "trace-request")
        self.assertEqual(interactive_trace["median_duration_seconds"], 270)
        overall = next(x for x in result["condition_overall"] if x["condition_id"] == "interactive")
        self.assertEqual(overall["scored_observation_count"], 2)
        self.assertEqual(overall["mean_normalized_score"], 0.75)

    def test_start_constraints_pure_copy_and_utc_normalization(self):
        ledger = new_ledger(self.study)
        started = start_attempt(self.study, ledger, "p01", "docs", "trace-request", "first", "2026-10-22T15:30:00+05:30", "new-first")
        self.assertEqual(ledger["attempts"], [])
        self.assertEqual(started["attempts"][0]["started_at"], "2026-10-22T10:00:00Z")
        with self.assertRaisesRegex(StudyError, "condition must match"):
            start_attempt(self.study, ledger, "p01", "interactive", "trace-request", "first", "2026-10-22T10:00:00Z", "wrong-condition")
        with self.assertRaisesRegex(StudyError, "unfinished attempt"):
            start_attempt(self.study, started, "p01", "docs", "trace-request", "practice", "2026-10-22T10:01:00Z", "overlap")
        with self.assertRaisesRegex(StudyError, "first attempt already exists"):
            submitted = submit_answer(self.study, started, "new-first", "", "2026-10-22T10:10:00Z")
            start_attempt(self.study, submitted, "p01", "docs", "trace-request", "first", "2026-10-22T10:11:00Z", "duplicate-first")
        imported = copy.deepcopy(self.ledger)
        legacy_attempt = next(a for a in imported["attempts"] if a["id"] == "attempt-p01-trace-first")
        legacy_attempt["started_at"] = "2026-10-21T14:30:00+05:30"
        legacy_attempt["submitted_at"] = "2026-10-21T14:38:00+05:30"
        legacy_attempt["scores"][0]["scored_at"] = "2026-10-21T14:50:00+05:30"
        legacy_attempt["scores"][1]["scored_at"] = "2026-10-21T15:00:00+05:30"
        normalized = start_attempt(self.study, imported, "p04", "interactive", "change-location", "practice", "2026-10-22T10:00:00Z", "normalizes-import")
        first = next(a for a in normalized["attempts"] if a["id"] == "attempt-p01-trace-first")
        self.assertEqual(first["started_at"], "2026-10-21T09:00:00Z")
        self.assertEqual(first["scores"][0]["scored_at"], "2026-10-21T09:20:00Z")

    def test_submission_preserves_empty_and_multiline_text_and_checks_time(self):
        ledger = new_ledger(self.study)
        started = start_attempt(self.study, ledger, "p02", "docs", "trace-request", "first", "2026-10-22T10:00:00Z", "attempt")
        with self.assertRaisesRegex(StudyError, "precedes"):
            submit_answer(self.study, started, "attempt", "answer", "2026-10-22T09:59:59Z")
        empty = submit_answer(self.study, started, "attempt", "", "2026-10-22T10:00:01Z")
        row = next(row for row in summarize(self.study, empty)["primary_rows"] if row["participant_id"] == "p02" and row["task_id"] == "trace-request")
        self.assertEqual((row["status"], row["answer"]), ("submitted_unscored", ""))
        with self.assertRaisesRegex(StudyError, "already been submitted"):
            submit_answer(self.study, empty, "attempt", "again", "2026-10-22T10:00:02Z")
        started = start_attempt(self.study, ledger, "p02", "docs", "trace-request", "first", "2026-10-22T10:00:00Z", "multiline")
        answer = "=SUM(A1:A2)\r\nsecond line\n"
        submitted = submit_answer(self.study, started, "multiline", answer, "2026-10-22T10:01:00Z")
        self.assertEqual(submitted["attempts"][0]["answer"], answer)

    def test_score_ranges_exact_keys_and_revision_history(self):
        attempt = next(a for a in self.ledger["attempts"] if a["id"] == "attempt-p01-trace-first")
        self.assertEqual(len(attempt["scores"]), 2)
        self.assertEqual(attempt["scores"][0]["items"]["evidence"], 0)
        self.assertEqual(attempt["scores"][1]["items"]["evidence"], 1)
        empty = new_ledger(self.study)
        started = start_attempt(self.study, empty, "p01", "docs", "trace-request", "first", "2026-10-22T10:00:00Z", "score-attempt")
        with self.assertRaisesRegex(StudyError, "before scoring"):
            record_score(self.study, started, "score-attempt", {"items": {"sequence": 1, "evidence": 1}, "note": "note"}, "r01", "2026-10-22T10:01:00Z")
        submitted = submit_answer(self.study, started, "score-attempt", "answer", "2026-10-22T10:01:00Z")
        for scores, message in (
            ({"items": {"sequence": 1}, "note": "missing criterion"}, "exactly"),
            ({"items": {"sequence": True, "evidence": 1}, "note": "bool"}, "integer"),
            ({"items": {"sequence": 3, "evidence": 1}, "note": "high"}, "from 0 to 2"),
            ({"items": {"sequence": 1, "evidence": 1}, "note": " "}, "non-empty"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(StudyError, message):
                record_score(self.study, submitted, "score-attempt", scores, "r01", "2026-10-22T10:02:00Z")
        scored = record_score(self.study, submitted, "score-attempt", {"items": {"sequence": 2, "evidence": 1}, "note": "Reviewed criteria."}, "r01", "2026-10-22T10:02:00Z")
        revised = record_score(self.study, scored, "score-attempt", {"items": {"sequence": 1, "evidence": 0}, "note": "Second reviewer applied the rubric."}, "r02", "2026-10-22T10:03:00Z")
        self.assertEqual(len(revised["attempts"][0]["scores"]), 2)
        row = summarize(self.study, revised)["primary_rows"][0]
        self.assertEqual((row["points"], row["reviewer"]), (1, "r02"))

    def test_ledger_rejects_changed_study_and_duplicate_first_attempt(self):
        changed = copy.deepcopy(self.study)
        changed["tasks"][0]["prompt"] += " Revised."
        with self.assertRaisesRegex(StudyError, "study hash differs"):
            validate_ledger(changed, self.ledger)
        duplicate = copy.deepcopy(self.ledger)
        first = next(a for a in duplicate["attempts"] if a["kind"] == "first")
        duplicate["attempts"].append(copy.deepcopy(first))
        duplicate["attempts"][-1]["id"] = "different-id"
        with self.assertRaisesRegex(StudyError, "more than one first"):
            validate_ledger(self.study, duplicate)
        with self.assertRaisesRegex(StudyError, "schema_version"):
            validate_study({**self.study, "schema_version": True})

    def test_csv_contains_expected_and_extra_attempts_safely(self):
        rows = export_rows(self.study, self.ledger)
        self.assertEqual(len(rows), 15)
        csv_text = export_csv(self.study, self.ledger)
        parsed = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(len(parsed), 15)
        target = next(row for row in parsed if row["attempt_id"] == "attempt-p01-auth-first")
        self.assertTrue(target["answer"].startswith("'=SUM(A1:A2)"))
        self.assertIn("\n", target["answer"])
        self.assertEqual(target["status"], "submitted_unscored")
        self.assertEqual(target["points"], "")
        zero = next(row for row in parsed if row["attempt_id"] == "attempt-p02-trace-first")
        self.assertEqual(zero["points"], "0")
        raw_answer = next(a["answer"] for a in self.ledger["attempts"] if a["id"] == "attempt-p01-auth-first")
        self.assertTrue(raw_answer.startswith("=SUM"))
        self.assertTrue(any(row["status"] == "not_started" and row["attempt_id"] == "" for row in parsed))
        unsafe = copy.deepcopy(self.ledger)
        prefixes = ["=", "+", "-", "@", "\t", "\r"]
        for attempt, prefix in zip([a for a in unsafe["attempts"] if a["submitted_at"] is not None][:len(prefixes)], prefixes):
            attempt["answer"] = prefix + "payload"
        safe_rows = list(csv.DictReader(io.StringIO(export_csv(self.study, unsafe), newline="")))
        for prefix in prefixes:
            self.assertIn("'" + prefix + "payload", [row["answer"] for row in safe_rows])

    def test_cli_lifecycle_and_read_only_exports(self):
        def run(*args):
            return subprocess.run([sys.executable, "-m", "comprehension_bench", *args], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(run("--help").returncode, 0)
        self.assertEqual(run("--version").stdout.strip(), "0.1.0")
        self.assertEqual(run("validate", "fixtures/study.json").returncode, 0)
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "run.json"
            started = run("start", "fixtures/study.json", "--participant", "p04", "--condition", "interactive", "--task", "trace-request", "--kind", "first", "--ledger", str(ledger_path))
            self.assertEqual(started.returncode, 0, started.stderr)
            attempt_id = started.stdout.strip()
            answer_path = Path(temp) / "answer.txt"
            answer_path.write_bytes(b"line one\r\nline two\n")
            submitted = run("submit", "fixtures/study.json", "--attempt", attempt_id, "--answer-file", str(answer_path), "--ledger", str(ledger_path))
            self.assertEqual(submitted.returncode, 0, submitted.stderr)
            ledger = json.loads(ledger_path.read_text())
            self.assertEqual(ledger["attempts"][0]["answer"], "line one\r\nline two\n")
            scored = run("score", "fixtures/study.json", "--attempt", attempt_id, "--scores", "fixtures/score-p01.json", "--reviewer", "cli-reviewer", "--ledger", str(ledger_path))
            self.assertEqual(scored.returncode, 0, scored.stderr)
            summary = run("summarize", "fixtures/study.json", "--ledger", "fixtures/completed-run.json", "--out", str(Path(temp) / "summary.json"))
            self.assertEqual(summary.returncode, 0, summary.stderr)
            exported = run("export", "fixtures/study.json", "--ledger", "fixtures/completed-run.json", "--out", str(Path(temp) / "observations.csv"))
            self.assertEqual(exported.returncode, 0, exported.stderr)
            changed_study = Path(temp) / "changed.json"
            changed = fixture("study.json"); changed["title"] += " altered"
            changed_study.write_text(json.dumps(changed))
            mismatch = run("summarize", str(changed_study), "--ledger", "fixtures/completed-run.json", "--out", str(Path(temp) / "bad.json"))
            self.assertEqual(mismatch.returncode, 2)
            self.assertNotIn("Traceback", mismatch.stderr)

    def test_cli_prevents_input_overwrites_and_preserves_original_bytes(self):
        def run(*args):
            return subprocess.run([sys.executable, "-m", "comprehension_bench", *args], cwd=ROOT, text=True, capture_output=True)
        study = ROOT / "fixtures/study.json"
        ledger = ROOT / "fixtures/completed-run.json"
        study_bytes, ledger_bytes = study.read_bytes(), ledger.read_bytes()
        score_file = ROOT / "fixtures/score-p01.json"
        score_bytes = score_file.read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            alias = Path(temp) / "ledger-alias.json"
            alias.symlink_to(ledger)
            summary = run("summarize", str(study), "--ledger", str(ledger), "--out", str(alias))
            self.assertEqual(summary.returncode, 2)
            self.assertIn("refusing to overwrite input", summary.stderr)
            export = run("export", str(study), "--ledger", str(ledger), "--out", str(ledger))
            self.assertEqual(export.returncode, 2)
            start = run("start", str(study), "--participant", "p04", "--condition", "interactive", "--task", "trace-request", "--kind", "first", "--ledger", str(study))
            self.assertEqual(start.returncode, 2)
            score = run("score", str(study), "--attempt", "attempt-p01-trace-first", "--scores", str(score_file), "--reviewer", "reviewer", "--ledger", str(score_file))
            self.assertEqual(score.returncode, 2)
        self.assertEqual(study.read_bytes(), study_bytes)
        self.assertEqual(ledger.read_bytes(), ledger_bytes)
        self.assertEqual(score_file.read_bytes(), score_bytes)


if __name__ == "__main__":
    unittest.main()
