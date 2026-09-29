#!/usr/bin/env python3
"""Evaluate Proof capability evidence against an effective policy."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
REPO_RELATIVE_PATH = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)(?!.*\\)[^\x00-\x1f\x7f]+$"
)
OPERATIONS = ("change", "release")
MODES = {"advisory", "enforced", "not_activated"}
STATUSES = {"passed", "failed", "blocked", "not_run"}
CONTROL_STAGES = {
    "change", "change-and-release", "pre-release", "release",
    "deployment", "post-deployment", "runtime",
}
PROFILE_CONTROL_SETS = {
    "core": {
        "change": {
            "repository-validation", "documentation-validation", "repository-ground-truth",
            "change-scope", "pr-metadata", "build", "unit-tests", "changed-code-coverage",
            "format-and-lint", "migration-validation", "custom-static-analysis",
            "secret-detection",
        },
        "release": {
            "repository-validation", "documentation-validation", "repository-ground-truth",
            "build", "unit-tests", "custom-static-analysis", "secret-detection",
        },
    },
    "github": {
        "change": {
            "deep-sast", "dependency-change-review", "platform-secret-protection",
            "dependency-remediation",
        },
        "release": {"artifact-provenance"},
    },
}


def operation_supports_stage(operation: str, stage: str) -> bool:
    if operation == "change":
        return stage in {"change", "change-and-release"}
    if operation == "release":
        return stage in {"release", "pre-release", "change-and-release"}
    raise ValueError(f"unknown operation: {operation}")


def load_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} must use JSON-compatible YAML: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 80 and IDENTIFIER.fullmatch(value) is not None


def catalog_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if catalog.get("version") != 2 or not isinstance(catalog.get("controls"), list):
        raise ValueError("control catalog must contain version 2 and controls")
    controls: dict[str, dict[str, Any]] = {}
    for control in catalog["controls"]:
        if not isinstance(control, dict) or not valid_identifier(control.get("id")):
            raise ValueError("control catalog contains an invalid control")
        control_id = control["id"]
        if control_id in controls:
            raise ValueError(f"duplicate control: {control_id}")
        if control.get("availability") not in {"runnable", "evidence-only"}:
            raise ValueError(f"control {control_id} availability is invalid")
        if control.get("stage") not in CONTROL_STAGES:
            raise ValueError(f"control {control_id} stage is invalid")
        if control.get("evidence_subject") not in {"git-commit", "artifact", "environment", "pull-request"}:
            raise ValueError(f"control {control_id} evidence subject is invalid")
        if control.get("enforcement_policy") not in {"promotable", "advisory-only"}:
            raise ValueError(f"control {control_id} enforcement policy is invalid")
        controls[control_id] = control
    return controls


def validate_profiles(profiles: dict[str, Any], controls: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    definitions = profiles.get("profiles")
    if profiles.get("version") != 2 or not isinstance(definitions, dict):
        raise ValueError("profiles must contain version 2 and profile definitions")
    if set(definitions) != {"core", "github"}:
        raise ValueError("runtime profiles must define exactly core and github")
    for profile_id, profile in definitions.items():
        if not valid_identifier(profile_id) or not isinstance(profile, dict) or profile.get("runnable") is not True:
            raise ValueError(f"profile {profile_id!r} is invalid")
        defaults = profile.get("defaults")
        if not isinstance(defaults, dict) or set(defaults) != set(OPERATIONS):
            raise ValueError(f"profile {profile_id} must define change and release defaults")
        for operation, modes in defaults.items():
            if not isinstance(modes, dict):
                raise ValueError(f"profile {profile_id} {operation} defaults must be an object")
            expected_controls = PROFILE_CONTROL_SETS[profile_id][operation]
            if set(modes) != expected_controls:
                missing = sorted(expected_controls - set(modes))
                extra = sorted(set(modes) - expected_controls)
                raise ValueError(
                    f"profile {profile_id} {operation} controls must exactly match the v2 contract; "
                    f"missing={missing}, extra={extra}"
                )
            for control_id, mode in modes.items():
                if control_id not in controls:
                    raise ValueError(f"profile {profile_id} references unknown control: {control_id}")
                if controls[control_id]["availability"] != "runnable":
                    raise ValueError(f"profile {profile_id} selects evidence-only control: {control_id}")
                if mode != "advisory":
                    raise ValueError(f"profile {profile_id} defaults must be advisory")
    return definitions


def validate_provider_config(config: dict[str, Any], controls: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    providers = config.get("providers")
    selections = config.get("selections")
    if config.get("version") != 2 or not isinstance(providers, dict) or not isinstance(selections, dict):
        raise ValueError("provider config must contain version 2, providers, and selections")
    review_author_pattern = re.compile(
        r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?$"
    )
    for provider_id, provider in providers.items():
        if not valid_identifier(provider_id) or not isinstance(provider, dict):
            raise ValueError("provider config contains an invalid provider")
        capabilities = provider.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities or len(capabilities) != len(set(capabilities)):
            raise ValueError(f"provider {provider_id} capabilities are invalid")
        if any(capability not in controls for capability in capabilities):
            raise ValueError(f"provider {provider_id} references an unknown capability")
        if not isinstance(provider.get("display_name"), str) or not provider["display_name"].strip():
            raise ValueError(f"provider {provider_id} display name is invalid")
        checks = provider.get("checks")
        if not isinstance(checks, dict) or any(capability not in capabilities for capability in checks):
            raise ValueError(f"provider {provider_id} checks are invalid")
        for capability, check in checks.items():
            if (
                not isinstance(check, dict)
                or not {"check_name", "workflow"}.issubset(check)
                or set(check) - {
                    "check_name", "workflow", "workflow_path", "app_slug", "external_id_prefix",
                    "artifact_name_prefix", "artifact_member", "trusted_paths",
                    "measurements_artifact_prefix", "measurements_member",
                }
            ):
                raise ValueError(f"provider {provider_id} {capability} check is invalid")
            for field in ("check_name", "workflow"):
                if not isinstance(check[field], str) or not check[field].strip() or len(check[field]) > 200:
                    raise ValueError(f"provider {provider_id} {capability} {field} is invalid")
            prefix = check.get("external_id_prefix")
            if prefix is not None and (
                not isinstance(prefix, str) or not prefix.strip() or len(prefix) > 150
            ):
                raise ValueError(f"provider {provider_id} {capability} external_id_prefix is invalid")
            workflow_path = check.get("workflow_path")
            if workflow_path is not None and (
                not isinstance(workflow_path, str) or not workflow_path.strip() or len(workflow_path) > 200
            ):
                raise ValueError(f"provider {provider_id} {capability} workflow_path is invalid")
            trusted_paths = check.get("trusted_paths")
            if trusted_paths is not None and (
                not isinstance(trusted_paths, list)
                or not trusted_paths
                or any(
                    not isinstance(path, str)
                    or len(path) > 300
                    or REPO_RELATIVE_PATH.fullmatch(path) is None
                    for path in trusted_paths
                )
                or len(trusted_paths) != len(set(trusted_paths))
            ):
                raise ValueError(f"provider {provider_id} {capability} trusted_paths are invalid")
            app_slug = check.get("app_slug")
            if app_slug is not None and (
                not isinstance(app_slug, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", app_slug) is None
                or len(app_slug) > 100
            ):
                raise ValueError(f"provider {provider_id} {capability} app_slug is invalid")
            if (workflow_path is None) == (app_slug is None):
                raise ValueError(
                    f"provider {provider_id} {capability} must declare exactly one of workflow_path or app_slug"
                )
            if trusted_paths is not None and workflow_path is None:
                raise ValueError(
                    f"provider {provider_id} {capability} trusted_paths require workflow_path"
                )
            artifact_prefix = check.get("artifact_name_prefix")
            if artifact_prefix is not None and (
                not isinstance(artifact_prefix, str)
                or not artifact_prefix.strip()
                or len(artifact_prefix) > 150
            ):
                raise ValueError(f"provider {provider_id} {capability} artifact_name_prefix is invalid")
            artifact_member = check.get("artifact_member")
            if artifact_member is not None and (
                not isinstance(artifact_member, str)
                or re.fullmatch(r"[A-Za-z0-9._-]+", artifact_member) is None
                or len(artifact_member) > 100
            ):
                raise ValueError(f"provider {provider_id} {capability} artifact_member is invalid")
            artifact_fields = (artifact_prefix, artifact_member)
            if prefix is not None and any(value is None for value in artifact_fields):
                raise ValueError(f"provider {provider_id} {capability} custom check artifact contract is incomplete")
            if prefix is None and any(value is not None for value in artifact_fields):
                raise ValueError(f"provider {provider_id} {capability} artifact contract requires external_id_prefix")
            measurements_prefix = check.get("measurements_artifact_prefix")
            measurements_member = check.get("measurements_member")
            if measurements_prefix is not None and (
                not isinstance(measurements_prefix, str)
                or re.fullmatch(r"[A-Za-z0-9._-]+", measurements_prefix) is None
                or len(measurements_prefix) > 150
            ):
                raise ValueError(f"provider {provider_id} {capability} measurements_artifact_prefix is invalid")
            if measurements_member is not None and (
                not isinstance(measurements_member, str)
                or re.fullmatch(r"[A-Za-z0-9._-]+", measurements_member) is None
                or len(measurements_member) > 100
            ):
                raise ValueError(f"provider {provider_id} {capability} measurements_member is invalid")
            if (measurements_prefix is None) != (measurements_member is None):
                raise ValueError(f"provider {provider_id} {capability} measurements contract is incomplete")
            if measurements_prefix is not None and (
                capability not in MEASURED_CONTROLS or workflow_path is None or prefix is not None
            ):
                raise ValueError(
                    f"provider {provider_id} {capability} measurements require a measured control and a pull_request workflow_path"
                )
            if prefix is not None and workflow_path is None:
                raise ValueError(f"provider {provider_id} {capability} artifact contract requires workflow_path")
        reviews = provider.get("reviews", {})
        if not isinstance(reviews, dict) or any(capability not in capabilities for capability in reviews):
            raise ValueError(f"provider {provider_id} reviews are invalid")
        overlapping_contracts = sorted(set(checks).intersection(reviews))
        if overlapping_contracts:
            raise ValueError(
                f"provider {provider_id} {overlapping_contracts[0]} cannot declare both a check and a review"
            )
        for capability, review in reviews.items():
            if not isinstance(review, dict) or set(review) != {"review_author"}:
                raise ValueError(f"provider {provider_id} {capability} review is invalid")
            author = review["review_author"]
            if (
                not isinstance(author, str)
                or len(author) > 100
                or review_author_pattern.fullmatch(author) is None
            ):
                raise ValueError(f"provider {provider_id} {capability} review_author is invalid")
        template = provider.get("template")
        if template is not None:
            expected_path = f".github/workflows/{Path(template).name}"
            for capability, check in checks.items():
                if check.get("workflow_path") != expected_path:
                    raise ValueError(
                        f"provider {provider_id} {capability} workflow_path must be {expected_path}"
                    )
    runnable = {control_id for control_id, control in controls.items() if control["availability"] == "runnable"}
    if set(selections) != runnable:
        raise ValueError("provider selections must cover exactly the runnable controls")
    for control_id, selection in selections.items():
        if not isinstance(selection, dict) or set(selection) != {"authoritative", "supplemental"}:
            raise ValueError(f"selection {control_id} is invalid")
        authority = selection["authoritative"]
        supplemental = selection["supplemental"]
        if authority not in providers or control_id not in providers[authority]["capabilities"]:
            raise ValueError(f"selection {control_id} has an invalid authoritative provider")
        if not isinstance(supplemental, list) or len(supplemental) != len(set(supplemental)):
            raise ValueError(f"selection {control_id} has duplicate supplemental providers")
        if authority in supplemental:
            raise ValueError(f"selection {control_id} authority is also supplemental")
        for provider_id in supplemental:
            if provider_id not in providers or control_id not in providers[provider_id]["capabilities"]:
                raise ValueError(f"selection {control_id} has an invalid supplemental provider")
    return providers, selections


def validate_policy(policy: dict[str, Any], profile_ids: set[str], controls: dict[str, dict[str, Any]]) -> None:
    if policy.get("version") != 2:
        raise ValueError("policy.version must be 2")
    selected = policy.get("profiles")
    if not isinstance(selected, list) or not selected or len(selected) != len(set(selected)):
        raise ValueError("policy profiles must be a non-empty unique list")
    unknown = [profile for profile in selected if profile not in profile_ids]
    if unknown:
        raise ValueError(f"policy references unknown profile: {unknown[0]}")
    overrides = policy.get("overrides")
    if not isinstance(overrides, dict) or set(overrides) != set(OPERATIONS):
        raise ValueError("policy overrides must define change and release")
    for operation, modes in overrides.items():
        if not isinstance(modes, dict):
            raise ValueError(f"policy {operation} overrides must be an object")
        for control_id, mode in modes.items():
            if control_id not in controls:
                raise ValueError(f"policy references unknown control: {control_id}")
            if controls[control_id]["availability"] != "runnable":
                raise ValueError(f"policy cannot select evidence-only control: {control_id}")
            if not operation_supports_stage(operation, controls[control_id]["stage"]):
                raise ValueError(f"{control_id} cannot be configured for {operation}")
            if mode not in MODES:
                raise ValueError(f"policy override for {control_id} is invalid")
            if mode == "enforced" and controls[control_id]["enforcement_policy"] == "advisory-only":
                raise ValueError(f"{control_id} is advisory-only and cannot be enforced")


CHECK_CONCLUSIONS = {
    "success": "passed", "failure": "failed", "cancelled": "blocked",
    "timed_out": "blocked", "action_required": "blocked", "stale": "blocked",
    "neutral": "not_run", "skipped": "not_run",
}
CHECK_TIMESTAMP_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"


def check_timestamp(value: Any) -> datetime:
    """Parse bounded, timezone-aware RFC3339 execution timestamps."""
    if not isinstance(value, str) or re.fullmatch(CHECK_TIMESTAMP_PATTERN, value) is None:
        raise ValueError("check_execution timestamp is invalid")
    # datetime normalizes oversized offset minutes; reject those explicitly.
    if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError("check_execution timezone offset is invalid")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_check_execution(value: Any, status: str) -> None:
    """Validate optional execution facts independently of enforcement mode."""
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "started_at", "completed_at", "duration_seconds", "conclusion"}
        or type(value["version"]) is not int or value["version"] != 1
        or not isinstance(value["conclusion"], str)
        or value["conclusion"] not in CHECK_CONCLUSIONS
        or CHECK_CONCLUSIONS[value["conclusion"]] != status
        or type(value["duration_seconds"]) is not int
        or not 0 <= value["duration_seconds"] <= 2**53 - 1
    ):
        raise ValueError("check_execution metadata contract is invalid")
    elapsed = (check_timestamp(value["completed_at"]) - check_timestamp(value["started_at"])).total_seconds()
    if elapsed < 0 or int(elapsed) != value["duration_seconds"]:
        raise ValueError("check_execution duration is inconsistent")


def validate_change_scope(value: Any, status: str) -> None:
    """Validate optional display metrics without changing control evaluation policy."""
    metric_limits = {
        "files": "max_files",
        "added_lines": "max_added_lines",
        "changed_lines": "max_changed_lines",
        "max_added_lines_per_file": "max_added_lines_per_file",
    }
    metric_keys = set(metric_limits) | {
        "binary_files", "total_files", "total_added_lines", "total_changed_lines",
        "excluded_files", "excluded_added_lines", "excluded_changed_lines",
        "excluded_binary_files",
    }
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "metrics", "thresholds"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or status not in {"passed", "failed"}
    ):
        raise ValueError("change_scope metadata contract is invalid")
    metrics, thresholds = value["metrics"], value["thresholds"]
    for values, keys in ((metrics, metric_keys), (thresholds, set(metric_limits.values()))):
        if (
            not isinstance(values, dict)
            or set(values) != keys
            or any(type(number) is not int or not 0 <= number <= 2**53 - 1 for number in values.values())
        ):
            raise ValueError("change_scope metrics or thresholds are invalid")
    if any(number == 0 for number in thresholds.values()):
        raise ValueError("change_scope thresholds must be positive")
    for key in ("files", "added_lines", "changed_lines"):
        if metrics[f"total_{key}"] != metrics[key] + metrics[f"excluded_{key}"]:
            raise ValueError("change_scope totals are inconsistent")
    for prefix in ("", "excluded_"):
        files = metrics[f"{prefix}files"]
        binary = metrics[f"{prefix}binary_files"]
        added = metrics[f"{prefix}added_lines"]
        changed = metrics[f"{prefix}changed_lines"]
        if binary > files or added > changed or (files == binary and changed != 0):
            raise ValueError("change_scope counts are inconsistent")
    maximum = metrics["max_added_lines_per_file"]
    text_files = metrics["files"] - metrics["binary_files"]
    if maximum > metrics["added_lines"] or metrics["added_lines"] > maximum * text_files:
        raise ValueError("change_scope per-file maximum is inconsistent")
    exceeded = any(metrics[metric] > thresholds[limit] for metric, limit in metric_limits.items())
    if exceeded != (status == "failed"):
        raise ValueError("change_scope status does not match thresholds")


PR_METADATA_MAX_SECTIONS = 20


def validate_pr_metadata(value: Any, status: str) -> None:
    """Validate optional trusted display detail; counts only, never PR text."""
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "title_matches", "required_sections", "missing_sections"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["title_matches"]) is not bool
        or status not in {"passed", "failed"}
    ):
        raise ValueError("pr_metadata detail contract is invalid")
    required, missing = value["required_sections"], value["missing_sections"]
    if (
        type(required) is not int or type(missing) is not int
        or not 0 <= missing <= required <= PR_METADATA_MAX_SECTIONS
    ):
        raise ValueError("pr_metadata section counts are invalid")
    if (value["title_matches"] and missing == 0) != (status == "passed"):
        raise ValueError("pr_metadata status does not match its detail")


# Self-reported measurements come from the pull request's own workflow run, so they
# are display-only: they never change a result status and are labeled as such.
MEASURED_CONTROLS = {
    "unit-tests": "tests",
    "changed-code-coverage": "coverage",
    "repository-validation": "contracts",
    "documentation-validation": "documentation",
    "repository-ground-truth": "documents",
    "migration-validation": "migrations",
    # AI reviews count the reviewer's own result file; the findings are the AI's judgment.
    "ai-engineering-review": "review_findings",
    "ai-qa-review": "review_findings",
    "ai-security-review": "review_findings",
    "ai-repository-standards-review": "review_findings",
    "custom-static-analysis": "findings",
    "secret-detection": "findings",
    "deep-sast": "findings",
    "dependency-vulnerability": "findings",
}
MEASUREMENT_FIELDS = {
    "tests": {"total", "passed", "failed", "skipped"},
    "coverage": {"measured_lines", "covered_lines", "threshold_percent"},
    "contracts": {"total", "passed", "failed", "not_run"},
    "documentation": {"markdown_files", "links_checked", "broken_links", "mapping_failures"},
    "documents": {"declared", "found", "missing"},
    "migrations": {"checked", "failed"},
    "review_findings": {"total", "p0", "p1", "p2", "p3", "unresolved_blocking"},
    # Scanner findings by severity bucket; "unrated" holds findings the tool does not rate.
    "findings": {"total", "critical", "high", "medium", "low", "unrated"},
}


def _measurement_problem(kind: str, numbers: dict[str, int], status: str) -> str | None:
    """Return why measurements are inconsistent with themselves or the status, or None."""
    if kind == "tests":
        if numbers["total"] != numbers["passed"] + numbers["failed"] + numbers["skipped"] or numbers["total"] == 0:
            return "test measurements are inconsistent"
        if status == "passed" and numbers["failed"]:
            return "test measurements contradict a passed status"
    elif kind == "coverage":
        if numbers["covered_lines"] > numbers["measured_lines"] or numbers["threshold_percent"] > 100:
            return "coverage measurements are inconsistent"
        below = numbers["covered_lines"] * 100 < numbers["threshold_percent"] * numbers["measured_lines"]
        if status == "passed" and below:
            return "coverage measurements contradict a passed status"
    elif kind == "contracts":
        if numbers["total"] != numbers["passed"] + numbers["failed"] + numbers["not_run"] or numbers["total"] == 0:
            return "contract measurements are inconsistent"
        if (status == "passed") != (numbers["failed"] == 0 and numbers["not_run"] == 0):
            return "contract measurements contradict the status"
        if status == "failed" and not numbers["failed"]:
            return "contract measurements contradict a failed status"
    elif kind == "documentation":
        if numbers["broken_links"] > numbers["links_checked"]:
            return "documentation measurements are inconsistent"
        if (status == "passed") != (numbers["broken_links"] + numbers["mapping_failures"] == 0):
            return "documentation measurements contradict the status"
    elif kind == "documents":
        if numbers["declared"] != numbers["found"] + numbers["missing"]:
            return "document measurements are inconsistent"
        if (status == "passed") != (numbers["missing"] == 0):
            return "document measurements contradict the status"
    elif kind == "migrations":
        if numbers["failed"] > numbers["checked"]:
            return "migration measurements are inconsistent"
        if status == "passed" and numbers["failed"]:
            return "migration measurements contradict a passed status"
    elif kind == "review_findings":
        # Not coupled to status: the check reflects the adapter's exit status, and an
        # adapter may fail for reasons other than a counted finding.
        blocking = numbers["p0"] + numbers["p1"]
        if numbers["total"] != blocking + numbers["p2"] + numbers["p3"] or numbers["unresolved_blocking"] > blocking:
            return "review finding measurements are inconsistent"
    elif kind == "findings":
        # Arithmetic only: a scan may pass with findings below the tool's own threshold,
        # and may fail for reasons other than a counted finding.
        buckets = ("critical", "high", "medium", "low", "unrated")
        if numbers["total"] != sum(numbers[bucket] for bucket in buckets):
            return "finding measurements are inconsistent"
    return None


def validate_measurements(control_id: str, value: Any, status: str) -> None:
    """Validate optional self-reported measurements for a measured control."""
    kind = MEASURED_CONTROLS.get(control_id)
    if (
        kind is None
        or status not in {"passed", "failed"}
        or not isinstance(value, dict)
        or set(value) != {"version", "source", kind}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["source"] != "pull-request-workflow"
    ):
        raise ValueError("measurements metadata contract is invalid")
    numbers = value[kind]
    if (
        not isinstance(numbers, dict)
        or set(numbers) != MEASUREMENT_FIELDS[kind]
        or any(type(number) is not int or not 0 <= number <= 2**53 - 1 for number in numbers.values())
    ):
        raise ValueError("measurements values are invalid")
    problem = _measurement_problem(kind, numbers, status)
    if problem:
        raise ValueError(problem)


def validate_evidence(
    evidence: dict[str, Any],
    controls: dict[str, dict[str, Any]],
    providers: dict[str, dict[str, Any]],
) -> None:
    if evidence.get("version") != 2 or set(evidence) not in (
        {"version", "subject", "results"},
        {"$schema", "version", "subject", "results"},
    ):
        raise ValueError("evidence must use the v2 nested evidence contract")
    subject = evidence.get("subject")
    if not isinstance(subject, dict) or set(subject) != {"type", "revision"}:
        raise ValueError("evidence subject is invalid")
    if subject["type"] not in {"git-commit", "artifact", "environment", "pull-request"}:
        raise ValueError("evidence subject type is invalid")
    if not isinstance(subject["revision"], str) or not subject["revision"].strip() or len(subject["revision"]) > 200:
        raise ValueError("evidence subject revision is invalid")
    results = evidence.get("results")
    if not isinstance(results, dict):
        raise ValueError("evidence results must be an object")
    for control_id, provider_results in results.items():
        if control_id not in controls or not isinstance(provider_results, dict) or not provider_results:
            raise ValueError(f"evidence control {control_id} is invalid")
        if subject["type"] != controls[control_id]["evidence_subject"]:
            raise ValueError(f"evidence {control_id} requires {controls[control_id]['evidence_subject']} subject")
        for provider_id, result in provider_results.items():
            if provider_id not in providers:
                raise ValueError(f"evidence references unknown provider: {provider_id}")
            if control_id not in providers[provider_id]["capabilities"]:
                raise ValueError(f"provider {provider_id} does not provide {control_id}")
            if not isinstance(result, dict) or set(result) - {"producer", "status", "evidence", "reason", "change_scope", "pr_metadata", "check_execution", "measurements"}:
                raise ValueError(f"evidence {control_id}.{provider_id} is invalid")
            if (
                not isinstance(result.get("producer"), str)
                or not result["producer"].strip()
                or len(result["producer"]) > 200
            ):
                raise ValueError(f"evidence {control_id}.{provider_id} producer is invalid")
            status = result.get("status")
            if status not in STATUSES:
                raise ValueError(f"evidence {control_id}.{provider_id} status is invalid")
            if "check_execution" in result:
                validate_check_execution(result["check_execution"], status)
            if "change_scope" in result:
                if (control_id, provider_id) != ("change-scope", "repository-change-scope"):
                    raise ValueError("change_scope metadata is only valid for change-scope.repository-change-scope")
                validate_change_scope(result["change_scope"], status)
            if "pr_metadata" in result:
                if (control_id, provider_id) != ("pr-metadata", "repository-pr-metadata"):
                    raise ValueError("pr_metadata detail is only valid for pr-metadata.repository-pr-metadata")
                validate_pr_metadata(result["pr_metadata"], status)
            if "measurements" in result:
                validate_measurements(control_id, result["measurements"], status)
            records = result.get("evidence")
            if status in {"passed", "failed"} and (
                not isinstance(records, list) or not records or any(not isinstance(item, str) or not item.strip() for item in records)
            ):
                raise ValueError(f"evidence {control_id}.{provider_id} evidence records are required")
            if records is not None and (
                not isinstance(records, list)
                or not records
                or any(
                    not isinstance(item, str) or not item.strip() or len(item) > 1_000
                    for item in records
                )
            ):
                raise ValueError(f"evidence {control_id}.{provider_id} evidence records are invalid")
            reason = result.get("reason")
            if reason is not None and (
                not isinstance(reason, str) or not reason.strip() or len(reason) > 1_000
            ):
                raise ValueError(f"evidence {control_id}.{provider_id} reason is invalid")
            if status in {"blocked", "not_run"} and (
                not isinstance(reason, str) or not reason.strip()
            ):
                raise ValueError(f"evidence {control_id}.{provider_id} reason is required")


def operation_applies(control: dict[str, Any], operation: str, subject_type: str) -> bool:
    return (
        operation_supports_stage(operation, control.get("stage", ""))
        and control.get("evidence_subject") == subject_type
    )


def effective_controls(
    policy: dict[str, Any],
    profiles: dict[str, Any],
    catalog: dict[str, Any],
    provider_config: dict[str, Any],
    operation: str,
    subject_type: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    controls = catalog_map(catalog)
    profile_definitions = validate_profiles(profiles, controls)
    providers, selections = validate_provider_config(provider_config, controls)
    validate_policy(policy, set(profile_definitions), controls)
    if operation not in OPERATIONS:
        raise ValueError(f"unknown operation: {operation}")

    defaults: dict[str, str] = {}
    for profile_id in policy["profiles"]:
        for control_id, mode in profile_definitions[profile_id]["defaults"][operation].items():
            previous = defaults.get(control_id)
            if previous is not None and previous != mode:
                raise ValueError(f"conflicting profile defaults for {control_id}")
            defaults[control_id] = mode
    modes = {**defaults, **policy["overrides"][operation]}
    selected: dict[str, dict[str, Any]] = {}
    for control_id, mode in modes.items():
        if mode == "not_activated" or not operation_applies(controls[control_id], operation, subject_type):
            continue
        selection = selections[control_id]
        selected[control_id] = {
            "mode": mode,
            "authoritative": selection["authoritative"],
            "supplemental": list(selection["supplemental"]),
        }
    return selected, controls, providers


def evaluate(
    policy: dict[str, Any],
    profiles: dict[str, Any],
    catalog: dict[str, Any],
    provider_config: dict[str, Any],
    evidence: dict[str, Any],
    operation: str,
    expected_revision: str,
    expected_subject_type: str,
    *,
    all_catalog_controls: bool = False,
    companions: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evaluate one primary subject plus optional companion subjects.

    A companion is ``(subject_type, expected_revision, evidence)`` and scores
    the controls bound to that subject type, such as mutable pull-request
    metadata beside commit-bound checks. Each evidence document must exactly
    match its own expected subject.
    """
    subjects = [(expected_subject_type, expected_revision, evidence), *(companions or [])]
    if len({subject_type for subject_type, _, _ in subjects}) != len(subjects):
        raise ValueError("each evaluated subject type may appear only once")
    selected: dict[str, dict[str, Any]] = {}
    sources: dict[str, tuple[dict[str, Any], bool]] = {}
    findings: list[dict[str, Any]] = []
    all_subjects_match = True
    for subject_type, revision, document in subjects:
        if not revision or len(revision) > 200:
            raise ValueError("expected revision must be 1-200 characters")
        if subject_type not in {"git-commit", "artifact", "environment", "pull-request"}:
            raise ValueError("expected subject type is invalid")
        subject_selected, controls, providers = effective_controls(
            policy, profiles, catalog, provider_config, operation, subject_type
        )
        validate_evidence(document, controls, providers)
        matches = document["subject"] == {"type": subject_type, "revision": revision}
        if not matches:
            all_subjects_match = False
            findings.append({
                "kind": "subject_mismatch",
                "status": "mismatch",
                "expected_subject": {"type": subject_type, "revision": revision},
                "observed_subject": dict(document["subject"]),
                "message": "evidence subject type and revision must exactly match the evaluated subject",
            })
        for control_id, selection in subject_selected.items():
            selected[control_id] = selection
            sources[control_id] = (document, matches)
    subject = evidence["subject"]
    evaluated_subject_types = {subject_type for subject_type, _, _ in subjects}

    rows: list[dict[str, Any]] = []
    counts = {mode: {"passed": 0, "total": 0} for mode in ("enforced", "advisory")}
    control_ids = list(controls) if all_catalog_controls else list(selected)
    for control_id in control_ids:
        control = controls[control_id]
        selection = selected.get(control_id)
        if selection is None:
            row = {
                "id": control_id,
                "name": control.get("name", control_id),
                "effective_mode": "not_activated",
                "authoritative_provider": None,
                "authoritative_evidence_status": "missing",
                "readiness": "GRAY",
                "supplemental": [],
            }
            control_subject = control.get("evidence_subject")
            if control_subject not in evaluated_subject_types and control_id in effective_controls(
                policy, profiles, catalog, provider_config, operation, control_subject
            )[0]:
                # Policy activates this control, but on a subject this evaluation did not score.
                row["inactive_reason"] = "other_subject"
                row["evidence_subject"] = control_subject
            rows.append(row)
            continue
        mode = selection["mode"]
        authority_id = selection["authoritative"]
        source, subject_matches = sources[control_id]
        authority_result = (
            source["results"].get(control_id, {}).get(authority_id)
            if subject_matches
            else None
        )
        authority_status = authority_result.get("status", "missing") if authority_result else "missing"
        passed = subject_matches and authority_status == "passed"
        counts[mode]["total"] += 1
        if passed:
            counts[mode]["passed"] += 1
        readiness = "GREEN" if passed else "RED" if mode == "enforced" else "ORANGE"
        supplemental = []
        for provider_id in selection["supplemental"]:
            provider_result = (
                source["results"].get(control_id, {}).get(provider_id)
                if subject_matches
                else None
            )
            supplemental.append({
                "id": provider_id,
                "display_name": providers[provider_id]["display_name"],
                "status": provider_result.get("status", "missing") if provider_result else "missing",
                "result": provider_result,
                "advisory": True,
            })
        row = {
            "id": control_id,
            "name": control.get("name", control_id),
            "effective_mode": mode,
            "authoritative_provider": {"id": authority_id, "display_name": providers[authority_id]["display_name"]},
            "authoritative_evidence_status": authority_status,
            "authoritative_result": authority_result,
            "readiness": readiness,
            "supplemental": supplemental,
        }
        rows.append(row)
        if not passed:
            findings.append({
                "kind": "authoritative_result",
                "control_id": control_id,
                "provider_id": authority_id,
                "mode": mode,
                "status": authority_status,
                "message": f"only fresh passed evidence from {providers[authority_id]['display_name']} satisfies {control.get('name', control_id)}",
            })

    blocked = not all_subjects_match or any(row["readiness"] == "RED" for row in rows)
    status = "RED" if blocked else "ORANGE" if any(row["readiness"] == "ORANGE" for row in rows) else "GREEN"
    result = {
        "version": 2,
        "decision": "block" if blocked else "allow",
        "status": status,
        "policy": policy["name"],
        "operation": operation,
        "subject": subject,
        "summary": counts,
        "controls": rows,
        "findings": findings,
    }
    if companions:
        result["companion_subjects"] = [dict(document["subject"]) for _, _, document in companions]
    return result


def render(result: dict[str, Any]) -> str:
    subject = result["subject"]
    lines = [
        f"{result['decision'].upper()} {result['operation']} {subject['type']}@{subject['revision']}",
        f"Status: {result['status']}",
        f"Enforced: {result['summary']['enforced']['passed']}/{result['summary']['enforced']['total']} passed",
        f"Advisory: {result['summary']['advisory']['passed']}/{result['summary']['advisory']['total']} passed",
    ]
    for row in result["controls"]:
        provider = row["authoritative_provider"]
        provider_name = provider["display_name"] if provider else "Not activated"
        lines.append(f"- {row['readiness']} {row['name']} — {provider_name}: {row['authoritative_evidence_status']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Proof evidence")
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--providers", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--operation", required=True, choices=OPERATIONS)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--subject-type", required=True, choices=("git-commit", "artifact", "environment", "pull-request"))
    parser.add_argument("--all-catalog-controls", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate(
            load_document(args.policy), load_document(args.profiles), load_document(args.catalog),
            load_document(args.providers), load_document(args.evidence), args.operation,
            args.revision, args.subject_type, all_catalog_controls=args.all_catalog_controls,
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) + "\n" if args.json else render(result), end="")
    return 0 if result["decision"] == "allow" else 1


if __name__ == "__main__":
    raise SystemExit(main())
