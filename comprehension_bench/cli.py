from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .core import StudyError, export_csv, new_ledger, record_score, start_attempt, submit_answer, summarize, validate_ledger, validate_study


def read_json(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StudyError(f"cannot read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StudyError(f"{path} must contain a JSON object")
    return value


def write_atomic(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def load_ledger(study: dict, path: str, *, allow_missing: bool = False) -> dict:
    target = Path(path)
    if allow_missing and not target.exists():
        return new_ledger(study)
    ledger = read_json(path)
    validate_ledger(study, ledger)
    return ledger


def _timestamp(explicit: str | None) -> str:
    return explicit or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _guard_output(path: str, inputs: list[str]) -> None:
    output = Path(path).resolve()
    for input_path in inputs:
        if output == Path(input_path).resolve():
            raise StudyError(f"refusing to overwrite input file {input_path}; choose a different output path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m comprehension_bench", description="Keep study answers, manual scores, and missing data auditable.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a study definition")
    validate.add_argument("study")
    start = commands.add_parser("start", help="record a task attempt")
    start.add_argument("study")
    start.add_argument("--participant", required=True)
    start.add_argument("--condition", required=True)
    start.add_argument("--task", required=True)
    start.add_argument("--kind", choices=("first", "practice", "repeat"), required=True)
    start.add_argument("--at", help="timezone-aware ISO timestamp for imported observations; default is current UTC")
    start.add_argument("--ledger", required=True)
    submit = commands.add_parser("submit", help="record one exact text answer")
    submit.add_argument("study")
    submit.add_argument("--attempt", required=True)
    submit.add_argument("--answer-file", required=True)
    submit.add_argument("--at", help="timezone-aware ISO timestamp for imported observations; default is current UTC")
    submit.add_argument("--ledger", required=True)
    score = commands.add_parser("score", help="append a manual rubric scoring revision")
    score.add_argument("study")
    score.add_argument("--attempt", required=True)
    score.add_argument("--scores", required=True)
    score.add_argument("--reviewer", required=True)
    score.add_argument("--ledger", required=True)
    summary = commands.add_parser("summarize", help="write descriptive, missingness-aware summaries")
    summary.add_argument("study")
    summary.add_argument("--ledger", required=True)
    summary.add_argument("--out", required=True)
    export = commands.add_parser("export", help="write observations as spreadsheet-safe CSV")
    export.add_argument("study")
    export.add_argument("--ledger", required=True)
    export.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        study = read_json(args.study)
        validate_study(study)
        if args.command == "validate":
            print(f"Valid study: {study['id']} ({len(study['participants'])} participants, {len(study['tasks'])} tasks)")
            return 0
        if args.command == "start":
            _guard_output(args.ledger, [args.study])
            ledger = load_ledger(study, args.ledger, allow_missing=True)
            attempt_id = str(uuid.uuid4())
            revised = start_attempt(study, ledger, args.participant, args.condition, args.task, args.kind, _timestamp(args.at), attempt_id)
            write_atomic(args.ledger, json_text(revised))
            print(attempt_id)
            return 0
        if args.command == "submit":
            _guard_output(args.ledger, [args.study, args.answer_file])
            ledger = load_ledger(study, args.ledger)
            try:
                answer = Path(args.answer_file).read_bytes().decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise StudyError(f"cannot read answer file {args.answer_file}: {exc}") from exc
            revised = submit_answer(study, ledger, args.attempt, answer, _timestamp(args.at))
            write_atomic(args.ledger, json_text(revised))
            print(f"Submitted attempt {args.attempt}")
            return 0
        if args.command == "score":
            _guard_output(args.ledger, [args.study, args.scores])
            ledger = load_ledger(study, args.ledger)
            scores = read_json(args.scores)
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            revised = record_score(study, ledger, args.attempt, scores, args.reviewer, timestamp)
            write_atomic(args.ledger, json_text(revised))
            print(f"Scored attempt {args.attempt}; prior score revisions retained")
            return 0
        ledger = load_ledger(study, args.ledger)
        if args.command == "summarize":
            _guard_output(args.out, [args.study, args.ledger])
            write_atomic(args.out, json_text(summarize(study, ledger)))
            return 0
        if args.command == "export":
            _guard_output(args.out, [args.study, args.ledger])
            write_atomic(args.out, export_csv(study, ledger))
            return 0
    except (StudyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
