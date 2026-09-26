#!/usr/bin/env python3
"""Collect nested Guardrails v2 evidence from GitHub checks and PR reviews."""

from __future__ import annotations

import argparse
import copy
import io
import importlib.util
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONCLUSIONS = {
    "success": "passed",
    "failure": "failed",
    "cancelled": "blocked",
    "timed_out": "blocked",
    "action_required": "blocked",
    "stale": "blocked",
    "neutral": "not_run",
    "skipped": "not_run",
}
MAX_ARTIFACT_ARCHIVE_BYTES = 1_000_000
MAX_ARTIFACT_MEMBER_BYTES = 64_000
MAX_PRODUCER_LENGTH = 200
MAX_EVIDENCE_RECORD_LENGTH = 1_000
MAX_REASON_LENGTH = 1_000
CHECK_RUNS_PER_PAGE = 100
MAX_CHECK_RUN_PAGES = 10
PULL_REQUEST_REVIEWS_PER_PAGE = 100
MAX_PULL_REQUEST_REVIEW_PAGES = 10
ARTIFACT_STATUSES = {"passed", "failed", "not_run"}


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def bounded_text(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    marker = "...[truncated]..."
    leading = (maximum - len(marker)) // 2
    trailing = maximum - len(marker) - leading
    return value[:leading] + marker + value[-trailing:]


def bounded_record(value: str) -> str:
    return bounded_text(value, MAX_EVIDENCE_RECORD_LENGTH)


def bounded_result(result: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(result)
    bounded["producer"] = bounded_text(bounded["producer"], MAX_PRODUCER_LENGTH)
    if "reason" in bounded:
        bounded["reason"] = bounded_text(bounded["reason"], MAX_REASON_LENGTH)
    if "evidence" in bounded:
        bounded["evidence"] = [bounded_record(record) for record in bounded["evidence"]]
    return bounded


def evaluator_module() -> Any:
    path = ROOT / "guardrails" / "evaluate.py"
    if not path.exists():
        path = ROOT / ".guardrails" / "evaluate.py"
    spec = importlib.util.spec_from_file_location("guardrails_v2_evaluator", path)
    if not spec or not spec.loader:
        raise ValueError(f"cannot load evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def check_run_evidence(control_id: str, provider_name: str, check: dict[str, Any]) -> dict[str, Any]:
    conclusion = check.get("conclusion") or "in_progress"
    status = CONCLUSIONS.get(conclusion, "not_run")
    url = check.get("html_url") or check.get("details_url") or "unavailable"
    result: dict[str, Any] = {
        "producer": f"GitHub Check: {check.get('name', provider_name)}",
        "status": status,
    }
    if status in {"passed", "failed"}:
        result["evidence"] = [f"{check.get('name', control_id)}: {conclusion}; {url}"]
    else:
        result["reason"] = f"GitHub check concluded {conclusion}; the provider did not return a passing result."
        if check.get("name"):
            result["evidence"] = [f"{check['name']}: {conclusion}; {url}"]
    return bounded_result(result)


def _request(url: str, token: str) -> Any:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def _request_bytes(url: str, token: str) -> bytes:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        build_opener(NoRedirectHandler()).open(request, timeout=20)
    except HTTPError as error:
        if error.code != 302:
            raise
        location = error.headers.get("Location")
    else:
        raise ValueError("artifact archive endpoint did not return the expected redirect")
    parsed = urlparse(location or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("artifact archive redirect Location must be an absolute HTTPS URL")
    unsigned_request = Request(location, headers={"Accept": "application/octet-stream"})
    with urlopen(unsigned_request, timeout=20) as response:
        content = response.read(MAX_ARTIFACT_ARCHIVE_BYTES + 1)
    if len(content) > MAX_ARTIFACT_ARCHIVE_BYTES:
        raise ValueError("artifact archive exceeds the safe size limit")
    return content


def expected_checks(
    policy: dict[str, Any], profiles: dict[str, Any], catalog: dict[str, Any],
    provider_config: dict[str, Any], operation: str,
) -> dict[str, dict[str, Any]]:
    selected, _, providers = evaluator_module().effective_controls(
        policy, profiles, catalog, provider_config, operation, "git-commit"
    )
    expected: dict[str, dict[str, Any]] = {}
    for control_id, selection in selected.items():
        for provider_id in [selection["authoritative"], *selection["supplemental"]]:
            check = providers[provider_id].get("checks", {}).get(control_id)
            if check:
                check_name = check["check_name"]
                contract = {
                    "check_name": check_name,
                    "workflow": check["workflow"],
                    "provider_id": provider_id,
                    "control_ids": [control_id],
                }
                if "external_id_prefix" in check:
                    contract["external_id_prefix"] = check["external_id_prefix"]
                if "workflow_path" in check:
                    contract["workflow_path"] = check["workflow_path"]
                if "trusted_paths" in check:
                    contract["trusted_paths"] = check["trusted_paths"]
                if "app_slug" in check:
                    contract["app_slug"] = check["app_slug"]
                if "artifact_name_prefix" in check:
                    contract["artifact_name_prefix"] = check["artifact_name_prefix"]
                if "artifact_member" in check:
                    contract["artifact_member"] = check["artifact_member"]
                existing = expected.get(check_name)
                if existing is not None and (
                    existing["provider_id"] != provider_id
                    or existing["workflow"] != check["workflow"]
                    or existing.get("external_id_prefix") != check.get("external_id_prefix")
                    or existing.get("workflow_path") != check.get("workflow_path")
                    or existing.get("trusted_paths") != check.get("trusted_paths")
                    or existing.get("app_slug") != check.get("app_slug")
                    or existing.get("artifact_name_prefix") != check.get("artifact_name_prefix")
                    or existing.get("artifact_member") != check.get("artifact_member")
                ):
                    raise ValueError(
                        f"ambiguous check name {check_name!r} is reused by different workflow/provider contracts"
                    )
                if existing is None:
                    expected[check_name] = contract
                elif control_id not in existing["control_ids"]:
                    existing["control_ids"].append(control_id)
    return expected


def expected_reviews(
    policy: dict[str, Any], profiles: dict[str, Any], catalog: dict[str, Any],
    provider_config: dict[str, Any], operation: str,
) -> list[dict[str, Any]]:
    selected, _, providers = evaluator_module().effective_controls(
        policy, profiles, catalog, provider_config, operation, "git-commit"
    )
    expected: list[dict[str, Any]] = []
    for control_id, selection in selected.items():
        for provider_id in [selection["authoritative"], *selection["supplemental"]]:
            review = providers[provider_id].get("reviews", {}).get(control_id)
            if review:
                expected.append({
                    "control_id": control_id,
                    "provider_id": provider_id,
                    "provider_name": providers[provider_id]["display_name"],
                    "review_author": review["review_author"],
                })
    return expected


def not_run(check_name: str, reason: str) -> dict[str, Any]:
    return bounded_result({
        "producer": f"GitHub Check: {check_name}",
        "status": "not_run",
        "reason": reason,
    })


def check_matches_declared_app(check: dict[str, Any], contract: dict[str, Any]) -> bool:
    """Return whether a same-name check came from the contract's declared app class."""
    app = check.get("app")
    actual_slug = app.get("slug") if isinstance(app, dict) else None
    app_slug = contract.get("app_slug")
    if isinstance(app_slug, str) and app_slug:
        return actual_slug == app_slug
    if contract.get("workflow_path"):
        return actual_slug == "github-actions"
    return True


def enumerate_check_runs(
    repo: str, revision: str, token: str, check_name: str,
) -> list[dict[str, Any]]:
    encoded_name = quote(check_name, safe="")
    check_runs: list[dict[str, Any]] = []
    validated_total: int | None = None
    for page in range(1, MAX_CHECK_RUN_PAGES + 1):
        payload = _request(
            f"https://api.github.com/repos/{repo}/commits/{revision}/check-runs"
            f"?check_name={encoded_name}&filter=all&per_page={CHECK_RUNS_PER_PAGE}&page={page}",
            token,
        )
        if not isinstance(payload, dict):
            raise ValueError("check-run response must be an object")
        total_count = payload.get("total_count")
        page_runs = payload.get("check_runs")
        if (
            not isinstance(total_count, int)
            or isinstance(total_count, bool)
            or total_count < 0
            or not isinstance(page_runs, list)
            or any(not isinstance(check, dict) for check in page_runs)
        ):
            raise ValueError("check-run response is malformed")
        if validated_total is None:
            validated_total = total_count
            required_pages = max(1, (validated_total + CHECK_RUNS_PER_PAGE - 1) // CHECK_RUNS_PER_PAGE)
            if required_pages > MAX_CHECK_RUN_PAGES:
                raise ValueError("check-run enumeration exceeds the safe page limit")
        elif total_count != validated_total:
            raise ValueError("check-run total_count changed during pagination")
        remaining = validated_total - len(check_runs)
        expected_page_size = min(CHECK_RUNS_PER_PAGE, max(0, remaining))
        if len(page_runs) != expected_page_size:
            raise ValueError("check-run page size is inconsistent with total_count")
        check_runs.extend(page_runs)
        if len(check_runs) == validated_total:
            return check_runs
    raise ValueError("check-run enumeration exceeded the safe page limit")


def enumerate_pull_request_reviews(
    repo: str, pull_request_number: int, token: str,
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for page in range(1, MAX_PULL_REQUEST_REVIEW_PAGES + 1):
        payload = _request(
            f"https://api.github.com/repos/{repo}/pulls/{pull_request_number}/reviews"
            f"?per_page={PULL_REQUEST_REVIEWS_PER_PAGE}&page={page}",
            token,
        )
        if not isinstance(payload, list) or any(
            not isinstance(review, dict) for review in payload
        ):
            raise ValueError("pull-request review response must be a list of objects")
        reviews.extend(payload)
        if len(payload) < PULL_REQUEST_REVIEWS_PER_PAGE:
            return reviews
    raise ValueError("pull-request review enumeration exceeds the safe page limit")


def collect_review_evidence(
    repo: str,
    revision: str,
    token: str,
    pull_request_number: int | None,
    contract: dict[str, Any],
    provider_name: str,
) -> dict[str, Any]:
    if pull_request_number is None:
        return not_run(
            provider_name,
            "A pull-request number is required to collect GitHub review evidence.",
        )
    reviews = enumerate_pull_request_reviews(repo, pull_request_number, token)
    author = contract["review_author"]
    matching = [
        review
        for review in reviews
        if review.get("commit_id") == revision
        and isinstance(review.get("user"), dict)
        and review["user"].get("login") == author
        and review["user"].get("type") == "Bot"
        and review.get("state") in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}
    ]
    if not matching:
        return not_run(
            provider_name,
            "No completed GitHub review matched the exact head and reviewer identity.",
        )
    review = max(
        matching,
        key=lambda item: (
            str(item.get("submitted_at") or ""),
            str(item.get("id") or ""),
        ),
    )
    url = review.get("html_url") or "unavailable"
    status = "failed" if review["state"] == "CHANGES_REQUESTED" else "passed"
    return bounded_result({
        "producer": f"GitHub Review: {provider_name}",
        "status": status,
        "evidence": [f"{provider_name}: {review['state']}; {url}"],
    })


def workflow_path_matches(expected: str, actual: Any) -> bool:
    return isinstance(actual, str) and (
        actual == expected
        or (actual.startswith(f"{expected}@") and len(actual) > len(expected) + 1)
    )


def trusted_paths_match_trusted_base(
    repo: str,
    trusted_paths: list[str],
    revision: str,
    trusted_base_revision: str,
    token: str,
) -> bool:
    for path in trusted_paths:
        encoded_path = quote(path, safe="/")
        candidate = _request(
            f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
            f"?ref={quote(revision, safe='')}",
            token,
        )
        trusted = _request(
            f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
            f"?ref={quote(trusted_base_revision, safe='')}",
            token,
        )
        candidate_sha = candidate.get("sha") if isinstance(candidate, dict) else None
        trusted_sha = trusted.get("sha") if isinstance(trusted, dict) else None
        if not (
            isinstance(candidate_sha, str)
            and bool(candidate_sha)
            and candidate_sha == trusted_sha
        ):
            return False
    return True


def artifact_document(archive_bytes: bytes, member: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            matches = [info for info in archive.infolist() if info.filename == member]
            if len(matches) != 1:
                raise ValueError("artifact member is missing or duplicated")
            if matches[0].file_size > MAX_ARTIFACT_MEMBER_BYTES:
                raise ValueError("artifact member exceeds the safe size limit")
            payload = archive.read(matches[0])
    except zipfile.BadZipFile as error:
        raise ValueError("artifact archive is not a valid zip file") from error
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("artifact member is not valid JSON") from error
    if not isinstance(document, dict):
        raise ValueError("artifact member must contain a JSON object")
    return document


def run_artifact_evidence(
    repo: str,
    revision: str,
    token: str,
    run_id: int,
    contract: dict[str, Any],
    check: dict[str, Any],
    provider_name: str,
    trusted_base_revision: str,
    trusted_workflow_ref: str,
) -> dict[str, Any]:
    check_name = contract["check_name"]
    artifact_prefix = contract.get("artifact_name_prefix")
    member = contract.get("artifact_member")
    provider_id = contract.get("provider_id")
    if not all(isinstance(value, str) and value for value in (artifact_prefix, member, provider_id)):
        return not_run(check_name, "The custom check artifact contract is incomplete.")
    expected_name = f"{artifact_prefix}{run_id}"
    try:
        listing = _request(
            f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"
            f"?name={quote(expected_name, safe='')}&per_page=100",
            token,
        )
    except (HTTPError, URLError, OSError, ValueError):
        return not_run(check_name, "The run-bound evidence artifact could not be listed.")
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        return not_run(check_name, "The run-bound evidence artifact listing is malformed.")
    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("name") == expected_name
    ]
    if listing.get("total_count") != 1 or len(matches) != 1:
        return not_run(check_name, "Exactly one expected run-bound evidence artifact is required.")
    artifact = matches[0]
    if artifact.get("expired") is not False:
        return not_run(check_name, "The expected run-bound evidence artifact is expired or has unknown expiry state.")
    artifact_run = artifact.get("workflow_run")
    if (
        not isinstance(artifact_run, dict)
        or artifact_run.get("id") != run_id
    ):
        return not_run(check_name, "The evidence artifact does not bind the exact workflow run.")
    artifact_id = artifact.get("id")
    if not isinstance(artifact_id, int) or isinstance(artifact_id, bool):
        return not_run(check_name, "The evidence artifact id is invalid.")
    try:
        archive = _request_bytes(
            f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip",
            token,
        )
        document = artifact_document(archive, member)
    except (HTTPError, URLError, OSError, ValueError) as error:
        return not_run(check_name, f"The evidence artifact member could not be safely parsed: {error}.")
    if document.get("version") != 1 or document.get("run_id") != run_id:
        return not_run(check_name, "The evidence artifact run binding is invalid.")
    if document.get("event") != "pull_request_target":
        return not_run(check_name, "The evidence artifact event is invalid.")
    if document.get("base_sha") != trusted_base_revision:
        return not_run(check_name, "The evidence artifact base SHA is invalid.")
    if document.get("base_ref") != trusted_workflow_ref:
        return not_run(check_name, "The evidence artifact base ref is invalid.")
    if document.get("head_sha") != revision:
        return not_run(check_name, "The evidence artifact head SHA is invalid.")
    if document.get("repository") != repo:
        return not_run(check_name, "The evidence artifact repository is invalid.")
    if document.get("provider_id") != provider_id:
        return not_run(check_name, "The evidence artifact provider is invalid.")
    status = document.get("status")
    if status not in ARTIFACT_STATUSES:
        return not_run(check_name, "The evidence artifact status is invalid.")
    summary = document.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 1_000:
        return not_run(check_name, "The evidence artifact summary is invalid.")
    url = check.get("details_url") or "unavailable"
    if status in {"passed", "failed"}:
        result = {
            "producer": provider_name,
            "status": status,
            "evidence": [f"{summary}; {url}"],
        }
        if provider_id == "repository-change-scope":
            scope = {
                "version": 1,
                "metrics": document.get("metrics"),
                "thresholds": document.get("thresholds"),
            }
            try:
                evaluator_module().validate_change_scope(scope, status)
            except ValueError:
                # Older or malformed optional measurements are unavailable;
                # the independently verified producer status is unchanged.
                pass
            else:
                result["change_scope"] = scope
        return bounded_result(result)
    return bounded_result({
        "producer": provider_name,
        "status": "not_run",
        "reason": summary,
        "evidence": [f"{check_name}: run-bound artifact; {url}"],
    })


def proven_check_evidence(
    repo: str,
    revision: str,
    token: str,
    contract: dict[str, Any],
    check: dict[str, Any],
    provider_name: str,
    *,
    trusted_base_revision: str | None = None,
    trusted_workflow_ref: str | None = None,
) -> dict[str, Any]:
    check_name = contract["check_name"]
    if check.get("name") != check_name:
        return not_run(check_name, "The GitHub check name does not match the declared provider contract.")
    if check.get("head_sha") != revision:
        return not_run(check_name, "The GitHub check did not bind to the exact revision under evaluation.")
    platform_proof_required = contract.get("external_id_prefix") is not None or any(
        field in contract for field in ("artifact_name_prefix", "artifact_member")
    )
    if (
        CONCLUSIONS.get(check.get("conclusion") or "in_progress", "not_run")
        == "not_run"
        and not platform_proof_required
    ):
        return check_run_evidence(check_name, provider_name, check)
    app = check.get("app")
    app_slug = contract.get("app_slug")
    workflow_path = contract.get("workflow_path")
    if isinstance(app_slug, str) and app_slug:
        if not isinstance(app, dict) or app.get("slug") != app_slug:
            return not_run(check_name, "The check application does not match the declared provider contract.")
        return check_run_evidence(check_name, provider_name, check)
    if not isinstance(workflow_path, str) or not workflow_path:
        return not_run(check_name, "The GitHub Actions provider contract requires an exact workflow path.")
    if not isinstance(app, dict) or app.get("slug") != "github-actions":
        return not_run(check_name, "The check provenance is not the github-actions application.")
    external_id_prefix = contract.get("external_id_prefix")
    if external_id_prefix is not None:
        external_id_match = re.fullmatch(
            rf"{re.escape(external_id_prefix)}([0-9]+):{re.escape(revision)}",
            check.get("external_id") or "",
        )
        if not external_id_match:
            return not_run(check_name, "The check external id does not bind the workflow run and exact revision.")
        run_id = int(external_id_match.group(1))
    else:
        details_url = check.get("details_url")
        match = re.search(r"/actions/runs/([0-9]+)(?:/|$)", details_url or "")
        if not match:
            return not_run(check_name, "The check details URL does not identify a GitHub Actions workflow run.")
        run_id = int(match.group(1))
    try:
        workflow_run = _request(
            f"https://api.github.com/repos/{repo}/actions/runs/{run_id}", token
        )
    except (HTTPError, URLError, OSError, ValueError):
        return not_run(check_name, "The GitHub Actions workflow provenance could not be verified.")
    if workflow_run.get("name") != contract["workflow"]:
        return not_run(check_name, "The GitHub Actions workflow name does not match the declared provider contract.")
    if workflow_run.get("id") is not None and workflow_run.get("id") != run_id:
        return not_run(check_name, "The GitHub Actions workflow run id does not match the check details URL.")
    event = workflow_run.get("event")
    if platform_proof_required:
        if event != "pull_request_target":
            return not_run(check_name, "Artifact-backed external-id evidence requires a pull_request_target workflow run.")
        if not isinstance(trusted_base_revision, str) or not trusted_base_revision:
            return not_run(check_name, "Artifact-backed external-id evidence requires an exact trusted base revision.")
        if not isinstance(trusted_workflow_ref, str) or not trusted_workflow_ref:
            return not_run(check_name, "Artifact-backed external-id evidence requires an exact trusted workflow ref.")
        if not isinstance(workflow_path, str) or not workflow_path:
            return not_run(check_name, "Artifact-backed external-id evidence requires an exact workflow path contract.")
        actual_path = workflow_run.get("path")
        if actual_path not in {workflow_path, f"{workflow_path}@{trusted_workflow_ref}"}:
            return not_run(check_name, "The GitHub Actions workflow path/ref does not match the trusted provider contract.")
    elif not workflow_path_matches(workflow_path, workflow_run.get("path")):
        return not_run(check_name, "The GitHub Actions workflow path does not match the declared provider contract.")
    if event not in {"pull_request", "pull_request_target"}:
        return not_run(check_name, "The GitHub Actions workflow run is not associated with a pull request event.")
    if not platform_proof_required:
        pull_requests = workflow_run.get("pull_requests")
        if not isinstance(pull_requests, list):
            return not_run(check_name, "The GitHub Actions workflow run pull-request association is malformed.")
        associated_revision = any(
            isinstance(pull_request, dict)
            and isinstance(pull_request.get("head"), dict)
            and pull_request["head"].get("sha") == revision
            for pull_request in pull_requests
        )
        if pull_requests and not associated_revision:
            return not_run(check_name, "The GitHub Actions workflow run is not associated with a pull request at the exact head revision.")
        if event == "pull_request_target" and not associated_revision:
            return not_run(check_name, "The GitHub Actions pull request target workflow lacks an exact head association.")
        if event == "pull_request" and workflow_run.get("head_sha") != revision:
            return not_run(check_name, "The GitHub Actions pull request workflow did not run at the exact head revision.")
        check_suite = check.get("check_suite")
        if (
            not isinstance(check_suite, dict)
            or check_suite.get("id") is None
            or workflow_run.get("check_suite_id") != check_suite["id"]
        ):
            return not_run(check_name, "The GitHub Actions workflow run does not match the check suite identity.")
        if not isinstance(trusted_base_revision, str) or not trusted_base_revision:
            return not_run(check_name, "The GitHub Actions check requires an exact trusted base revision.")
        trusted_paths = list(dict.fromkeys([
            workflow_path,
            *contract.get("trusted_paths", []),
        ]))
        try:
            paths_match = trusted_paths_match_trusted_base(
                repo,
                trusted_paths,
                revision,
                trusted_base_revision,
                token,
            )
        except (HTTPError, URLError, OSError, ValueError, KeyError):
            return not_run(
                check_name,
                "The trusted path contents could not be verified against the trusted base.",
            )
        if not paths_match:
            return not_run(
                check_name,
                "A trusted path, including the workflow definition, differs from the trusted base.",
            )
    else:
        return run_artifact_evidence(
            repo, revision, token, run_id, contract, check, provider_name,
            trusted_base_revision, trusted_workflow_ref,
        )
    return check_run_evidence(check_name, provider_name, check)


def collect_checks(
    repo: str,
    revision: str,
    token: str,
    policy: dict[str, Any],
    profiles: dict[str, Any],
    catalog: dict[str, Any],
    provider_config: dict[str, Any],
    operation: str,
    wait_seconds: int = 0,
    subject_type: str = "git-commit",
    trusted_base_revision: str | None = None,
    trusted_workflow_ref: str | None = None,
    pull_request_number: int | None = None,
) -> dict[str, Any]:
    if subject_type != "git-commit":
        raise ValueError("GitHub check collection is git-commit only")
    expected = expected_checks(policy, profiles, catalog, provider_config, operation)
    reviews = expected_reviews(policy, profiles, catalog, provider_config, operation)
    providers = provider_config["providers"]
    check_names = set(expected)
    deadline = time.monotonic() + max(0, wait_seconds)
    maximum_attempts = 1 + (max(0, wait_seconds) + 9) // 10
    matching: dict[str, list[dict[str, Any]]] = {name: [] for name in check_names}
    wrong_app_only: dict[str, bool] = {name: False for name in check_names}
    enumeration_failures: set[str] = set()
    attempts = 0
    while True:
        attempts += 1
        for name in check_names - enumeration_failures:
            try:
                check_runs = enumerate_check_runs(repo, revision, token, name)
            except (HTTPError, URLError, OSError, ValueError, KeyError):
                enumeration_failures.add(name)
                matching[name] = []
            else:
                contract = expected[name]
                same_name = [check for check in check_runs if check.get("name") == name]
                matching[name] = [
                    check
                    for check in same_name
                    if check_matches_declared_app(check, contract)
                ]
                wrong_app_only[name] = bool(same_name and not matching[name])
        complete = all(
            name in enumeration_failures
            or (
                matching[name]
                and (len(matching[name]) > 1 or matching[name][0].get("status") == "completed")
            )
            for name in check_names
        )
        if complete or time.monotonic() >= deadline or attempts >= maximum_attempts:
            break
        time.sleep(10)

    results: dict[str, dict[str, dict[str, Any]]] = {}
    for check_name, contract in expected.items():
        provider_id = contract["provider_id"]
        matches = matching[check_name]
        if check_name in enumeration_failures:
            result = not_run(
                check_name,
                "Complete GitHub check-run enumeration could not be proven.",
            )
        elif not matches:
            if wrong_app_only[check_name]:
                declared_app = contract.get("app_slug") or "github-actions"
                result = not_run(
                    check_name,
                    "The selected provider check was reported only by applications "
                    f"that do not match the declared app {declared_app!r}.",
                )
            else:
                result = not_run(check_name, "The selected provider check did not report this revision.")
        elif len(matches) > 1:
            result = not_run(check_name, "Duplicate matching GitHub check names make provider provenance ambiguous.")
        else:
            check = matches[0]
            result = proven_check_evidence(
                repo, revision, token, contract, check,
                providers[provider_id]["display_name"],
                trusted_base_revision=trusted_base_revision,
                trusted_workflow_ref=trusted_workflow_ref,
            )
        for control_id in contract["control_ids"]:
            results.setdefault(control_id, {})[provider_id] = copy.deepcopy(result)
    review_attempts = 0
    pending_reviews = list(reviews)
    review_results: dict[tuple[str, str], dict[str, Any]] = {}
    while pending_reviews:
        review_attempts += 1
        next_pending = []
        for contract in pending_reviews:
            key = (contract["control_id"], contract["provider_id"])
            try:
                result = collect_review_evidence(
                    repo,
                    revision,
                    token,
                    pull_request_number,
                    contract,
                    contract["provider_name"],
                )
            except (HTTPError, URLError, OSError, ValueError, KeyError):
                result = not_run(
                    contract["provider_name"],
                    "Complete GitHub pull-request review enumeration could not be proven.",
                )
            review_results[key] = result
            if (
                result["status"] != "passed"
                and pull_request_number is not None
                and time.monotonic() < deadline
                and review_attempts < maximum_attempts
            ):
                next_pending.append(contract)
        if not next_pending:
            break
        pending_reviews = next_pending
        time.sleep(10)
    for (control_id, provider_id), result in review_results.items():
        results.setdefault(control_id, {})[provider_id] = result
    return {"version": 2, "subject": {"type": "git-commit", "revision": revision}, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect selected Guardrails v2 GitHub check evidence")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--policy", type=Path, default=Path(".guardrails/policy.yaml"))
    parser.add_argument("--profiles", type=Path, default=Path(".guardrails/profiles.yaml"))
    parser.add_argument("--catalog", type=Path, default=Path(".guardrails/control-catalog.yaml"))
    parser.add_argument("--providers", type=Path, default=Path(".guardrails/providers.yaml"))
    parser.add_argument("--trusted-base-revision", required=True)
    parser.add_argument("--trusted-workflow-ref", required=True)
    parser.add_argument("--operation", choices=("change", "release"), default="change")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--pull-request-number", type=int)
    args = parser.parse_args()
    if not args.repo or not args.token:
        print("ERROR --repo and --token are required", file=sys.stderr)
        return 2
    try:
        evidence = collect_checks(
            args.repo, args.revision, args.token, load(args.policy), load(args.profiles),
            load(args.catalog), load(args.providers), args.operation,
            wait_seconds=args.wait_seconds,
            trusted_base_revision=args.trusted_base_revision,
            trusted_workflow_ref=args.trusted_workflow_ref,
            pull_request_number=args.pull_request_number,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        return 0
    except (OSError, ValueError, KeyError, HTTPError, URLError) as error:
        print(f"ERROR collecting GitHub evidence: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
