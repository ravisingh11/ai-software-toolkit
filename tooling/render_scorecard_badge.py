#!/usr/bin/env python3
# Proof installer-owned runtime.
"""Validate a Proof scorecard and render a bounded public status site."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


VALID_STATUSES = {"GREEN": "#2da44e", "ORANGE": "#bf8700", "RED": "#cf222e"}
VALID_DECISIONS = {"allow", "block"}
MAX_MEMBER_BYTES = 64_000
MAX_SOURCE_BYTES = 1_000_000
REVISION_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
RFC3339_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)


def _integer(value: Any, field: str, *, positive: bool = False) -> int:
    if type(value) is not int:  # bool is intentionally excluded
        raise ValueError(f"{field} must be an integer")
    if value < (1 if positive else 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{field} must be {qualifier}")
    return value


def _timestamp(value: str, field: str) -> str:
    if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        normalized = parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise ValueError(f"{field} must be an RFC 3339 timestamp") from error
    rendered = normalized.isoformat(
        timespec="microseconds" if normalized.microsecond else "seconds"
    )
    return rendered.replace("+00:00", "Z")


def _repository(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or not REPOSITORY_PATTERN.fullmatch(value):
        raise ValueError("repository must use OWNER/REPOSITORY format")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ValueError("repository must use OWNER/REPOSITORY format")
    return owner, name


def pages_base_url(repository: str) -> str:
    owner, name = _repository(repository)
    owner_domain = owner.lower()
    if name.lower() == f"{owner_domain}.github.io":
        return f"https://{owner_domain}.github.io/"
    return f"https://{owner_domain}.github.io/{name}/"


def _validate_run_url(
    repository: str, run_id: int, run_attempt: int, run_url: str
) -> str:
    _repository(repository)
    if not isinstance(run_url, str):
        raise ValueError("run_url must be an HTTPS GitHub Actions run-attempt URL")
    parsed = urlsplit(run_url)
    expected_path = f"/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("run_url must match the repository, run ID, and run attempt")
    return run_url


def _bounded_source(source_dir: Path) -> tuple[Path, Path]:
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("source directory must be a real directory")
    entries = list(source_dir.iterdir())
    total_bytes = 0
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise ValueError(
                f"source contains a nested, special, or symlinked entry: {entry.name}"
            )
        size = entry.stat().st_size
        if size > MAX_MEMBER_BYTES:
            raise ValueError(
                f"source member exceeds {MAX_MEMBER_BYTES} bytes: {entry.name}"
            )
        total_bytes += size
        if total_bytes > MAX_SOURCE_BYTES:
            raise ValueError(f"source exceeds {MAX_SOURCE_BYTES} aggregate bytes")
    json_files = sorted(source_dir.glob("scorecard-*.json"))
    if len(json_files) != 1:
        raise ValueError("source must contain exactly one scorecard JSON file")
    json_path = json_files[0]
    markdown_path = json_path.with_suffix(".md")
    if not markdown_path.is_file() or markdown_path.is_symlink():
        raise ValueError("scorecard JSON must have one paired Markdown report")
    if {entry.name for entry in entries} != {json_path.name, markdown_path.name}:
        raise ValueError(
            "source must contain only the paired scorecard JSON and Markdown files"
        )
    return json_path, markdown_path


def _counts(document: dict[str, Any], mode: str) -> dict[str, int]:
    value = document.get(mode)
    if not isinstance(value, dict):
        raise ValueError(f"{mode} must be an object")
    passed = _integer(value.get("passed"), f"{mode}.passed")
    total = _integer(value.get("total"), f"{mode}.total")
    if passed > total:
        raise ValueError(f"{mode}.passed cannot exceed {mode}.total")
    return {"passed": passed, "total": total}


def _result_breakdown(document: dict[str, Any]) -> dict[str, Any]:
    """Publish only complete control counts that reconcile with both mode totals."""
    unavailable = {"availability": "unavailable"}
    rows = document.get("controls")
    if not isinstance(rows, list):
        return unavailable
    counts = {mode: dict.fromkeys(("passed", "failed", "blocked", "unverified"), 0)
              for mode in ("enforced", "advisory")}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            return unavailable
        control_id, mode = row.get("id"), row.get("effective_mode")
        if not isinstance(control_id, str) or not control_id or control_id in seen:
            return unavailable
        seen.add(control_id)
        if mode == "not_activated":
            continue
        if not isinstance(mode, str) or mode not in counts:
            return unavailable
        status = row.get("evidence_status")
        if not isinstance(status, str) or status not in {"passed", "failed", "blocked", "no_result"}:
            return unavailable
        counts[mode]["unverified" if status == "no_result" else status] += 1
    for mode, values in counts.items():
        expected = document[mode]
        if values["passed"] != expected["passed"] or sum(values.values()) != expected["total"]:
            return unavailable
    overall = {key: sum(values[key] for values in counts.values()) for key in counts["enforced"]}
    return {"availability": "available", "overall": overall, **counts}


# Public display allowlist: never use artifact-supplied names, reasons, or URLs.
# Kept aligned with the built-in catalog by a regression test.
PUBLIC_CONTROLS = (
    ('repository-validation', 'Repository Validation', 'Validate repository-owned contracts and configuration', 'Build & quality'),
    ('documentation-validation', 'Documentation Validation', 'Validate documentation structure, links, and declared targets', 'Build & quality'),
    ('repository-ground-truth', 'Repository Ground Truth', 'Validate declared repository architecture and engineering documents', 'Build & quality'),
    ('change-scope', 'PR Size', 'Detect oversized or unexpectedly broad changes', 'Build & quality'),
    ('pr-metadata', 'PR Metadata', 'Validate pull-request title and body requirements against mutable PR state', 'Build & quality'),
    ('format-and-lint', 'Format and Lint', 'Verify repository formatting and lint rules with the repository-owned command', 'Build & quality'),
    ('migration-validation', 'Migration Validation', 'Validate repository-specific database and data migration safety', 'Build & quality'),
    ('build', 'Build', 'Detect compilation, packaging, and build-time regressions', 'Build & quality'),
    ('unit-tests', 'Unit Tests', 'Detect functional regressions in changed behavior', 'Build & quality'),
    ('functional-qa', 'Functional QA', 'Exercise the running application as a user to detect functional regressions in changed behavior', 'AI & QA'),
    ('changed-code-coverage', 'Changed Code Coverage', 'Measure test coverage for changed code', 'Build & quality'),
    ('custom-static-analysis', 'Custom Static Analysis', 'Run repository and organization-specific static rules', 'Build & quality'),
    ('secret-detection', 'Secret Detection', 'Detect credentials and authentication material in source history', 'Security & dependencies'),
    ('deep-sast', 'Deep SAST', 'Detect security vulnerabilities through semantic source analysis', 'Security & dependencies'),
    ('dependency-change-review', 'Dependency Change Review', 'Review security and license risk introduced by dependency changes', 'Security & dependencies'),
    ('platform-secret-protection', 'Platform Secret Protection', 'Verify platform secret scanning and push protection', 'Security & dependencies'),
    ('dependency-remediation', 'Dependency Remediation', 'Verify automated dependency security remediation is configured', 'Security & dependencies'),
    ('artifact-provenance', 'Artifact Provenance', 'Attest where and how a release artifact was built', 'Release & runtime'),
    ('static-quality', 'Static Quality', 'Evaluate maintainability, reliability, and static quality gates', 'Build & quality'),
    ('dependency-vulnerability', 'Dependency Vulnerability', 'Detect known vulnerabilities in resolved dependencies', 'Security & dependencies'),
    ('license-compliance', 'License Compliance', 'Evaluate dependency licenses against repository policy', 'Security & dependencies'),
    ('ai-engineering-review', 'AI Engineering Review', 'Review correctness, architecture, maintainability, and regression risk', 'AI & QA'),
    ('ai-qa-review', 'AI QA Review', 'Review tests, edge cases, failure paths, and assertions', 'AI & QA'),
    ('ai-security-review', 'AI Security Review', 'Review authentication, isolation, injection, secrets, and privilege risks', 'AI & QA'),
    ('ai-repository-standards-review', 'AI Repository Standards Review', 'Review changes against repository-owned engineering ground truth', 'AI & QA'),
    ('runtime-soak', 'Runtime Soak', 'Detect runtime degradation, leaks, and performance drift over time', 'Release & runtime'),
    ('container-vulnerability', 'Container Vulnerability', 'Detect vulnerabilities in container images', 'Release & runtime'),
    ('iac-misconfiguration', 'IaC Misconfiguration', 'Detect insecure infrastructure-as-code configuration', 'Security & dependencies'),
    ('artifact-sbom', 'Artifact SBOM', 'Record the software components contained in an artifact', 'Release & runtime'),
    ('artifact-vulnerability', 'Artifact Vulnerability', 'Detect vulnerabilities in a built release artifact', 'Release & runtime'),
    ('deployment-policy', 'Deployment Policy', 'Verify deployment approval and environment policy', 'Release & runtime'),
    ('dynamic-application-security', 'Dynamic Application Security', 'Detect vulnerabilities in a running application', 'Release & runtime'),
    ('runtime-assurance', 'Runtime Assurance', 'Verify runtime security and operational safeguards', 'Release & runtime'),
 )
_CONTROL_RESULTS = {
    "passed": ("Passed", "good"), "failed": ("Failed", "danger"),
    "blocked": ("Blocked", "caution"), "no_result": ("Unverified", "neutral"),
    "not_activated": ("Not activated", "neutral"),
    "not_reported": ("Not reported", "neutral"),
}
_CONTROL_MODES = {"enforced": "Enforced", "advisory": "Advisory",
                  "not_activated": "Not activated", "not_reported": "Not reported"}


_REVIEW_FINDING_METRICS = 'Findings by severity (P0 to P3); unresolved P0/P1 findings'


# Check-specific assessment criteria; these describe the contract, not claimed measurements.
_CHECK_ASSESSMENTS = {'repository-validation': ('Installed Proof contracts',
                           'Installed runtime files, Semgrep self-test fixtures, schemas, and the control catalog, profiles, providers, and policy',
                           'Every contract group validates; the first failure stops the run',
                           'Contract groups passed; failed; not run'),
 'documentation-validation': ('Documentation integrity',
                              'Local Markdown links, declared documentation targets, and required documentation updates for changed files',
                              'No broken local links and every documentation mapping is satisfied',
                              'Markdown files; local links checked; broken links; mapping failures'),
 'repository-ground-truth': ('Declared engineering ground truth',
                             'Documents declared in .proof/ground-truth-ai.yaml, such as agent instructions and architecture, testing, security, and contribution guides',
                             'Every declared document exists in the repository; document contents are not assessed',
                             'Documents declared; found; missing'),
 'change-scope': ('Change size',
                  'Counted files, added lines, changed lines, and maximum additions per file',
                  'Each measurement is within its configured limit',
                  'Files and LOC are shown below'),
 'pr-metadata': ('PR title and description',
                 'Configured title pattern and required description sections; title and description text are not published',
                 'Title matches the configured pattern and every required section is present',
                 'Whether the title matches; required sections present and missing'),
 'format-and-lint': ('Formatting and lint rules',
                     'Repository-configured formatter and lint command',
                     'Configured command completes successfully',
                     'Files checked; errors; warnings'),
 'migration-validation': ('Migration safety',
                          'Repository-specific migration checks, or declared absence of migrations',
                          'Repository migration validator succeeds',
                          'Migrations checked; failed'),
 'build': ('Build and packaging',
           'Repository-configured build command',
           'Build command completes successfully',
           'Artifacts produced; build errors'),
 'unit-tests': ('Automated unit tests',
                'Repository-configured test command and selected test suites',
                'Test command completes successfully',
                'Tests passed; failed; skipped; total'),
 'functional-qa': ('Application behavior',
                   'Configured user journeys and assertions against a running application',
                   'Executed QA scenarios meet the advisory scenario expectations',
                   'Scenarios passed; failed; blocked; skipped'),
 'changed-code-coverage': ('Coverage of changed code',
                           'Executable changed lines compared with repository coverage policy',
                           'Changed-line coverage meets the repository-configured threshold',
                           'Covered lines; uncovered lines; coverage percentage; configured threshold'),
 'custom-static-analysis': ('Custom static rules',
                            'Repository and organization-specific analysis rules',
                            'Configured analyzer completes without policy-blocking findings',
                            'Findings by severity'),
 'secret-detection': ('Secrets in source history',
                      'Credential patterns in the configured scan scope',
                      'Scanner reports no policy-blocking secret findings',
                      'Secret findings'),
 'deep-sast': ('Semantic security analysis',
               'Data flow and security queries for configured languages',
               'Selected security analysis satisfies its configured policy',
               'Queries run; vulnerabilities by severity'),
 'dependency-change-review': ('Dependency changes',
                              'New or changed dependencies and associated security/license risk',
                              'Changes satisfy the configured dependency review policy',
                              'Dependencies changed; new vulnerabilities; license violations'),
 'platform-secret-protection': ('Platform protection settings',
                                'Secret scanning and push protection capability checks',
                                'Required platform protections are enabled and verified',
                                'Secret scanning enabled; push protection enabled'),
 'dependency-remediation': ('Remediation configuration',
                            'Automated dependency security update configuration',
                            'Required dependency remediation automation is configured',
                            'Security updates enabled; configuration checks'),
 'artifact-provenance': ('Build provenance',
                         'Attestation tying a release artifact to its build source',
                         'Artifact provenance satisfies the release policy',
                         'Artifacts attested; verification failures'),
 'static-quality': ('Static quality gate',
                    'Maintainability, reliability, and quality rules from the selected provider',
                    'Provider quality gate satisfies its configured policy',
                    'Quality-gate conditions; bugs; code smells; duplication'),
 'dependency-vulnerability': ('Resolved dependency vulnerabilities',
                              'Known vulnerabilities in the resolved dependency graph',
                              'Findings satisfy the configured severity and exception policy',
                              'Dependencies scanned; critical/high/medium/low findings'),
 'license-compliance': ('Dependency license policy',
                        'Detected dependency licenses and configured allow/deny rules',
                        'Licenses satisfy the configured compliance policy',
                        'Licenses evaluated; violations; unknown licenses'),
 'ai-engineering-review': ('Engineering review dimensions',
                           'Correctness, architecture, maintainability, and regression risk',
                           'Advisory review completes with a documented disposition',
                           _REVIEW_FINDING_METRICS),
 'ai-qa-review': ('Test adequacy review',
                  'Test assertions, edge cases, failure paths, and coverage gaps',
                  'Advisory review completes with a documented disposition',
                  _REVIEW_FINDING_METRICS),
 'ai-security-review': ('Security review dimensions',
                        'Authentication, isolation, injection, secrets, and privilege boundaries',
                        'Advisory review completes with a documented disposition',
                        _REVIEW_FINDING_METRICS),
 'ai-repository-standards-review': ('Repository standards review',
                                    'Changes compared with repository-owned engineering requirements',
                                    'Advisory review completes with a documented disposition',
                                    _REVIEW_FINDING_METRICS),
 'runtime-soak': ('Sustained runtime behavior',
                  'Degradation, resource leaks, errors, and performance drift over time',
                  'Observed runtime stays within configured environment limits',
                  'Test duration; error rate; latency; resource growth'),
 'container-vulnerability': ('Container image security',
                             'Vulnerabilities in the selected container image',
                             'Image findings satisfy the configured vulnerability policy',
                             'Images scanned; vulnerabilities by severity'),
 'iac-misconfiguration': ('Infrastructure configuration',
                          'Security rules for infrastructure-as-code resources',
                          'Configuration satisfies the selected infrastructure policy',
                          'Resources scanned; misconfigurations by severity'),
 'artifact-sbom': ('Software component inventory',
                   'Software components recorded in an artifact SBOM',
                   'SBOM satisfies artifact inventory requirements',
                   'Components recorded; missing metadata'),
 'artifact-vulnerability': ('Release artifact security',
                            'Vulnerabilities in a built release artifact',
                            'Artifact findings satisfy the configured vulnerability policy',
                            'Artifacts scanned; vulnerabilities by severity'),
 'deployment-policy': ('Deployment authorization',
                       'Approval and environment-policy evidence',
                       'Deployment satisfies required environment policy',
                       'Approvals verified; policy violations'),
 'dynamic-application-security': ('Running application security',
                                  'Security checks against a deployed application',
                                  'Runtime security findings satisfy configured scan policy',
                                  'Endpoints scanned; vulnerabilities by severity'),
 'runtime-assurance': ('Operational safeguards',
                       'Runtime security and operational control evidence',
                       'Safeguards satisfy the configured environment policy',
                       'Safeguards verified; policy violations')}


def _execution_details(row: dict[str, Any]) -> dict[str, Any]:
    """Validate optional timing facts again at the public projection boundary."""
    unavailable = {"availability": "unavailable"}
    result = row.get("authoritative_result")
    value = result.get("check_execution") if isinstance(result, dict) else None
    conclusions = {"success": "passed", "failure": "failed", "cancelled": "blocked",
                   "timed_out": "blocked", "action_required": "blocked", "stale": "blocked",
                   "neutral": "no_result", "skipped": "no_result"}
    if (not isinstance(value, dict)
            or set(value) != {"version", "started_at", "completed_at", "duration_seconds", "conclusion"}
            or type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["conclusion"], str)
            or conclusions.get(value["conclusion"]) != row.get("evidence_status")
            or ("no_result" if result.get("status") == "not_run" else result.get("status")) != row.get("evidence_status")
            or value["conclusion"] not in conclusions
            or type(value["duration_seconds"]) is not int
            or not 0 <= value["duration_seconds"] <= 2**53 - 1):
        return unavailable
    try:
        for key in ("started_at", "completed_at"):
            timestamp = value[key]
            if not isinstance(timestamp, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", timestamp) is None:
                return unavailable
            if timestamp[-1:] != "Z" and (int(timestamp[-5:-3]) > 23 or int(timestamp[-2:]) > 59):
                return unavailable
        start = _timestamp(value["started_at"], "started_at")
        end = _timestamp(value["completed_at"], "completed_at")
        elapsed = (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
        if elapsed < 0 or int(elapsed) != value["duration_seconds"]:
            return unavailable
    except (ValueError, TypeError, OverflowError):
        return unavailable
    return {"availability": "available", "started_at": start, "completed_at": end,
            "duration_seconds": value["duration_seconds"], "conclusion": value["conclusion"]}


_SEVERITIES = ("critical", "high", "medium", "low")
_FINDING_FIELDS = ("total", *_SEVERITIES, "unrated")
_MEASURED_FIELDS = {"unit-tests": ("tests", ("total", "passed", "failed", "skipped")),
                    "changed-code-coverage": ("coverage", ("measured_lines", "covered_lines", "threshold_percent")),
                    "repository-validation": ("contracts", ("total", "passed", "failed", "not_run")),
                    "documentation-validation": ("documentation", ("markdown_files", "links_checked", "broken_links", "mapping_failures")),
                    "repository-ground-truth": ("documents", ("declared", "found", "missing")),
                    "migration-validation": ("migrations", ("checked", "failed")),
                    **{control_id: ("review_findings", ("total", "p0", "p1", "p2", "p3", "unresolved_blocking"))
                       for control_id in ("ai-engineering-review", "ai-qa-review", "ai-security-review",
                                          "ai-repository-standards-review")},
                    **{control_id: ("findings", _FINDING_FIELDS) for control_id in ("custom-static-analysis", "secret-detection")}}


def _measurements_consistent(kind: str, numbers: dict[str, int], status: str) -> bool:
    """Mirror the evaluator's arithmetic and status rules for each measurement kind."""
    passed = status == "passed"
    if kind == "tests":
        return (numbers["total"] > 0 and numbers["total"] == numbers["passed"] + numbers["failed"] + numbers["skipped"]
                and not (passed and numbers["failed"]))
    if kind == "coverage":
        below = numbers["covered_lines"] * 100 < numbers["threshold_percent"] * numbers["measured_lines"]
        return (numbers["covered_lines"] <= numbers["measured_lines"] and numbers["threshold_percent"] <= 100
                and not (passed and below))
    if kind == "contracts":
        clean = numbers["failed"] == 0 and numbers["not_run"] == 0
        return (numbers["total"] > 0 and numbers["total"] == numbers["passed"] + numbers["failed"] + numbers["not_run"]
                and passed == clean and (passed or numbers["failed"] > 0))
    if kind == "documentation":
        return (numbers["broken_links"] <= numbers["links_checked"]
                and passed == (numbers["broken_links"] + numbers["mapping_failures"] == 0))
    if kind == "migrations":
        return numbers["failed"] <= numbers["checked"] and not (passed and numbers["failed"])
    if kind == "review_findings":
        blocking = numbers["p0"] + numbers["p1"]
        return numbers["total"] == blocking + numbers["p2"] + numbers["p3"] and numbers["unresolved_blocking"] <= blocking
    if kind == "findings":
        # Arithmetic only: a scan may pass with findings under its own threshold.
        return numbers["total"] == sum(numbers[key] for key in _FINDING_FIELDS[1:])
    return numbers["declared"] == numbers["found"] + numbers["missing"] and passed == (numbers["missing"] == 0)


def _measurements(control_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Re-validate optional self-reported measurements; never trust them for status."""
    unavailable = {"availability": "unavailable"}
    spec = _MEASURED_FIELDS.get(control_id)
    result = row.get("authoritative_result")
    value = result.get("measurements") if isinstance(result, dict) else None
    status = row.get("evidence_status")
    if spec is None or status not in ("passed", "failed"):
        return unavailable
    kind, fields = spec
    producer = result.get("producer") if isinstance(result, dict) else None
    if kind == "review_findings" and isinstance(producer, str) and producer.startswith("GitHub Review: "):
        # A native GitHub review posts findings as comments; there is no result file to count.
        return {"availability": "unavailable", "reason": "review_comments"}
    if not isinstance(value, dict):
        return unavailable
    numbers = value.get(kind)
    if (set(value) != {"version", "source", kind} or type(value.get("version")) is not int or value["version"] != 1
            or value.get("source") != "pull-request-workflow" or result.get("status") != status
            or not isinstance(numbers, dict) or set(numbers) != set(fields)
            or any(type(numbers[key]) is not int or not 0 <= numbers[key] <= 2**53 - 1 for key in fields)
            or not _measurements_consistent(kind, numbers, status)):
        return unavailable
    return {"availability": "available", "source": "pull-request-workflow", kind: {key: numbers[key] for key in fields}}


_SELF_REPORTED_NOTE = "Self-reported by the pull request's own workflow run; not independently verified and never used for the result."
_AI_REVIEW_NOTE = ("Counted from the AI reviewer's result file in the pull request's own workflow run. The findings are "
                   "the AI provider's judgment, not independently verified, and never used for the result; AI review is advisory-only.")


def _measurement_note(measurements: dict[str, Any]) -> str:
    return _AI_REVIEW_NOTE if "review_findings" in measurements else _SELF_REPORTED_NOTE


def _measurement_summary(measurements: dict[str, Any]) -> str | None:
    if measurements["availability"] != "available":
        return None
    if "tests" in measurements:
        tests = measurements["tests"]
        return (f'{tests["passed"]:,} passed · {tests["failed"]:,} failed · {tests["skipped"]:,} skipped '
                f'({tests["total"]:,} tests)')
    if "contracts" in measurements:
        counts = measurements["contracts"]
        return (f'{counts["passed"]:,} passed · {counts["failed"]:,} failed · {counts["not_run"]:,} not run '
                f'({counts["total"]:,} contract groups)')
    if "documentation" in measurements:
        counts = measurements["documentation"]
        return (f'{counts["markdown_files"]:,} Markdown files · {counts["links_checked"]:,} local links checked · '
                f'{counts["broken_links"]:,} broken · {counts["mapping_failures"]:,} documentation mapping failures')
    if "documents" in measurements:
        counts = measurements["documents"]
        return (f'{counts["found"]:,} of {counts["declared"]:,} declared documents found · '
                f'{counts["missing"]:,} missing')
    if "review_findings" in measurements:
        counts = measurements["review_findings"]
        if not counts["total"]:
            return "No findings reported by the AI reviewer"
        noun = "finding" if counts["total"] == 1 else "findings"
        return (f'{counts["total"]:,} {noun}: {counts["p0"]:,} P0 · {counts["p1"]:,} P1 · {counts["p2"]:,} P2 · '
                f'{counts["p3"]:,} P3 · {counts["unresolved_blocking"]:,} unresolved P0/P1')
    if "migrations" in measurements:
        counts = measurements["migrations"]
        if not counts["checked"]:
            return "No migrations found to check"
        return f'{counts["checked"]:,} migrations checked · {counts["failed"]:,} failed'
    if "findings" in measurements:
        counts = measurements["findings"]
        if not counts["total"]:
            return "No findings reported"
        if not any(counts[key] for key in _SEVERITIES):
            plural = "s" if counts["total"] != 1 else ""
            return f'{counts["total"]:,} finding{plural} · severity not rated by the scanner'
        summary = " · ".join(f"{counts[key]:,} {key}" for key in _SEVERITIES)
        return summary + (f' · {counts["unrated"]:,} unrated' if counts["unrated"] else "")
    coverage = measurements["coverage"]
    measured, covered = coverage["measured_lines"], coverage["covered_lines"]
    if not measured:
        return f'No measurable changed lines · target {coverage["threshold_percent"]}%'
    percent = int(covered * 1000 / measured) / 10  # floor to one decimal; never round up to a target
    return f'{covered:,} of {measured:,} changed lines covered ({percent:.1f}%) · target {coverage["threshold_percent"]}%'


_PR_METADATA_NOTE = ("Evaluated by the trusted base-branch PR metadata validator. "
                     "The title, description, and section names are not published.")


def _pr_metadata_detail(control_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Re-validate trusted PR metadata counts; mirrors evaluate.validate_pr_metadata."""
    unavailable = {"availability": "unavailable"}
    result = row.get("authoritative_result")
    value = result.get("pr_metadata") if isinstance(result, dict) else None
    status = row.get("evidence_status")
    provider = row.get("authoritative_provider")
    if (control_id != "pr-metadata" or not isinstance(value, dict) or status not in ("passed", "failed")
            or not isinstance(provider, dict) or provider.get("id") != "repository-pr-metadata"
            or result.get("status") != status
            or set(value) != {"version", "title_matches", "required_sections", "missing_sections"}
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["title_matches"]) is not bool):
        return unavailable
    required, missing = value["required_sections"], value["missing_sections"]
    if (type(required) is not int or type(missing) is not int or not 0 <= missing <= required <= 20
            or (value["title_matches"] and missing == 0) != (status == "passed")):
        return unavailable
    return {"availability": "available", "title_matches": value["title_matches"],
            "required_sections": required, "missing_sections": missing}


def _pr_metadata_summary(detail: dict[str, Any]) -> str | None:
    if detail["availability"] != "available":
        return None
    title = "Title matches" if detail["title_matches"] else "Title does not match"
    required = detail["required_sections"]
    if not required:
        return f"{title} the required format · No required sections configured"
    noun = "section" if required == 1 else "sections"
    return f"{title} the required format · {required - detail['missing_sections']:,} of {required:,} required {noun} present"


def _control_details(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Project enum-only results for known controls; fail closed on bad totals."""
    consistent = _result_breakdown(document)["availability"] == "available"
    rows = {row["id"]: row for row in document["controls"]} if consistent else {}
    details = []
    for control_id, name, purpose, group in PUBLIC_CONTROLS:
        row = rows.get(control_id, {})
        mode, status = row.get("effective_mode"), row.get("evidence_status")
        valid = (mode in ("enforced", "advisory") and status in ("passed", "failed", "blocked", "no_result")) or (mode == status == "not_activated")
        # Only the allowlisted pull-request subject is published; anything else stays plain not activated.
        separate = (valid and mode == "not_activated" and row.get("inactive_reason") == "other_subject"
                    and row.get("evidence_subject") == "pull-request")
        details.append({"id": control_id, "name": name, "purpose": purpose, "group": group,
                        "mode": mode if valid else "not_reported",
                        "status": status if valid else "not_reported",
                        "separate_subject": "pull-request" if separate else None,
                        "execution": _execution_details(row) if valid else {"availability": "unavailable"},
                        "measurements": _measurements(control_id, row) if valid else {"availability": "unavailable"},
                        "detail": _pr_metadata_detail(control_id, row) if valid else {"availability": "unavailable"}})
    return details


_SEPARATE_RESULT = ("Checked on the PR", "neutral")
_SEPARATE_NOTE = ("Policy activates this check on the pull request itself, because a title or description edit does not "
                  "create a new commit. This snapshot did not include a pull-request result, so the check is excluded "
                  "from these totals. See the pull request's PR Metadata check.")


def _result_label(row: dict[str, Any]) -> tuple[str, str]:
    return _SEPARATE_RESULT if row.get("separate_subject") else _CONTROL_RESULTS[row["status"]]


def _controls_markdown(controls: list[dict[str, Any]]) -> str:
    lines = ["## Individual checks", "", "Every built-in catalog check is listed. Not reported means this snapshot has no validated row; it does not imply disabled or passed.", "",
             "| Check | ID | Mode | Result | Purpose |", "| --- | --- | --- | --- | --- |"]
    for row in controls:
        lines.append(f"| {row['name']} | `{row['id']}` | {_CONTROL_MODES[row['mode']]} | {_result_label(row)[0]} | {row['purpose']} |")
    measured = [(row["name"], _measurement_summary(row["measurements"]), row["measurements"]) for row in controls]
    measured = [(name, summary, values) for name, summary, values in measured if summary]
    if measured:
        lines += ["", "### Self-reported measurements", "", _SELF_REPORTED_NOTE, ""]
        lines += [f"- {name}: {summary}" + (" (AI review, advisory-only)" if "review_findings" in values else "")
                  for name, summary, values in measured]
        if any("review_findings" in values for *_, values in measured):
            lines += ["", _AI_REVIEW_NOTE]
    trusted = [(row["name"], _pr_metadata_summary(row["detail"])) for row in controls]
    trusted = [(name, summary) for name, summary in trusted if summary]
    if trusted:
        lines += ["", "### PR metadata", "", _PR_METADATA_NOTE, ""]
        lines += [f"- {name}: {summary}" for name, summary in trusted]
    return "\n".join(lines)


def _duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:,}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"


def _utc_label(timestamp: str) -> str:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return parsed.strftime("%d %b %Y · %H:%M:%S UTC")


_ATTENTION_STATUSES = ("failed", "blocked", "no_result")
_INACTIVE_STATUSES = ("not_activated", "not_reported")


def _check_target(control_id: str) -> str:
    return "size-title" if control_id == "change-scope" else f"check-{control_id}"


def _attention_html(controls: list[dict[str, Any]], breakdown: dict[str, Any]) -> str:
    """List active checks without a passing result, most severe first."""
    flagged = sorted((row for row in controls if row["status"] in _ATTENTION_STATUSES),
                     key=lambda row: _ATTENTION_STATUSES.index(row["status"]))
    unnamed = 0
    if breakdown["availability"] == "available":
        overall = breakdown["overall"]
        unnamed = max(0, overall["failed"] + overall["blocked"] + overall["unverified"] - len(flagged))
    if not flagged and not unnamed:
        return ""
    items = []
    for row in flagged:
        label, tone = _CONTROL_RESULTS[row["status"]]
        name = html.escape(row["name"])
        items.append(f'<li><span class="size-result {tone}">{label}</span> <a href="#{_check_target(row["id"])}">{name}</a> <span class="attention-mode">{_CONTROL_MODES[row["mode"]]}</span></li>')
    if unnamed:
        plural = "s" if unnamed != 1 else ""
        items.append(f'<li class="attention-private">{unnamed} custom control{plural} without a passing result. Custom control names are not published.</li>')
    return '<section class="attention" aria-labelledby="attention-title"><h2 id="attention-title">Needs attention</h2><ul>' + ''.join(items) + '</ul></section>'


# Repository-owned commands whose only portable signal is their exit status.
_EXIT_STATUS_ONLY = {"build", "format-and-lint"}
# Scanners whose finding counts live in the provider's own service or check, not in this report.
_COUNTS_ELSEWHERE = {
    "deep-sast": ("Finding counts are not collected for this check. CodeQL publishes its findings to GitHub code scanning "
                  "(the repository's Security tab), and Snyk Code and Semgrep App keep theirs in their own reports; "
                  "open those for vulnerabilities by severity."),
    "static-quality": ("Only the quality-gate result is reported. SonarQube keeps quality-gate conditions, bugs, code smells, "
                       "and duplication on the SonarQube server; open the project there for them."),
    "dependency-change-review": ("Only the overall result is reported. GitHub Dependency Review writes changed dependencies, "
                                 "new vulnerabilities, and license violations to its own job summary; open the pull "
                                 "request's Dependency Review check for them."),
    "dependency-vulnerability": ("Only the overall result is reported. The Snyk Open Source and FOSSA adapters do not yet "
                                 "export finding counts; open the pull request's provider check or the provider project "
                                 "for findings by severity."),
    "license-compliance": ("Only the overall result is reported. The FOSSA adapter does not yet export license counts; "
                           "open the pull request's FOSSA check or the FOSSA project for them."),
}


def _counts_gap(metrics: str, control_id: str = "", measurements: dict[str, Any] | None = None) -> str:
    """Explain, in a sentence, which counts this check type could report but did not."""
    if (measurements or {}).get("reason") == "review_comments":
        return ("Only the review state was reported. This reviewer posts its findings as pull request review comments, "
                "which this report does not count; open the pull request's reviews to read them.")
    if _MEASURED_FIELDS.get(control_id, ("",))[0] == "review_findings":
        return ("Only the overall result was reported. Finding counts appear only when an AI PR Review adapter packages "
                "its result file for this run; a native GitHub review posts findings as review comments instead. "
                "Open the source report for the review output.")
    if control_id in _COUNTS_ELSEWHERE:
        return _COUNTS_ELSEWHERE[control_id]
    if control_id in _EXIT_STATUS_ONLY:
        return ("Only the command's exit status is reported. This repository supplies the command, so counts such as "
                f"{metrics[:1].lower() + metrics[1:].replace('; ', ', ')} depend on its tools; open the source report for their output.")
    fields = ", ".join(part.strip() for part in metrics.split(";"))
    return f"Only the overall result was reported. This report does not include {fields[:1].lower() + fields[1:]}."


def _inactive_intro(inactive: list[tuple[str, str]]) -> str:
    # Not activated is a known exclusion; not reported means the row is missing, so
    # its relationship to the aggregate totals is unknown and must not be asserted.
    statuses = {status for status, _ in inactive}
    parts = []
    if "separate" in statuses:
        parts.append("Checks marked Checked on the PR run against the pull request, not this commit, and are excluded from these totals.")
    if "not_activated" in statuses:
        parts.append("Not activated checks are excluded from the active-control totals.")
    if "not_reported" in statuses:
        parts.append("Not reported checks have no validated row in this snapshot; whether they count toward the totals is unknown.")
    return " ".join(parts)


def _count_reconciliation(metadata: dict[str, Any]) -> str:
    """Explain how the aggregate totals relate to the listed built-in checks."""
    controls = metadata["controls"]
    listed = len(controls)
    if metadata["result_breakdown"]["availability"] != "available":
        return (f"Individual results could not be matched to these totals for this snapshot, so the "
                f"{listed} built-in checks below are shown as not reported.")
    active = sum(row["status"] in _ATTENTION_STATUSES + ("passed",) for row in controls)
    separate = sum(bool(row.get("separate_subject")) for row in controls)
    inactive = sum(row["status"] == "not_activated" for row in controls) - separate
    missing = sum(row["status"] == "not_reported" for row in controls)
    custom = metadata["total"] - active

    def plural(count: int, noun: str) -> str:
        return f"{count} {noun}{'' if count == 1 else 's'}"

    parts = [f"The totals count {plural(metadata['total'], 'active check')}."]
    def verb(count: int, singular: str, plural_form: str) -> str:
        return f"{count} {singular if count == 1 else plural_form}"

    breakdown = [verb(active, "is active", "are active")]
    if separate:
        breakdown.append(verb(separate, "is checked on the pull request", "are checked on the pull request"))
    if inactive:
        breakdown.append(verb(inactive, "is not activated", "are not activated"))
    if missing:
        breakdown.append(verb(missing, "is not reported", "are not reported"))
    joined = breakdown[0] if len(breakdown) == 1 else ", ".join(breakdown[:-1]) + " and " + breakdown[-1]
    parts.append(f"Of the {listed} built-in checks listed below, {joined}.")
    if separate or inactive or missing:
        parts.append("Only active checks count toward the totals.")
    if custom > 0:
        parts.append(f"{plural(custom, 'custom check')} also {'counts' if custom == 1 else 'count'} but "
                     f"{'is' if custom == 1 else 'are'} not listed by name.")
    return " ".join(parts)


def _controls_html(controls: list[dict[str, Any]], run_url: str, scope: dict[str, Any]) -> str:
    groups = []
    active_details = []
    inactive_details = []
    for group in ("Build & quality", "Security & dependencies", "AI & QA", "Release & runtime"):
        rows = []
        for row in controls:
            if row["group"] != group:
                continue
            label, tone = _result_label(row)
            safe = {key: html.escape(value, quote=True) for key, value in row.items() if isinstance(value, str)}
            note = {"not_reported": "No validated row in this snapshot. Activation and outcome are unknown.",
                    "not_activated": "Not activated for this evaluation. Excluded from active-control totals.",
                    "no_result": "No usable evidence was available. This is not a passing result.",
                    "passed": "",
                    "failed": "The producer reported a failure.",
                    "blocked": "The producer reported a blocker."}[row["status"]]
            if row.get("separate_subject"):
                note = _SEPARATE_NOTE
            evidence = '' if row["status"] in _INACTIVE_STATUSES else f'<a href="{html.escape(run_url, quote=True)}" aria-label="Source report for {safe["name"]}">Source report ↗</a>'
            target = _check_target(row["id"])
            # A dash means no active mode: unknown (not reported) or excluded (not activated).
            mode = "—" if row["mode"] in _INACTIVE_STATUSES else _CONTROL_MODES[row["mode"]]
            rows.append(f'<tr><th scope="row"><a href="#{target}">{safe["name"]}</a> <code class="check-id">{safe["id"]}</code></th><td><span class="size-result {tone}">{label}</span></td><td class="mode-cell">{mode}</td></tr>')
            assessment, inputs, condition, metrics = _CHECK_ASSESSMENTS[row["id"]]
            criteria = [("Assessment", assessment), ("Evaluates", inputs), ("Expected result", condition)]
            execution = row["execution"]
            run_facts = ''
            if execution["availability"] == "available":
                duration = _duration(execution["duration_seconds"])
                completed = _utc_label(execution["completed_at"])
                run_facts = f'<p class="check-run">Ran for <strong>{duration}</strong> · completed <time datetime="{execution["completed_at"]}">{completed}</time></p>'
                criteria.extend([("Started (UTC)", execution["started_at"]),
                                 ("Completed (UTC)", execution["completed_at"]),
                                 ("Execution time", f'{duration} ({execution["duration_seconds"]:,} seconds)'),
                                 ("Producer conclusion", execution["conclusion"].replace("_", " "))])
            else:
                criteria.append(("Execution time", "Not supplied by this source report"))
            measured = _measurement_summary(row["measurements"])
            evaluated = _pr_metadata_summary(row["detail"])
            if evaluated:
                run_facts += f'<p class="check-measure"><strong>{html.escape(evaluated)}</strong><span>{_PR_METADATA_NOTE}</span></p>'
                criteria.append(("Evaluated", evaluated))
            elif measured:
                run_facts += f'<p class="check-measure"><strong>{html.escape(measured)}</strong><span>{_measurement_note(row["measurements"])}</span></p>'
                criteria.append(("Self-reported measurements", measured))
            elif row["id"] != "change-scope":
                criteria.append(("Counts not reported", _counts_gap(metrics, row["id"], row["measurements"])))
            criteria_rows = ''.join(f'<tr><th scope="row">{html.escape(key)}</th><td>{html.escape(value)}</td></tr>' for key, value in criteria)
            measurements = '<details class="criteria"><summary>Assessment criteria</summary><table class="assessment-table"><caption>Assessment criteria and available detail</caption><tbody>' + criteria_rows + '</tbody></table></details>'
            if row["id"] == "change-scope":
                measurements += _scope_html(scope)
            note_html = f'<p class="check-note">{note}</p>' if note else ''
            mode_html = '' if row["mode"] in _INACTIVE_STATUSES else f'<p class="check-mode">{_CONTROL_MODES[row["mode"]]}</p>'
            card = f'<article class="check-detail {tone}" id="check-{safe["id"]}" tabindex="-1"><div class="check-top"><h3>{safe["name"]} <code class="check-id">{safe["id"]}</code></h3><span class="size-result">{label}</span></div><p>{safe["purpose"]}</p>{mode_html}{note_html}{run_facts}{measurements}<div class="check-links">{evidence}<a href="#checks-title">Back to checks ↑</a></div></article>'
            detail_status = "separate" if row.get("separate_subject") else row["status"]
            (inactive_details if row["status"] in _INACTIVE_STATUSES else active_details).append((detail_status, card))
        groups.append(f'<tbody><tr class="check-category"><th colspan="3" scope="rowgroup">{html.escape(group)}</th></tr>{"".join(rows)}</tbody>')
    overview = '<section class="checks" aria-labelledby="checks-title"><p class="eyebrow">Every check, visible</p><h2 id="checks-title" tabindex="-1">Individual checks</h2><p class="checks-intro">All built-in catalog checks. Select a check to see its purpose and evidence below. Not reported means no validated row in this snapshot; it does not imply disabled or passed. A dash means the check has no active mode in this snapshot. Custom controls may contribute to totals without publishing their private names.</p><div class="checks-table-wrap" role="region" aria-label="Individual checks" tabindex="0"><table class="checks-table"><caption>Check results and policy modes for this snapshot</caption><thead><tr><th scope="col">Check</th><th scope="col">Result</th><th scope="col" class="mode-cell">Mode</th></tr></thead>' + ''.join(groups) + '</table></div></section>'
    # Stable sort: checks needing attention first, then passes, each in catalog order.
    order = (*_ATTENTION_STATUSES, "passed")
    active = ''.join(card for _, card in sorted(active_details, key=lambda item: order.index(item[0])))
    inactive = ''.join(card for _, card in inactive_details)
    details = '<section class="checks" aria-labelledby="check-details-title"><h2 id="check-details-title">Check details</h2><p class="checks-intro">Checks needing attention come first. Source report links open the evaluation run containing the detailed evidence.</p>' + active
    if inactive:
        details += f'<h3 class="inactive-title" id="inactive-title">Checked elsewhere, not activated, or not reported <span>({len(inactive_details)})</span></h3><p class="checks-intro">{_inactive_intro(inactive_details)}</p><div class="inactive-grid">{inactive}</div>'
    return overview + details + '</section>'



def _breakdown_markdown(breakdown: dict[str, Any]) -> str:
    if breakdown["availability"] != "available":
        return "Result breakdown unavailable: this source does not contain complete, consistent control results."
    lines = ["| Evidence results | Passed | Failed | Blocked | Unverified |", "| --- | ---: | ---: | ---: | ---: |"]
    for key, label in (("overall", "All active controls"), ("enforced", "Enforced"), ("advisory", "Advisory")):
        counts = breakdown[key]
        lines.append(f"| {label} | {counts['passed']} | {counts['failed']} | {counts['blocked']} | {counts['unverified']} |")
    return "\n".join(lines)


def _breakdown_html(breakdown: dict[str, Any]) -> str:
    heading = '<section class="scope-panel" aria-labelledby="results-title"><h2 id="results-title">Evidence results</h2>'
    if breakdown["availability"] != "available":
        return heading + '<p>Result breakdown unavailable: this source does not contain complete, consistent control results.</p></section>'
    rows = []
    for key, label in (("overall", "All active controls"), ("enforced", "Enforced"), ("advisory", "Advisory")):
        counts = breakdown[key]
        rows.append(f'<tr><th scope="row">{label}</th><td>{counts["passed"]}</td><td>{counts["failed"]}</td><td>{counts["blocked"]}</td><td>{counts["unverified"]}</td></tr>')
    return heading + '<div class="size-table-wrap" role="region" aria-label="Evidence results" tabindex="0"><table class="size-table"><caption>Control outcomes, separated from unavailable evidence</caption><thead><tr><th scope="col">Controls</th><th scope="col">Passed</th><th scope="col">Failed</th><th scope="col">Blocked</th><th scope="col">Unverified</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div><p>Failed means a reported failure. Blocked means the producer reported a blocker. Unverified means no usable result was available.</p></section>'


_SIZE_GUIDANCE = "Large PRs can overwhelm human reviewers; smaller, focused PRs make feedback more actionable."


_SCOPE_ROWS = (
    ("files", "max_files", "Counted files"),
    ("added_lines", "max_added_lines", "Added lines"),
    ("changed_lines", "max_changed_lines", "Added + deleted lines"),
    ("max_added_lines_per_file", "max_added_lines_per_file", "Most added lines in one file"),
)
_SCOPE_METRICS = (
    "files", "added_lines", "changed_lines", "max_added_lines_per_file",
    "binary_files", "total_files", "total_added_lines", "total_changed_lines",
    "excluded_files", "excluded_added_lines", "excluded_changed_lines",
    "excluded_binary_files",
)


def _change_scope(document: dict[str, Any]) -> dict[str, Any]:
    # Optional measurements cannot invalidate an otherwise valid scorecard.
    # Malformed data is never rendered as a passing or zero-sized change.
    try:
        return _validated_change_scope(document)
    except (ValueError, TypeError, KeyError):
        return {"availability": "unavailable"}


def _validated_change_scope(document: dict[str, Any]) -> dict[str, Any]:
    """Project only bounded aggregate measurements from the selected producer."""
    unavailable = {"availability": "unavailable"}
    controls = document.get("controls", [])
    if not isinstance(controls, list):
        return unavailable
    rows = [row for row in controls if isinstance(row, dict) and row.get("id") == "change-scope"]
    if not rows:
        return unavailable
    if len(rows) != 1:
        raise ValueError("duplicate change-scope controls")
    row = rows[0]
    provider = row.get("authoritative_provider") or {}
    result = row.get("authoritative_result") or {}
    mode = row.get("effective_mode")
    if (not isinstance(provider, dict) or provider.get("id") != "repository-change-scope"
            or mode not in {"advisory", "enforced"}
            or not isinstance(result, dict)
            or row.get("evidence_status") not in {"passed", "failed"}):
        return unavailable
    scope = result.get("change_scope")
    if scope is None:
        return unavailable
    if not isinstance(scope, dict) or type(scope.get("version")) is not int or scope["version"] != 1:
        raise ValueError("change_scope must use version 1")
    raw_metrics, raw_limits = scope.get("metrics"), scope.get("thresholds")
    if not isinstance(raw_metrics, dict) or not isinstance(raw_limits, dict):
        raise ValueError("change_scope requires metrics and thresholds")
    metrics = {key: _integer(raw_metrics.get(key), f"change_scope.{key}") for key in _SCOPE_METRICS}
    limits = {key: _integer(raw_limits.get(key), f"change_scope.{key}", positive=True) for _, key, _ in _SCOPE_ROWS}
    if any(value > 2**53 - 1 for value in (*metrics.values(), *limits.values())):
        raise ValueError("change_scope measurements exceed the supported bound")
    for key in ("files", "added_lines", "changed_lines"):
        if metrics[f"total_{key}"] != metrics[key] + metrics[f"excluded_{key}"]:
            raise ValueError("change_scope aggregate totals are inconsistent")
    for prefix in ("", "excluded_"):
        files = metrics[f"{prefix}files"]
        binary = metrics[f"{prefix}binary_files"]
        added = metrics[f"{prefix}added_lines"]
        changed = metrics[f"{prefix}changed_lines"]
        if binary > files or added > changed or (files == binary and changed != 0):
            raise ValueError("change_scope measurements are inconsistent")
    maximum = metrics["max_added_lines_per_file"]
    text_files = metrics["files"] - metrics["binary_files"]
    if maximum > metrics["added_lines"] or metrics["added_lines"] > maximum * text_files:
        raise ValueError("change_scope per-file measurements are inconsistent")
    exceeded = any(metrics[key] > limits[limit] for key, limit, _ in _SCOPE_ROWS)
    status = "failed" if exceeded else "passed"
    if result.get("status") != status or row.get("evidence_status") != status:
        raise ValueError("change_scope status does not match its measurements")
    return {"availability": "available", "mode": mode, "status": status,
            "metrics": metrics, "thresholds": limits}


def _scope_markdown(scope: dict[str, Any]) -> str:
    title = "\n## PR Size · Files & LOC\n\n" + _SIZE_GUIDANCE + "\n\n"
    if scope["availability"] != "available":
        return title + "Measurements unavailable. This source does not contain validated PR size measurements.\n"
    metrics, limits = scope["metrics"], scope["thresholds"]
    meaning = "Advisory — warns only; does not block the policy decision." if scope["mode"] == "advisory" else "Enforced — exceeding a limit blocks the policy decision."
    lines = [title + meaning, "", "| Measurement | Counted | Limit | Result |", "| --- | ---: | ---: | --- |"]
    for key, limit, label in _SCOPE_ROWS:
        state = "Above limit" if metrics[key] > limits[limit] else "Within limit"
        lines.append(f"| {label} | {metrics[key]} | {limits[limit]} | {state} |")
    lines += ["", f"Total: {metrics['total_files']} files; {metrics['total_added_lines']} added lines; {metrics['total_changed_lines']} added + deleted lines.",
              f"Excluded: {metrics['excluded_files']} files; {metrics['excluded_added_lines']} added lines; {metrics['excluded_changed_lines']} added + deleted lines.",
              f"Binary files: {metrics['binary_files']} counted; {metrics['excluded_binary_files']} excluded. Binary contents have no line count."]
    return "\n".join(lines) + "\n"


def _scope_html(scope: dict[str, Any]) -> str:
    # Rendered inside the PR Size check card, so it is a subsection: no repeated
    # title, and the card's mode label already states advisory versus enforced.
    heading = '<section class="scope-block" aria-labelledby="size-title"><h4 id="size-title" tabindex="-1">Files &amp; lines of code</h4>' + f'<p>{_SIZE_GUIDANCE}</p>'
    if scope["availability"] != "available":
        return heading + '<p><strong>Measurements unavailable</strong></p><p>This source does not contain validated PR size measurements. No size verdict is available; missing measurements are not a pass.</p></section>'
    metrics, limits = scope["metrics"], scope["thresholds"]
    advisory = scope["mode"] == "advisory"
    meaning = "Exceeding a limit warns only; it does not block the policy decision." if advisory else "Exceeding a limit blocks the policy decision."
    rows = []
    for key, limit, label in _SCOPE_ROWS:
        exceeded = metrics[key] > limits[limit]
        tone = ("caution" if advisory else "danger") if exceeded else "good"
        state = "Above limit" if exceeded else "Within limit"
        rows.append(f'<tr><th scope="row">{label}</th><td>{metrics[key]:,}</td><td>{limits[limit]:,}</td><td><span class="size-result {tone}">{state}</span></td></tr>')
    return heading + f'''<p class="scope-mode">{meaning}</p>
<div class="size-table-wrap" role="region" aria-label="PR size measurements" tabindex="0"><table class="size-table"><caption>Counted changes compared with the configured limits</caption><thead><tr><th scope="col">Measurement</th><th scope="col">Counted</th><th scope="col">Limit</th><th scope="col">Result</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<div class="scope-totals"><p><strong>Total diff</strong><br>{metrics['total_files']:,} files · {metrics['total_added_lines']:,} added lines · {metrics['total_changed_lines']:,} added + deleted lines</p><p><strong>Excluded from limits</strong><br>{metrics['excluded_files']:,} files · {metrics['excluded_added_lines']:,} added lines · {metrics['excluded_changed_lines']:,} added + deleted lines</p></div>
<p class="size-footnote">Counted changes exclude the configured path patterns. Binary files: {metrics['binary_files']:,} counted; {metrics['excluded_binary_files']:,} excluded. Binary contents have no line count. File paths are not published.</p></section>'''


def _validated_scorecard(source_dir: Path) -> dict[str, Any]:
    json_path, _ = _bounded_source(source_dir)
    try:
        document = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"invalid scorecard JSON: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("scorecard JSON must contain an object")
    if document.get("version") != 2 or type(document.get("version")) is not int:
        raise ValueError("scorecard version must be 2")
    if document.get("operation") != "change":
        raise ValueError("scorecard operation must be change")
    status = document.get("status")
    decision = document.get("decision")
    if not isinstance(status, str) or status not in VALID_STATUSES:
        raise ValueError("scorecard status must be GREEN, ORANGE, or RED")
    if not isinstance(decision, str) or decision not in VALID_DECISIONS:
        raise ValueError("scorecard decision must be allow or block")
    subject = document.get("subject")
    if not isinstance(subject, dict) or subject.get("type") != "git-commit":
        raise ValueError("scorecard subject must be a git commit")
    revision = subject.get("revision")
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise ValueError(
            "scorecard revision must be an exact lowercase 40-character SHA"
        )
    enforced = _counts(document, "enforced")
    advisory = _counts(document, "advisory")
    passed = enforced["passed"] + advisory["passed"]
    total = enforced["total"] + advisory["total"]
    if total == 0:
        raise ValueError("scorecard must contain at least one active control")
    enforced_miss = enforced["passed"] < enforced["total"]
    advisory_miss = advisory["passed"] < advisory["total"]
    expected_status = "RED" if enforced_miss else "ORANGE" if advisory_miss else "GREEN"
    expected_decision = "block" if expected_status == "RED" else "allow"
    if status != expected_status or decision != expected_decision:
        raise ValueError(
            "scorecard status and decision are inconsistent with aggregate counts"
        )
    return {
        "status": status,
        "decision": decision,
        "enforced": enforced,
        "advisory": advisory,
        "passed": passed,
        "total": total,
        "subject_revision": revision,
        "change_scope": _change_scope(document),
        "result_breakdown": _result_breakdown(document),
        "controls": _control_details(document),
    }


def inspect_scorecard(source_dir: Path) -> dict[str, object]:
    """Return the normalized trusted fields needed to validate a source artifact."""
    return dict(_validated_scorecard(Path(source_dir)))


def _write_atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _public_metadata(
    inspected: dict[str, Any],
    repository: str,
    run_id: int,
    run_attempt: int,
    run_url: str,
    source_run_created_at: str,
    expected_revision: str,
) -> dict[str, Any]:
    published_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    passed = inspected["passed"]
    total = inspected["total"]
    return {
        "version": 1,
        "operation": "change",
        "label": "Latest PR Scorecard",
        "status": inspected["status"],
        "decision": inspected["decision"],
        "message": f"{inspected['status']} {passed}/{total}",
        "repository": repository,
        "source_run_id": run_id,
        "source_run_attempt": run_attempt,
        "source_run_url": run_url,
        "source_run_created_at": source_run_created_at,
        "published_at": published_at,
        "subject_digest": f"sha256:{hashlib.sha256(expected_revision.encode()).hexdigest()}",
        "passed": passed,
        "total": total,
        "enforced": inspected["enforced"],
        "advisory": inspected["advisory"],
        "pages_url": pages_base_url(repository),
        "change_scope": inspected["change_scope"],
        "result_breakdown": inspected["result_breakdown"],
        "controls": inspected["controls"],
    }


def _svg(metadata: dict[str, Any]) -> str:
    label = str(metadata["label"])
    message = str(metadata["message"])
    label_width = 128
    message_width = max(88, len(message) * 8 + 20)
    total_width = label_width + message_width
    description = html.escape(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")), quote=True
    )
    safe_label = html.escape(label)
    safe_message = html.escape(message)
    color = VALID_STATUSES[str(metadata["status"])]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{safe_label}: {safe_message}">
  <title>{safe_label}: {safe_message}</title>
  <desc>{description}</desc>
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
  <clipPath id="r"><rect width="{total_width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)"><rect width="{label_width}" height="20" fill="#555"/><rect x="{label_width}" width="{message_width}" height="20" fill="{color}"/><rect width="{total_width}" height="20" fill="url(#s)"/></g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11"><text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{safe_label}</text><text x="{label_width / 2}" y="14">{safe_label}</text><text x="{label_width + message_width / 2}" y="15" fill="#010101" fill-opacity=".3">{safe_message}</text><text x="{label_width + message_width / 2}" y="14">{safe_message}</text></g>
</svg>
"""


_ALLOW_MEANING = "ALLOW means the enforced controls are satisfied for this snapshot. It does not establish mergeability or release readiness."
_UNGATED_MEANING = ("No enforced controls are configured, so the policy decision is not gated by any control "
                    "and every result is advisory. It does not establish mergeability or release readiness.")
_BLOCK_MEANING = "BLOCK means at least one enforced control did not pass for this snapshot."


def _collection_note(controls: list[dict[str, Any]]) -> str:
    if any(row["measurements"]["availability"] == "available" for row in controls):
        return ("Test totals, coverage, validator counts, and Semgrep CE and Gitleaks finding counts, where shown, are "
                "self-reported by the pull request's own workflow run and are not independently verified. Finding counts "
                "from other security scanners are not collected in this summary.")
    return "Test totals, security finding counts, and coverage percentages are not collected in this summary."


def _decision_meaning(metadata: dict[str, Any]) -> str:
    if metadata["decision"] == "block":
        return _BLOCK_MEANING
    return _UNGATED_MEANING if metadata["enforced"]["total"] == 0 else _ALLOW_MEANING


def _markdown(metadata: dict[str, Any]) -> str:
    return f"""# Latest PR Scorecard

![{metadata["message"]}](proof-badge.svg)

| Field | Value |
| --- | --- |
| Repository | {metadata["repository"]} |
| Operation | {metadata["operation"]} |
| Status | {metadata["status"]} |
| Active controls | {metadata["passed"]}/{metadata["total"]} passed |
| Enforced | {metadata["enforced"]["passed"]}/{metadata["enforced"]["total"]} passed |
| Advisory | {metadata["advisory"]["passed"]}/{metadata["advisory"]["total"]} passed |
| Source run | [{metadata["source_run_id"]} attempt {metadata["source_run_attempt"]}]({metadata["source_run_url"]}) |
| Source created | {metadata["source_run_created_at"]} |
| Published | {metadata["published_at"]} |
| Subject digest | {metadata["subject_digest"]} |

{_breakdown_markdown(metadata["result_breakdown"])}

Failed means a reported failure. Blocked means the producer reported a blocker. Unverified means no usable result was available.

{_decision_meaning(metadata)}
This is a published PR snapshot. The source timestamp does not prove it matches the current PR head or current main.
{_collection_note(metadata["controls"])}
{_scope_markdown(metadata["change_scope"])}
{_controls_markdown(metadata["controls"])}
"""


_REPORT_CSS = """
:root{color-scheme:light;--ink:#182b32;--muted:#52636b;--line:#dbe3e4;
  --paper:#fff;--canvas:#f4f7f7;--accent:#155e63;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--canvas);color:var(--ink);font-size:15px;line-height:1.6}
a{color:var(--accent);text-underline-offset:4px}
a:hover{text-decoration-thickness:2px}
a:focus-visible,summary:focus-visible{outline:3px solid #227b92;outline-offset:5px;border-radius:3px}
.skip-link{position:absolute;left:16px;top:-80px;background:var(--paper);padding:12px;z-index:1}
.skip-link:focus{top:12px}
.shell{width:min(1080px,100% - 64px);margin-inline:auto}
.topbar{background:var(--paper);border-bottom:1px solid var(--line)}
.topbar .shell{display:flex;justify-content:space-between;align-items:center;gap:24px;min-height:82px;padding-block:16px}
.brand{display:flex;align-items:center;gap:12px;min-width:0}
.brand-mark{display:grid;place-items:center;width:36px;height:40px;flex-shrink:0;background:var(--accent);color:#fff;font-weight:750;border-radius:9px 9px 16px 16px}
.brand-name{display:block;font-size:16px;font-weight:750;letter-spacing:-.3px}
.repository{display:block;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.repo-link{font-size:13px;font-weight:600;white-space:nowrap}
main{padding-block:48px 36px}
.eyebrow{margin:0 0 8px;color:var(--accent);font-size:11px;font-weight:750;letter-spacing:1.7px;text-transform:uppercase}
h1{margin:0;font-size:clamp(30px,4.5vw,42px);font-weight:650;line-height:1.2;letter-spacing:-1.6px}
.intro{margin:12px 0 28px;color:var(--muted);max-width:680px;font-size:16px}
.good{--tone:#216341;--wash:#eef8f1;--edge:#c6e1cf}
.caution{--tone:#815407;--wash:#fff7e8;--edge:#ecd5a7}
.danger{--tone:#a02d36;--wash:#fff1f2;--edge:#ebc5c9}
.neutral{--tone:#52636b;--wash:#f2f5f5;--edge:var(--line)}
.status-panel{display:flex;justify-content:space-between;align-items:center;gap:24px;padding:25px 28px;border:1px solid var(--edge);border-left:4px solid var(--tone);border-radius:12px;background:var(--wash);margin-bottom:22px}
.status-label{display:flex;align-items:center;gap:8px;color:var(--tone);font-size:12px;font-weight:800;letter-spacing:1px}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--tone)}
.status-panel h2{font-size:21px;line-height:1.35;letter-spacing:-.4px;margin:7px 0 4px}
.status-panel p{margin:0;color:var(--muted);font-size:13px}
.decision{text-align:right;flex-shrink:0}
.decision dt{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:1px}
.decision dd{color:var(--tone);margin:4px 0 0;font-size:20px;font-weight:750}
.metrics-note{margin:12px 2px 0;color:var(--muted);font-size:13px}
.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.metric{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:24px}
.metric h2{margin:0 0 12px;font-size:13px;font-weight:650;color:var(--muted)}
.count{font-size:40px;font-weight:650;line-height:1.2;letter-spacing:-1.5px;font-variant-numeric:tabular-nums}
.count span{font-size:24px;color:var(--muted);font-weight:450;letter-spacing:-.5px}
.count-caption{font-size:12px;color:var(--muted);margin:5px 0 20px}
.track{height:6px;border-radius:5px;background:#e8eeee;overflow:hidden}
.fill{height:100%;background:var(--tone);border-radius:5px}
.metric-note{color:var(--tone);font-size:12px;font-weight:650;margin:10px 0 0}
.scope-panel{margin-top:24px;padding:28px;background:var(--paper);border:1px solid var(--line);border-radius:12px}
.scope-panel h2{margin:0;font-size:24px;letter-spacing:-.5px}
.scope-panel p{color:var(--muted);font-size:13px}
.scope-mode{font-weight:650}
.size-table-wrap{overflow-x:auto}.size-table-wrap:focus-visible{outline:3px solid #227b92;outline-offset:3px}
.size-table{width:100%;border-collapse:collapse;font-size:13px}
.size-table caption{text-align:left;color:var(--muted);padding:8px 0 12px}
.size-table th,.size-table td{text-align:left;padding:13px 10px;border-bottom:1px solid var(--line)}
.size-table thead{background:var(--canvas)}
.size-table td:nth-child(2),.size-table td:nth-child(3){font-variant-numeric:tabular-nums}
.size-result{display:inline-block;white-space:nowrap;padding:3px 9px;border-radius:5px;background:var(--wash);color:var(--tone);font-weight:650}
.scope-totals{display:grid;grid-template-columns:1fr 1fr;gap:20px}.scope-totals strong{color:var(--ink)}
.size-footnote{margin-bottom:0}
.scope-block{margin-top:18px;padding-top:16px;border-top:1px solid var(--line)}
.scope-block h4{margin:0;font-size:14px;line-height:1.4;color:var(--ink)}
.check-detail .scope-block p{margin:6px 0 0}.check-detail .scope-block .scope-mode{color:var(--ink);font-weight:600}
.check-detail .scope-block .size-footnote{margin-top:12px}
.checks{margin-top:36px}.checks h2{font-size:28px;margin:0}.checks-intro{color:var(--muted);max-width:850px;font-size:14px}
.checks-table-wrap{overflow-x:auto}.checks-table-wrap:focus-visible{outline:3px solid #227b92;outline-offset:3px}
.attention{margin:0 0 22px;padding:20px 24px;background:var(--paper);border:1px solid var(--line);border-radius:12px}
.attention h2{margin:0 0 10px;font-size:15px}.attention ul{list-style:none;margin:0;padding:0;display:grid;gap:8px;font-size:14px}
.attention .size-result{font-size:11px;padding:2px 7px;min-width:78px;text-align:center}.attention-mode{color:var(--muted);font-size:12px}
.attention-private{color:var(--muted);font-size:13px}
.decision .decision-note{color:var(--muted);font-size:11px;font-weight:600;margin-top:2px}
.checks-table{width:100%;border-collapse:collapse;background:var(--paper);font-size:13px}
.checks-table caption{text-align:left;color:var(--muted);font-size:12px;padding:0 0 10px}
.checks-table th,.checks-table td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
.checks-table thead{background:#e8eeee}.checks-table tbody th[scope="row"]{font-weight:550}
.checks-table .check-category th{background:#edf3f3;color:var(--accent);font-size:12px;padding-block:10px}
.check-id{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;font-weight:400;color:var(--muted);margin-left:6px}
.checks-table .size-result{font-size:11px;padding:2px 7px}.checks-table tbody tr:not(.check-category):hover{background:#f5f9f9}
.assessment-table{width:100%;border-collapse:collapse;margin-top:16px;font-size:13px}.assessment-table caption{text-align:left;color:var(--muted);font-size:12px;padding-bottom:8px}.assessment-table th,.assessment-table td{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:10px 8px}.assessment-table th{width:180px;font-weight:600}.assessment-table td{overflow-wrap:anywhere}
.check-detail,#checks-title,#size-title{scroll-margin-top:24px}#size-title:focus{outline:2px solid var(--accent);outline-offset:4px}.check-detail:focus,#checks-title:focus{outline:2px solid var(--accent);outline-offset:4px}
.check-detail{margin-top:16px;padding:22px;border:1px solid var(--line);border-top:3px solid var(--tone);border-radius:10px;background:var(--paper);display:flex;flex-direction:column}
.check-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.check-top h3{font-size:16px;line-height:1.4;margin:0}.check-top .size-result{font-size:11px}
.check-detail p{font-size:13px;color:var(--muted);margin:12px 0 0}.check-detail .check-mode{font-size:11px;font-weight:750;text-transform:uppercase;letter-spacing:.6px;color:var(--ink)}
.check-detail .check-note{font-size:12px}.check-detail .check-run{font-size:12px;color:var(--ink)}
.check-detail .check-measure{font-size:13px;color:var(--ink);padding:10px 12px;background:var(--canvas);border-radius:8px}
.check-measure span{display:block;color:var(--muted);font-size:11px;margin-top:2px}
.criteria{border:0;padding:12px 0 0;font-size:12px}.criteria summary{color:var(--accent)}
.inactive-title{margin:32px 0 0;font-size:18px}.inactive-title span{color:var(--muted);font-weight:500}
.inactive-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}
.inactive-grid .check-detail{padding:16px 18px;border-top-width:1px}.check-links{display:flex;flex-wrap:wrap;gap:16px;padding-top:16px;margin-top:auto;font-size:12px}
.evidence{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:36px;padding:30px;margin-top:24px;background:var(--paper);border:1px solid var(--line);border-radius:12px}
.evidence h2{margin:0 0 8px;font-size:18px;letter-spacing:-.3px}
.evidence p{color:var(--muted);font-size:13px;margin:0 0 20px;max-width:420px}
.button{display:inline-flex;align-items:center;gap:20px;background:var(--accent);color:#fff;border:1px solid var(--accent);border-radius:7px;text-decoration:none;font-size:13px;font-weight:650;padding:10px 16px}
.button:hover{background:#104b50}
.source-facts{margin:0;display:grid;gap:15px;align-content:start}
.source-facts div{display:grid;grid-template-columns:110px minmax(0,1fr);gap:16px}
.source-facts dt{color:var(--muted);font-size:12px}
.source-facts dd{margin:0;font-size:12px;font-weight:550;overflow-wrap:anywhere}
.scope-note{display:flex;gap:12px;padding:20px 2px;color:var(--muted);font-size:12px;line-height:1.7}
.scope-note strong{color:var(--ink);font-weight:650}
.scope-note p{margin:0}
.note-mark{flex-shrink:0;font-size:16px;color:var(--accent)}
details{border-top:1px solid var(--line);padding:18px 0;color:var(--muted);font-size:12px}
summary{cursor:pointer;width:fit-content;font-weight:600}
.digest{margin:14px 0 0}
.digest code{display:block;margin-top:5px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere;color:var(--ink)}
footer{display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding:22px 0 12px;color:var(--muted);font-size:11px}
footer img{display:block;max-width:100%;height:auto}
.formats{display:flex;gap:20px;flex-wrap:wrap;font-size:12px}
@media(max-width:680px){
  .shell{width:calc(100% - 36px)}
  .topbar .shell{gap:12px}.repo-link{font-size:12px}
  main{padding-top:30px}.intro{font-size:14px}
  .status-panel{align-items:flex-start;padding:20px;gap:16px}
  .status-panel h2{font-size:18px}.decision dd{font-size:17px}
  .metrics{grid-template-columns:1fr;gap:12px}
  .check-detail{padding:18px}.checks-table th,.checks-table td{padding:7px 9px;white-space:normal}
  .checks-table .check-id{display:block;margin:2px 0 0}.checks-table .mode-cell{display:none}
  .attention{padding:18px}.inactive-grid{grid-template-columns:1fr}
  .scope-panel{padding:20px}.scope-totals{grid-template-columns:1fr;gap:0}
  .size-table{font-size:12px}
  .size-table th,.size-table td{padding:10px 5px}
  .metric{padding:20px}.count-caption{margin-bottom:14px}
  .evidence{grid-template-columns:1fr;gap:26px;padding:22px}
  .source-facts div{grid-template-columns:95px minmax(0,1fr);gap:12px}
  footer{align-items:flex-start;flex-direction:column}
}
@media(max-width:380px){.status-panel{flex-direction:column}.decision{text-align:left;margin:0}}
@media(prefers-reduced-motion:no-preference){a{transition:background-color .15s ease}}
"""


def _html(metadata: dict[str, Any]) -> str:
    safe = {key: html.escape(str(value), quote=True) for key, value in metadata.items()}
    tone, headline = {
        "GREEN": ("good", "All active controls passed"),
        "ORANGE": ("caution", "Advisory controls need attention"),
        "RED": ("danger", "Enforced controls need attention"),
    }[metadata["status"]]
    cards = []
    for label, counts, card_tone in (
        ("Active controls", metadata, tone),
        ("Enforced", metadata["enforced"], "danger"),
        ("Advisory", metadata["advisory"], "caution"),
    ):
        passed, total = counts["passed"], counts["total"]
        percent = passed / total * 100 if total else 0
        if not total:
            card_tone, note = "neutral", "No controls configured"
        elif passed == total:
            card_tone, note = "good", "All passed"
        else:
            note = f"{total - passed} not passed"
        cards.append(f"""<section class="metric {card_tone}" aria-label="{label}">
  <h2>{label}</h2><div class="count">{passed}<span>/{total}</span></div>
  <p class="count-caption">controls passed</p>
  <div class="track" aria-hidden="true"><div class="fill" style="width:{percent:.2f}%"></div></div>
  <p class="metric-note">{note}</p>
</section>""")
    ungated = '<dd class="decision-note">Advisory only</dd>' if not metadata["enforced"]["total"] else ''
    timestamps = {
        key: datetime.fromisoformat(str(metadata[key]).replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .strftime("%d %b %Y · %H:%M:%S UTC")
        for key in ("source_run_created_at", "published_at")
    }
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="Latest published pull-request scorecard for {safe['repository']}: {safe['message']}.">
  <title>Latest PR Scorecard · {safe['repository']}</title>
  <style>{_REPORT_CSS}</style>
</head>
<body>
<a class="skip-link" href="#scorecard">Skip to scorecard</a>
<header class="topbar"><div class="shell">
  <div class="brand"><span class="brand-mark" aria-hidden="true">AI</span><div>
    <span class="brand-name">AI Software Toolkit</span><span class="repository">{safe['repository']}</span>
  </div></div>
  <a class="repo-link" href="https://github.com/{safe['repository']}">View repository <span aria-hidden="true">↗</span></a>
</div></header>
<main class="shell" id="scorecard">
  <p class="eyebrow">CI evidence / change assessment</p>
  <h1>Latest PR Scorecard</h1>
  <p class="intro">A clear view of the latest published pull-request evaluation.</p>
  <section class="status-panel {tone}" aria-label="Scorecard status">
    <div><div class="status-label"><span class="status-dot" aria-hidden="true"></span>{safe['status']}</div>
      <h2>{headline}</h2><p>{_decision_meaning(metadata)}</p></div>
    <dl class="decision"><dt>Policy decision</dt><dd>{safe['decision'].upper()}</dd>{ungated}</dl>
  </section>
  {_attention_html(metadata["controls"], metadata["result_breakdown"])}
  <div class="metrics">{''.join(cards)}</div>
  <p class="metrics-note">{html.escape(_count_reconciliation(metadata))} <a href="#checks-title">See all checks ↓</a></p>
  {_breakdown_html(metadata["result_breakdown"])}
  {_controls_html(metadata["controls"], metadata["source_run_url"], metadata["change_scope"])}
  <section class="evidence" aria-labelledby="evidence-title">
    <div><h2 id="evidence-title">Trace it to the evidence</h2>
      <p>Open the source CI run for the full scorecard, individual controls, and supporting results.</p>
      <a class="button" href="{safe['source_run_url']}">View source CI run <span aria-hidden="true">↗</span></a>
    </div>
    <dl class="source-facts">
      <div><dt>Source run</dt><dd>#{safe['source_run_id']} · attempt {safe['source_run_attempt']}</dd></div>
      <div><dt>Source created</dt><dd><time datetime="{safe['source_run_created_at']}">{timestamps['source_run_created_at']}</time></dd></div>
      <div><dt>Published</dt><dd><time datetime="{safe['published_at']}">{timestamps['published_at']}</time></dd></div>
      <div><dt>Operation</dt><dd>{safe['operation']}</dd></div>
    </dl>
  </section>
  <aside class="scope-note"><span class="note-mark" aria-hidden="true">ⓘ</span>
    <p><strong>A PR snapshot, not an assessment of current main.</strong> Counts show controls with passing evidence.
    The source timestamp does not prove this matches the current PR head. Advisory gaps do not block the policy decision.
    {_collection_note(metadata["controls"])}</p>
  </aside>
  <details><summary>Verification details</summary>
    <p class="digest">Subject digest<code>{safe['subject_digest']}</code></p>
  </details>
  <footer><img src="proof-badge.svg" alt="{safe['message']}" width="216" height="20">
    <nav class="formats" aria-label="Report formats"><a href="scorecard.json">Summary JSON</a><a href="scorecard.md">Summary Markdown</a></nav>
  </footer>
</main>
</body></html>
"""


def _replace_directory(temporary: Path, output_dir: Path) -> None:
    if output_dir.is_symlink():
        raise OSError("output directory cannot be a symlink")
    if output_dir.exists() and not output_dir.is_dir():
        raise OSError("output path must be a directory")
    backup: Path | None = None
    if output_dir.exists():
        backup = (
            output_dir.parent
            / f".{output_dir.name}.backup-{next(tempfile._get_candidate_names())}"
        )
        os.replace(output_dir, backup)
    try:
        os.replace(temporary, output_dir)
    except Exception:
        if backup is not None and not output_dir.exists():
            os.replace(backup, output_dir)
        raise
    if backup is not None:
        try:
            shutil.rmtree(backup)
        except OSError:
            # The second rename is the publication commit point. Cleanup must
            # never turn a successfully installed output into a failed run.
            pass


def render_badge(
    source_dir: Path,
    output_dir: Path,
    repository: str,
    run_id: int,
    run_attempt: int,
    run_url: str,
    source_run_created_at: str,
    expected_revision: str,
) -> dict[str, object]:
    """Render a validated scorecard into a bounded, static public projection."""
    inspected = _validated_scorecard(Path(source_dir))
    _repository(repository)
    run_id = _integer(run_id, "run_id", positive=True)
    run_attempt = _integer(run_attempt, "run_attempt", positive=True)
    run_url = _validate_run_url(repository, run_id, run_attempt, run_url)
    source_run_created_at = _timestamp(source_run_created_at, "source_run_created_at")
    if not isinstance(expected_revision, str) or not REVISION_PATTERN.fullmatch(
        expected_revision
    ):
        raise ValueError(
            "expected_revision must be an exact lowercase 40-character SHA"
        )
    if inspected["subject_revision"] != expected_revision:
        raise ValueError("scorecard revision does not match expected revision")

    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent)
    )
    try:
        metadata = _public_metadata(
            inspected,
            repository,
            run_id,
            run_attempt,
            run_url,
            source_run_created_at,
            expected_revision,
        )
        (temporary / "proof-badge.svg").write_text(
            _svg(metadata), encoding="utf-8"
        )
        (temporary / "scorecard.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (temporary / "scorecard.md").write_text(_markdown(metadata), encoding="utf-8")
        (temporary / "index.html").write_text(_html(metadata), encoding="utf-8")
        _replace_directory(temporary, output_dir)
        return metadata
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a bounded public Proof scorecard badge"
    )
    parser.add_argument("--source-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect-output", type=Path)
    mode.add_argument("--output-dir", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--run-attempt", type=int)
    parser.add_argument("--run-url")
    parser.add_argument("--source-run-created-at")
    parser.add_argument("--expected-revision")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.inspect_output is not None:
            inspected = inspect_scorecard(args.source_dir)
            _write_atomic_text(
                args.inspect_output,
                json.dumps(inspected, indent=2, sort_keys=True) + "\n",
            )
            return 0
        required = {
            "repository": args.repository,
            "run_id": args.run_id,
            "run_attempt": args.run_attempt,
            "run_url": args.run_url,
            "source_run_created_at": args.source_run_created_at,
            "expected_revision": args.expected_revision,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"rendering requires: {', '.join(missing)}")
        metadata = render_badge(args.source_dir, args.output_dir, **required)
        print(
            f"Published badge input: {metadata['status']} {metadata['passed']}/{metadata['total']}"
        )
        return 0
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"ERROR runtime: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
