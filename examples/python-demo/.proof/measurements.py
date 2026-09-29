#!/usr/bin/env python3
# Proof installer-owned runtime.
"""Record self-reported test, coverage, validator, AI review, and scanner measurements for the Proof scorecard.

Test, coverage, validator, and AI review commands run the pull request's own code, and the
scanner counts are produced by this pull request's copy of the converter, so these
numbers are self-reported display metadata. They never change a check's status.

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


REVIEW_SEVERITIES = ("P0", "P1", "P2", "P3")
REVIEW_STATUSES = {"open", "resolved", "accepted", "deferred", "needs-context"}


def from_review_result(path: Path) -> dict[str, Any]:
    """Count one AI reviewer result file (pr-review/pr-review.md) by severity.

    Unresolved blocking mirrors the pr-review blocking rule: a P0 or P1
    finding whose status is not ``resolved``; a missing status counts as open.
    Only counts leave this function, never finding text, paths, or rule names.
    """
    result = json.loads(_read(path))
    findings = result.get("findings") if isinstance(result, dict) else None
    if not isinstance(findings, list):
        raise ValueError(f"{path} is not an AI review result with a findings list")
    counts = dict.fromkeys(REVIEW_SEVERITIES, 0)
    unresolved_blocking = 0
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError(f"{path} has a finding that is not an object")
        severity, status = finding.get("severity"), finding.get("status")
        status = "open" if status is None else status
        if severity not in counts or status not in REVIEW_STATUSES:
            raise ValueError(f"{path} has a finding without an allowed severity and status")
        counts[severity] += 1
        unresolved_blocking += severity in ("P0", "P1") and status != "resolved"
    return {"version": 1, "source": "pull-request-workflow", "review_findings": {
        "total": len(findings), "p0": counts["P0"], "p1": counts["P1"], "p2": counts["P2"], "p3": counts["P3"],
        "unresolved_blocking": unresolved_blocking,
    }}


# Semgrep rule severities onto the shared buckets. Semgrep CE has no critical legacy
# level; INVENTORY, EXPERIMENT, or an unknown value is counted as unrated.
SEMGREP_SEVERITIES = {"CRITICAL": "critical", "ERROR": "high", "HIGH": "high", "WARNING": "medium",
                      "MEDIUM": "medium", "INFO": "low", "LOW": "low"}


def _findings(severities: list[str]) -> dict[str, Any]:
    counts = dict.fromkeys(("critical", "high", "medium", "low", "unrated"), 0)
    for severity in severities:
        counts[severity] += 1
    return {"version": 1, "source": "pull-request-workflow", "findings": {"total": len(severities), **counts}}


# SARIF levels for results whose rule has no numeric security-severity.
SARIF_LEVELS = {"error": "high", "warning": "medium", "note": "low"}


def _security_bucket(score: Any) -> str | None:
    """GitHub code scanning's CVSS bands for a rule's security-severity, or None when absent."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if value >= 9.0:
        return "critical"
    if value >= 7.0:
        return "high"
    if value >= 4.0:
        return "medium"
    return "low" if value > 0 else None


def _sarif_rule(result: dict[str, Any], components: list[dict[str, Any]]) -> dict[str, Any]:
    """The rule a SARIF result refers to, looked up in its own tool component (driver when unnamed)."""
    reference = result.get("rule") if isinstance(result.get("rule"), dict) else {}
    component_reference = reference.get("toolComponent")
    rule_id = result.get("ruleId") or reference.get("id")
    rule_index = reference.get("index", result.get("ruleIndex"))
    if isinstance(component_reference, dict) and type(component_reference.get("index")) is int:
        # SARIF toolComponent indexes point into tool.extensions; the driver is components[0].
        position = component_reference["index"] + 1
        candidates = [components[position]] if 0 < position < len(components) else []
    else:
        candidates = components[:1]
    for component in candidates:
        rules = [rule for rule in (component.get("rules") or []) if isinstance(rule, dict)]
        if type(rule_index) is int and 0 <= rule_index < len(rules):
            return rules[rule_index]
        for rule in rules:
            if rule.get("id") == rule_id:
                return rule
    if not isinstance(component_reference, dict):
        # No component named: older producers put pack rules only in extensions, so search them by ID.
        for component in components[1:]:
            for rule in component.get("rules") or []:
                if isinstance(rule, dict) and rule.get("id") == rule_id:
                    return rule
    return {}


def _suppressed(result: dict[str, Any]) -> bool:
    """A suppression is in force when accepted or when it states no status; rejected or under-review ones are not."""
    suppressions = result.get("suppressions")
    return isinstance(suppressions, list) and any(
        isinstance(item, dict) and item.get("status", "accepted") == "accepted" for item in suppressions)


def from_sarif(paths: list[Path]) -> dict[str, Any]:
    """Count SARIF results (for example CodeQL's, one file per language) by security severity.

    A result's severity comes from its rule's ``security-severity`` property, resolved in the
    result's own tool component; otherwise from the result level, then the rule's default
    level, then SARIF's ``warning`` default. Results with a suppression in force are not
    counted. Counts only: never paths, rule IDs, or messages.
    """
    severities: list[str] = []
    for path in paths:
        report = json.loads(_read(path))
        runs = report.get("runs") if isinstance(report, dict) else None
        if not isinstance(runs, list):
            raise ValueError(f"{path} is not a SARIF report")
        for run in runs:
            tool = run.get("tool") if isinstance(run, dict) else None
            results = run.get("results") if isinstance(run, dict) else None
            if not isinstance(tool, dict) or not isinstance(results, list):
                raise ValueError(f"{path} has a malformed SARIF run")
            components = [component if isinstance(component, dict) else {}
                          for component in [tool.get("driver") or {}, *(tool.get("extensions") or [])]]
            for result in results:
                if not isinstance(result, dict):
                    raise ValueError(f"{path} has a malformed SARIF result")
                if _suppressed(result):
                    continue
                rule = _sarif_rule(result, components)
                default_level = (rule.get("defaultConfiguration") or {}).get("level")
                level = result.get("level") or default_level or "warning"
                bucket = (_security_bucket((rule.get("properties") or {}).get("security-severity"))
                          or SARIF_LEVELS.get(level, "unrated"))
                severities.append(bucket)
    return _findings(severities)


def from_semgrep(path: Path) -> dict[str, Any]:
    """Count a ``semgrep scan --json-output`` report by rule severity; counts only, never paths or messages."""
    report = json.loads(_read(path))
    results = report.get("results") if isinstance(report, dict) else None
    errors = report.get("errors") if isinstance(report, dict) else None
    if not isinstance(results, list) or not isinstance(errors, list):
        raise ValueError(f"{path} is not a Semgrep JSON report")
    # A fatal error can leave targets unscanned, so the counts would understate findings.
    if any(not isinstance(error, dict) or error.get("level") not in ("warn", "info") for error in errors):
        raise ValueError(f"{path} records a Semgrep error; the scan may be incomplete")
    severities = []
    for result in results:
        extra = result.get("extra") if isinstance(result, dict) else None
        if not isinstance(extra, dict):
            raise ValueError(f"{path} has a malformed Semgrep result")
        severity = extra.get("severity")
        severities.append(SEMGREP_SEVERITIES.get(severity.upper() if isinstance(severity, str) else "", "unrated"))
    return _findings(severities)


def from_gitleaks(path: Path) -> dict[str, Any]:
    """Count a gitleaks JSON report; gitleaks does not rate severity, so every finding is unrated."""
    report = json.loads(_read(path))
    if not isinstance(report, list) or any(not isinstance(finding, dict) or "RuleID" not in finding for finding in report):
        raise ValueError(f"{path} is not a gitleaks JSON report")
    return _findings(["unrated"] * len(report))


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
    review_parser = commands.add_parser("review-findings", help="count an AI reviewer result file by severity")
    review_parser.add_argument("result", type=Path)
    semgrep_parser = commands.add_parser("semgrep", help="count a Semgrep JSON report by severity")
    semgrep_parser.add_argument("report", type=Path)
    gitleaks_parser = commands.add_parser("gitleaks", help="count a gitleaks JSON report")
    gitleaks_parser.add_argument("report", type=Path)
    sarif_parser = commands.add_parser("sarif", help="count SARIF reports (for example CodeQL) by security severity")
    sarif_parser.add_argument("reports", nargs="+", type=Path)
    package_parser = commands.add_parser("package", help="bind measurements to this workflow run")
    package_parser.add_argument("--control", required=True, choices=("unit-tests", "changed-code-coverage", "repository-validation",
                                         "documentation-validation", "repository-ground-truth",
                                         "migration-validation", "ai-engineering-review", "ai-qa-review",
                                         "ai-security-review", "ai-repository-standards-review",
                                         "custom-static-analysis", "secret-detection", "deep-sast",
                                         "dependency-vulnerability"))
    package_parser.add_argument("--input", type=Path, required=True)
    package_parser.add_argument("--outcome", required=True)
    package_parser.add_argument("--head-sha", required=True)
    for command in (unittest_parser, junit_parser, cover_parser, review_parser, semgrep_parser, gitleaks_parser, sarif_parser,
                    package_parser):
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
        elif args.command == "review-findings":
            document = from_review_result(args.result)
        elif args.command == "semgrep":
            document = from_semgrep(args.report)
        elif args.command == "gitleaks":
            document = from_gitleaks(args.report)
        elif args.command == "sarif":
            document = from_sarif(args.reports)
        else:
            document = package(args.control, json.loads(_read(args.input)), args.outcome, args.head_sha)
        _write(args.output, document)
    except (OSError, ValueError, TypeError, KeyError, ElementTree.ParseError) as error:
        print(f"proof measurements: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
