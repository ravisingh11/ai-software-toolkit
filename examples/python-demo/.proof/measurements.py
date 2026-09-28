#!/usr/bin/env python3
# Proof installer-owned runtime.
"""Record self-reported test and coverage measurements for the Proof scorecard.

Test and coverage commands run the pull request's own code, so these numbers
are self-reported display metadata. They never change a check's status.

A configured command writes a measurements file to ``$PROOF_MEASUREMENTS_FILE``
with one of the converters below (or directly, using the documented format).
The workflow then runs ``package`` to bind the file to its run and head
revision before uploading it as a run-bound artifact.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
MAX_INPUT_BYTES = 50_000_000
UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
UNITTEST_RESULT = re.compile(r"^(OK|FAILED)(?: \(([^)]*)\))?\s*$", re.MULTILINE)


def evaluator() -> Any:
    for path in (HERE / "evaluate.py", HERE.parent / "proof" / "evaluate.py"):
        if path.is_file():
            spec = importlib.util.spec_from_file_location("proof_measurements_evaluator", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    raise ValueError("cannot locate the Proof evaluator")


def _read(path: Path) -> str:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"{path} exceeds {MAX_INPUT_BYTES} bytes")
    return path.read_text(encoding="utf-8", errors="replace")


def _tests(passed: int, failed: int, skipped: int) -> dict[str, Any]:
    return {"version": 1, "source": "pull-request-workflow", "tests": {
        "total": passed + failed + skipped, "passed": passed, "failed": failed, "skipped": skipped,
    }}


def from_unittest_logs(paths: list[Path]) -> dict[str, Any]:
    """Sum ``python -m unittest`` summaries; every log must contain exactly one run."""
    passed = failed = skipped = 0
    for path in paths:
        text = _read(path)
        ran, results = UNITTEST_RAN.findall(text), UNITTEST_RESULT.findall(text)
        if len(ran) != 1 or len(results) != 1:
            raise ValueError(f"{path} must contain exactly one unittest summary")
        counts = {"failures": 0, "errors": 0, "skipped": 0, "expected failures": 0, "unexpected successes": 0}
        for part in filter(None, (item.strip() for item in results[0][1].split(","))):
            key, _, value = part.partition("=")
            if key not in counts or not value.isdigit():
                raise ValueError(f"{path} has an unrecognized unittest summary: {part}")
            counts[key] = int(value)
        total = int(ran[0])
        run_failed = counts["failures"] + counts["errors"] + counts["unexpected successes"]
        # An expected failure is a known-broken test: never report it as passed.
        not_run = counts["skipped"] + counts["expected failures"]
        if (results[0][0] == "OK") != (run_failed == 0) or run_failed + not_run > total:
            raise ValueError(f"{path} unittest summary is inconsistent")
        passed += total - run_failed - not_run
        failed += run_failed
        skipped += not_run
    return _tests(passed, failed, skipped)


def from_junit(paths: list[Path]) -> dict[str, Any]:
    """Count JUnit XML test cases; errors count as failures."""
    passed = failed = skipped = 0
    for path in paths:
        root = ElementTree.fromstring(_read(path))
        for case in root.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failed += 1
            elif case.find("skipped") is not None:
                skipped += 1
            else:
                passed += 1
    return _tests(passed, failed, skipped)


def from_diff_cover(path: Path, threshold: int) -> dict[str, Any]:
    """Convert a ``diff-cover --format json:PATH`` report for changed lines."""
    report = json.loads(_read(path))
    measured, violations = report.get("total_num_lines"), report.get("total_num_violations")
    if type(measured) is not int or type(violations) is not int or not 0 <= violations <= measured:
        raise ValueError(f"{path} is not a diff-cover JSON report")
    return {"version": 1, "source": "pull-request-workflow", "coverage": {
        "measured_lines": measured, "covered_lines": measured - violations, "threshold_percent": threshold,
    }}


def package(control: str, measurements: dict[str, Any], outcome: str, head_sha: str) -> dict[str, Any]:
    status = {"success": "passed", "failure": "failed"}.get(outcome)
    if status is None:
        raise ValueError("only successful or failed command outcomes carry measurements")
    evaluator().validate_measurements(control, measurements, status)
    run_id, repository = os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_REPOSITORY", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if (not run_id.isdigit() or not attempt.isdigit() or int(attempt) < 1 or not repository
            or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None):
        raise ValueError("GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, GITHUB_REPOSITORY, and an exact head SHA are required")
    return {"version": 1, "run_id": int(run_id), "run_attempt": int(attempt), "repository": repository,
            "head_sha": head_sha, "control": control, "measurements": measurements}


def _write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    unittest_parser = commands.add_parser("unittest", help="summarize python -m unittest output logs")
    unittest_parser.add_argument("logs", nargs="+", type=Path)
    junit_parser = commands.add_parser("junit", help="summarize JUnit XML reports")
    junit_parser.add_argument("reports", nargs="+", type=Path)
    cover_parser = commands.add_parser("diff-cover", help="summarize a diff-cover JSON report")
    cover_parser.add_argument("report", type=Path)
    cover_parser.add_argument("--threshold", type=int, required=True)
    package_parser = commands.add_parser("package", help="bind measurements to this workflow run")
    package_parser.add_argument("--control", required=True, choices=("unit-tests", "changed-code-coverage"))
    package_parser.add_argument("--input", type=Path, required=True)
    package_parser.add_argument("--outcome", required=True)
    package_parser.add_argument("--head-sha", required=True)
    for command in (unittest_parser, junit_parser, cover_parser, package_parser):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "unittest":
            document = from_unittest_logs(args.logs)
        elif args.command == "junit":
            document = from_junit(args.reports)
        elif args.command == "diff-cover":
            if not 0 <= args.threshold <= 100:
                raise ValueError("threshold must be between 0 and 100")
            document = from_diff_cover(args.report, args.threshold)
        else:
            document = package(args.control, json.loads(_read(args.input)), args.outcome, args.head_sha)
        _write(args.output, document)
    except (OSError, ValueError, TypeError, KeyError, ElementTree.ParseError) as error:
        print(f"proof measurements: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
