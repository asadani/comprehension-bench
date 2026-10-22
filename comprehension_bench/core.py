"""Study validation, observation ledger transitions, and summaries."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import statistics
from datetime import datetime, timezone
from typing import Any


class StudyError(ValueError):
    """An actionable study, ledger, or observation error."""


def need(ok: bool, message: str) -> None:
    if not ok:
        raise StudyError(message)


def text(value: Any, where: str) -> None:
    need(isinstance(value, str) and bool(value.strip()), f"{where} must be a non-empty string")


def _unique(items: list[dict], key: str, where: str) -> dict[str, dict]:
    result = {}
    for i, item in enumerate(items):
        need(isinstance(item, dict), f"{where}[{i}] must be an object")
        value = item.get(key)
        text(value, f"{where}[{i}].{key}")
        need(value not in result, f"duplicate {key}: {value}")
        result[value] = item
    return result


def validate_study(study: dict) -> None:
    need(isinstance(study, dict), "study must be an object")
    version = study.get("schema_version")
    need(isinstance(version, int) and not isinstance(version, bool) and version == 1, "schema_version must be integer 1")
    text(study.get("id"), "study.id")
    text(study.get("title"), "study.title")
    for key in ("conditions", "participants", "tasks"):
        need(isinstance(study.get(key), list) and bool(study[key]), f"study.{key} must be a non-empty array")
    conditions = _unique(study["conditions"], "id", "conditions")
    for ident, condition in conditions.items():
        text(condition.get("label"), f"condition {ident}.label")
        text(condition.get("artifact"), f"condition {ident}.artifact")
    participants = _unique(study["participants"], "id", "participants")
    for ident, participant in participants.items():
        condition_id = participant.get("condition_id")
        need(isinstance(condition_id, str) and condition_id in conditions, f"participant {ident} has unknown condition_id")
    tasks = _unique(study["tasks"], "id", "tasks")
    for ident, task in tasks.items():
        text(task.get("prompt"), f"task {ident}.prompt")
        rubric = task.get("rubric")
        need(isinstance(rubric, list) and bool(rubric), f"task {ident}.rubric must be a non-empty array")
        items = _unique(rubric, "id", f"task {ident}.rubric")
        for item_id, item in items.items():
            text(item.get("description"), f"rubric {ident}/{item_id}.description")
            points = item.get("max_points")
            need(isinstance(points, int) and not isinstance(points, bool) and points > 0, f"rubric {ident}/{item_id}.max_points must be a positive integer")


def study_sha256(study: dict) -> str:
    validate_study(study)
    try:
        canonical = json.dumps(study, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StudyError(f"study cannot be canonically encoded: {exc}") from exc
    return hashlib.sha256(canonical).hexdigest()


def new_ledger(study: dict) -> dict:
    validate_study(study)
    return {"schema_version": 1, "study_id": study["id"], "study_sha256": study_sha256(study), "attempts": []}


def parse_time(value: Any, where: str) -> datetime:
    need(isinstance(value, str), f"{where} must be an ISO 8601 timestamp with a timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StudyError(f"{where} must be an ISO 8601 timestamp with a timezone") from exc
    need(result.tzinfo is not None and result.utcoffset() is not None, f"{where} must include a timezone")
    return result.astimezone(timezone.utc)


def format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="auto").replace("+00:00", "Z")


def _normalized_ledger(ledger: dict) -> dict:
    revised = copy.deepcopy(ledger)
    for attempt in revised["attempts"]:
        attempt["started_at"] = format_time(parse_time(attempt["started_at"], "started_at"))
        if attempt["submitted_at"] is not None:
            attempt["submitted_at"] = format_time(parse_time(attempt["submitted_at"], "submitted_at"))
        for revision in attempt["scores"]:
            revision["scored_at"] = format_time(parse_time(revision["scored_at"], "scored_at"))
    return revised


def validate_ledger(study: dict, ledger: dict) -> None:
    validate_study(study)
    need(isinstance(ledger, dict), "ledger must be an object")
    version = ledger.get("schema_version")
    need(isinstance(version, int) and not isinstance(version, bool) and version == 1, "ledger schema_version must be integer 1")
    need(ledger.get("study_id") == study["id"], "ledger belongs to a different study id")
    need(ledger.get("study_sha256") == study_sha256(study), "ledger study hash differs; use a separate ledger for this study revision")
    attempts = ledger.get("attempts")
    need(isinstance(attempts, list), "ledger.attempts must be an array")
    participants = {x["id"]: x for x in study["participants"]}
    conditions = {x["id"] for x in study["conditions"]}
    tasks = {x["id"]: x for x in study["tasks"]}
    attempt_ids: set[str] = set()
    first_pairs: set[tuple[str, str]] = set()
    unfinished: set[tuple[str, str]] = set()
    for i, attempt in enumerate(attempts):
        where = f"attempts[{i}]"
        need(isinstance(attempt, dict), f"{where} must be an object")
        need("submitted_at" in attempt and "answer" in attempt, f"{where} must include submitted_at and answer, using null before submission")
        aid = attempt.get("id")
        text(aid, f"{where}.id")
        need(aid not in attempt_ids, f"duplicate attempt id: {aid}")
        attempt_ids.add(aid)
        pid, cid, tid = attempt.get("participant_id"), attempt.get("condition_id"), attempt.get("task_id")
        need(isinstance(pid, str) and pid in participants, f"attempt {aid} has unknown participant")
        need(isinstance(cid, str) and cid in conditions, f"attempt {aid} has unknown condition")
        need(isinstance(tid, str) and tid in tasks, f"attempt {aid} has unknown task")
        kind = attempt.get("kind")
        need(isinstance(kind, str) and kind in {"first", "practice", "repeat"}, f"attempt {aid}.kind must be first, practice, or repeat")
        if kind == "first":
            need(cid == participants[pid]["condition_id"], f"first attempt {aid} must use the participant's assigned condition")
            pair = (pid, tid)
            need(pair not in first_pairs, f"participant {pid} has more than one first attempt for task {tid}")
            first_pairs.add(pair)
        started = parse_time(attempt.get("started_at"), f"attempt {aid}.started_at")
        submitted_at = attempt.get("submitted_at")
        answer = attempt.get("answer")
        if submitted_at is None:
            need(answer is None, f"unsubmitted attempt {aid} must have answer null")
            pair = (pid, tid)
            need(pair not in unfinished, f"participant {pid} has overlapping unfinished attempts for task {tid}")
            unfinished.add(pair)
        else:
            submitted = parse_time(submitted_at, f"attempt {aid}.submitted_at")
            need(submitted >= started, f"attempt {aid} submitted before it started")
            need(isinstance(answer, str), f"submitted attempt {aid} answer must be a string, including an empty string")
        score_history = attempt.get("scores")
        need(isinstance(score_history, list), f"attempt {aid}.scores must be an array")
        rubric = {x["id"]: x for x in tasks[tid]["rubric"]}
        for j, revision in enumerate(score_history):
            rwhere = f"attempt {aid}.scores[{j}]"
            need(isinstance(revision, dict), f"{rwhere} must be an object")
            need(submitted_at is not None, f"attempt {aid} must be submitted before scoring")
            text(revision.get("reviewer"), f"{rwhere}.reviewer")
            scored_at = parse_time(revision.get("scored_at"), f"{rwhere}.scored_at")
            need(scored_at >= parse_time(submitted_at, f"attempt {aid}.submitted_at"), f"{rwhere}.scored_at precedes submission")
            items = revision.get("items")
            need(isinstance(items, dict) and set(items) == set(rubric), f"{rwhere}.items must contain exactly the task rubric ids")
            for item_id, points in items.items():
                maximum = rubric[item_id]["max_points"]
                need(isinstance(points, int) and not isinstance(points, bool) and 0 <= points <= maximum, f"{rwhere}.{item_id} must be an integer from 0 to {maximum}")
            text(revision.get("note"), f"{rwhere}.note")


def start_attempt(study: dict, ledger: dict, participant_id: str, condition_id: str, task_id: str, kind: str, started_at: str, attempt_id: str) -> dict:
    validate_ledger(study, ledger)
    need(isinstance(participant_id, str), "participant_id must be a string")
    need(isinstance(condition_id, str), "condition_id must be a string")
    need(isinstance(task_id, str), "task_id must be a string")
    need(isinstance(kind, str), "kind must be a string")
    participants = {x["id"]: x for x in study["participants"]}
    task_ids = {x["id"] for x in study["tasks"]}
    condition_ids = {x["id"] for x in study["conditions"]}
    need(participant_id in participants, f"unknown participant: {participant_id}")
    need(condition_id in condition_ids, f"unknown condition: {condition_id}")
    need(task_id in task_ids, f"unknown task: {task_id}")
    need(kind in {"first", "practice", "repeat"}, "kind must be first, practice, or repeat")
    text(attempt_id, "attempt_id")
    need(not any(a["id"] == attempt_id for a in ledger["attempts"]), f"duplicate attempt id: {attempt_id}")
    if kind == "first":
        need(condition_id == participants[participant_id]["condition_id"], "first attempt condition must match participant assignment")
        need(not any(a["participant_id"] == participant_id and a["task_id"] == task_id and a["kind"] == "first" for a in ledger["attempts"]), f"first attempt already exists for {participant_id}/{task_id}")
    need(not any(a["participant_id"] == participant_id and a["task_id"] == task_id and a["submitted_at"] is None for a in ledger["attempts"]), f"unfinished attempt already exists for {participant_id}/{task_id}")
    timestamp = format_time(parse_time(started_at, "started_at"))
    revised = _normalized_ledger(ledger)
    revised["attempts"].append({"id": attempt_id, "participant_id": participant_id, "condition_id": condition_id, "task_id": task_id, "kind": kind, "started_at": timestamp, "submitted_at": None, "answer": None, "scores": []})
    validate_ledger(study, revised)
    return revised


def submit_answer(study: dict, ledger: dict, attempt_id: str, answer: str, submitted_at: str) -> dict:
    validate_ledger(study, ledger)
    need(isinstance(answer, str), "answer must be text")
    attempt = next((x for x in ledger["attempts"] if x["id"] == attempt_id), None)
    need(attempt is not None, f"unknown attempt id: {attempt_id}")
    need(attempt["submitted_at"] is None, f"attempt {attempt_id} has already been submitted")
    submitted = parse_time(submitted_at, "submitted_at")
    need(submitted >= parse_time(attempt["started_at"], f"attempt {attempt_id}.started_at"), "submitted_at precedes started_at")
    revised = _normalized_ledger(ledger)
    updated = next(x for x in revised["attempts"] if x["id"] == attempt_id)
    updated["submitted_at"] = format_time(submitted)
    updated["answer"] = answer
    validate_ledger(study, revised)
    return revised


def record_score(study: dict, ledger: dict, attempt_id: str, scores: dict, reviewer: str, scored_at: str) -> dict:
    validate_ledger(study, ledger)
    text(reviewer, "reviewer")
    need(isinstance(scores, dict) and set(scores) == {"items", "note"}, "score input must contain exactly items and note")
    text(scores.get("note"), "score note")
    attempt = next((x for x in ledger["attempts"] if x["id"] == attempt_id), None)
    need(attempt is not None, f"unknown attempt id: {attempt_id}")
    need(attempt["submitted_at"] is not None, f"attempt {attempt_id} must be submitted before scoring")
    timestamp = parse_time(scored_at, "scored_at")
    need(timestamp >= parse_time(attempt["submitted_at"], f"attempt {attempt_id}.submitted_at"), "scored_at precedes submission")
    task = next(x for x in study["tasks"] if x["id"] == attempt["task_id"])
    rubric = {x["id"]: x for x in task["rubric"]}
    items = scores.get("items")
    need(isinstance(items, dict) and set(items) == set(rubric), "scores.items must contain exactly the task rubric ids")
    normalized_items = {}
    for item in task["rubric"]:
        points = items[item["id"]]
        maximum = item["max_points"]
        need(isinstance(points, int) and not isinstance(points, bool) and 0 <= points <= maximum, f"score {item['id']} must be an integer from 0 to {maximum}")
        normalized_items[item["id"]] = points
    revised = _normalized_ledger(ledger)
    updated = next(x for x in revised["attempts"] if x["id"] == attempt_id)
    updated["scores"].append({"reviewer": reviewer.strip(), "scored_at": format_time(timestamp), "items": normalized_items, "note": scores["note"].strip()})
    validate_ledger(study, revised)
    return revised


def _max_points(task: dict) -> int:
    return sum(item["max_points"] for item in task["rubric"])


def _active_score(attempt: dict) -> dict | None:
    return attempt["scores"][-1] if attempt["scores"] else None


def summarize(study: dict, ledger: dict) -> dict:
    validate_ledger(study, ledger)
    participants = {x["id"]: x for x in study["participants"]}
    tasks = {x["id"]: x for x in study["tasks"]}
    first = {(a["participant_id"], a["task_id"]): a for a in ledger["attempts"] if a["kind"] == "first"}
    primary_rows = []
    for participant in study["participants"]:
        for task in study["tasks"]:
            attempt = first.get((participant["id"], task["id"]))
            max_points = _max_points(task)
            if attempt is None:
                primary_rows.append({"participant_id": participant["id"], "assigned_condition": participant["condition_id"], "observed_condition": None, "task_id": task["id"], "attempt_id": None, "kind": "first", "status": "not_started", "started_at": None, "submitted_at": None, "duration_seconds": None, "points": None, "max_points": max_points, "normalized_score": None, "reviewer": None, "prior_exposure": False, "answer": None, "score_note": None})
                continue
            submitted_at = attempt["submitted_at"]
            score = _active_score(attempt)
            if submitted_at is None:
                status = "in_progress"
            elif score is None:
                status = "submitted_unscored"
            else:
                status = "scored"
            earlier_exposure = any(
                other["participant_id"] == participant["id"] and other["task_id"] == task["id"] and other["kind"] in {"practice", "repeat"} and parse_time(other["started_at"], "started_at") < parse_time(attempt["started_at"], "started_at")
                for other in ledger["attempts"]
            )
            duration = None if submitted_at is None else (parse_time(submitted_at, "submitted_at") - parse_time(attempt["started_at"], "started_at")).total_seconds()
            points = None if score is None else sum(score["items"].values())
            primary_rows.append({"participant_id": participant["id"], "assigned_condition": participant["condition_id"], "observed_condition": attempt["condition_id"], "task_id": task["id"], "attempt_id": attempt["id"], "kind": "first", "status": status, "started_at": format_time(parse_time(attempt["started_at"], "started_at")), "submitted_at": None if submitted_at is None else format_time(parse_time(submitted_at, "submitted_at")), "duration_seconds": duration, "points": points, "max_points": max_points, "normalized_score": None if score is None else points / max_points, "reviewer": None if score is None else score["reviewer"], "prior_exposure": earlier_exposure, "answer": attempt["answer"], "score_note": None if score is None else score["note"]})
    condition_task = []
    overall = []
    for condition in study["conditions"]:
        condition_rows = [row for row in primary_rows if row["assigned_condition"] == condition["id"]]
        scored_condition = [row["normalized_score"] for row in condition_rows if row["status"] == "scored"]
        overall.append({"condition_id": condition["id"], "scored_observation_count": len(scored_condition), "mean_normalized_score": None if not scored_condition else statistics.mean(scored_condition), "denominator": len(scored_condition), "interpretation": "mean across scored participant-task observations; not a balanced participant-level estimate"})
        for task in study["tasks"]:
            rows = [row for row in condition_rows if row["task_id"] == task["id"]]
            scored = [row["normalized_score"] for row in rows if row["status"] == "scored"]
            durations = [row["duration_seconds"] for row in rows if row["submitted_at"] is not None]
            submitted_count = sum(row["submitted_at"] is not None for row in rows)
            condition_task.append({"condition_id": condition["id"], "task_id": task["id"], "expected_count": len(rows), "started_count": sum(row["status"] != "not_started" for row in rows), "submitted_count": submitted_count, "scored_count": len(scored), "missing_count": sum(row["status"] == "not_started" for row in rows), "unscored_count": sum(row["status"] in {"in_progress", "submitted_unscored"} for row in rows), "mean_normalized_score": None if not scored else statistics.mean(scored), "mean_score_denominator": len(scored), "median_duration_seconds": None if not durations else statistics.median(durations), "median_duration_denominator": len(durations)})
    practice_counts = []
    for condition in study["conditions"]:
        for task in study["tasks"]:
            for kind in ("practice", "repeat"):
                attempts = [a for a in ledger["attempts"] if a["condition_id"] == condition["id"] and a["task_id"] == task["id"] and a["kind"] == kind]
                practice_counts.append({"condition_id": condition["id"], "task_id": task["id"], "kind": kind, "attempt_count": len(attempts), "submitted_count": sum(a["submitted_at"] is not None for a in attempts), "scored_count": sum(bool(a["scores"]) for a in attempts)})
    exposed = [{"participant_id": row["participant_id"], "task_id": row["task_id"], "attempt_id": row["attempt_id"], "assigned_condition": row["assigned_condition"], "prior_attempts": [{"attempt_id": a["id"], "kind": a["kind"], "condition_id": a["condition_id"], "started_at": format_time(parse_time(a["started_at"], "started_at"))} for a in ledger["attempts"] if a["participant_id"] == row["participant_id"] and a["task_id"] == row["task_id"] and a["kind"] in {"practice", "repeat"} and parse_time(a["started_at"], "started_at") < parse_time(row["started_at"], "started_at")]} for row in primary_rows if row["prior_exposure"]]
    cross_condition = [{"attempt_id": a["id"], "participant_id": a["participant_id"], "task_id": a["task_id"], "kind": a["kind"], "assigned_condition": participants[a["participant_id"]]["condition_id"], "observed_condition": a["condition_id"]} for a in ledger["attempts"] if a["condition_id"] != participants[a["participant_id"]]["condition_id"]]
    limitations = ["Observations are descriptive and do not establish causal effects or statistical significance.", "Duration records elapsed time between attempt start and submission; it is not proof of comprehension.", "Primary summaries use first attempts only and include prior-exposed participants with an explicit flag.", "Scores are manual reviewer judgments; the latest revision is active and prior revisions remain in the ledger."]
    if exposed:
        limitations.append("First-attempt results include prior-exposed participants.")
    return {"schema_version": 1, "study_id": study["id"], "study_title": study["title"], "study_sha256": study_sha256(study), "conditions": [{"id": c["id"], "label": c["label"], "artifact": c["artifact"]} for c in study["conditions"]], "primary_rows": primary_rows, "condition_task": condition_task, "condition_overall": overall, "practice_repeat_counts": practice_counts, "prior_exposure": exposed, "cross_condition_attempts": cross_condition, "limitations": limitations}


CSV_FIELDS = ["participant_id", "assigned_condition", "observed_condition", "task_id", "attempt_id", "kind", "status", "started_at", "submitted_at", "duration_seconds", "points", "max_points", "normalized_score", "reviewer", "prior_exposure", "answer", "score_note"]


def export_rows(study: dict, ledger: dict) -> list[dict]:
    summary = summarize(study, ledger)
    rows = [dict((field, row.get(field)) for field in CSV_FIELDS) for row in summary["primary_rows"]]
    task_by_id = {x["id"]: x for x in study["tasks"]}
    participant_by_id = {x["id"]: x for x in study["participants"]}
    for attempt in ledger["attempts"]:
        if attempt["kind"] == "first":
            continue
        task = task_by_id[attempt["task_id"]]
        score = _active_score(attempt)
        duration = None if attempt["submitted_at"] is None else (parse_time(attempt["submitted_at"], "submitted_at") - parse_time(attempt["started_at"], "started_at")).total_seconds()
        points = None if score is None else sum(score["items"].values())
        rows.append({"participant_id": attempt["participant_id"], "assigned_condition": participant_by_id[attempt["participant_id"]]["condition_id"], "observed_condition": attempt["condition_id"], "task_id": attempt["task_id"], "attempt_id": attempt["id"], "kind": attempt["kind"], "status": "in_progress" if attempt["submitted_at"] is None else "submitted_unscored" if score is None else "scored", "started_at": format_time(parse_time(attempt["started_at"], "started_at")), "submitted_at": None if attempt["submitted_at"] is None else format_time(parse_time(attempt["submitted_at"], "submitted_at")), "duration_seconds": duration, "points": points, "max_points": _max_points(task), "normalized_score": None if score is None else points / _max_points(task), "reviewer": None if score is None else score["reviewer"], "prior_exposure": False, "answer": attempt["answer"], "score_note": None if score is None else score["note"]})
    return rows


def _csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + value
    return value


def export_csv(study: dict, ledger: dict) -> str:
    output = io.StringIO(newline="")
    # CR and LF both belong to the dialect terminator so QUOTE_MINIMAL quotes either inside a cell.
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\r\n", extrasaction="raise")
    writer.writeheader()
    for row in export_rows(study, ledger):
        writer.writerow({key: _csv_safe(row[key]) for key in CSV_FIELDS})
    return output.getvalue()
