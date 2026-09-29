#!/usr/bin/env python3
# Proof installer-owned runtime.
"""Bind a credentialed provider result to its workflow run and describe the check run that reports it.

The Snyk, FOSSA, and AI PR Review workflows run on ``pull_request_target``, so
GitHub always takes the workflow and this runtime from the default branch.
Their jobs hold a provider credential and read the pull-request head only as
data. Each job reports its result twice, with the same content:

* ``evidence`` writes ``proof-evidence.json``, which the job uploads as the
  run-bound artifact ``proof-<provider>-<run id>``. The Proof collector reads
  the status from this artifact, never from the check conclusion.
* ``check`` writes the check-run payload the job posts for the pull-request
  head, named exactly as the provider contract and carrying the external id
  ``proof:<provider>:<run id>:<head sha>``.

A missing or unreadable result is recorded as ``blocked``, and a fork pull
request whose credential was withheld as ``not_run``; neither is ever a pass.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STATUSES = ("passed", "failed", "blocked", "not_run")
CONCLUSIONS = {"passed": "success", "failed": "failure", "blocked": "failure", "not_run": "failure"}
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
PROVIDER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
MAX_SUMMARY = 1000
MAX_INPUT_BYTES = 1_000_000


def external_id_prefix(provider_id: str) -> str:
    return f"proof:{provider_id}:"


def artifact_name_prefix(provider_id: str) -> str:
    return f"proof-{provider_id}-"


def bounded(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_SUMMARY else text[: MAX_SUMMARY - 3] + "..."


def read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"{path} is not a regular file within the size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def fragment_result(path: Path, provider_id: str, head_sha: str) -> tuple[str, str]:
    """Status and summary from the adapter's evidence fragment; unreadable evidence is blocked."""
    try:
        document = read_json(path)
    except (OSError, ValueError) as error:
        return "blocked", f"execution-error: the trusted adapter produced no readable evidence ({error})."
    subject = document.get("subject") if isinstance(document, dict) else None
    results = document.get("results") if isinstance(document, dict) else None
    if not isinstance(subject, dict) or subject.get("revision") != head_sha:
        return "not_run", "revision-mismatch: the adapter evidence is not bound to the pull-request head."
    provided = [entry.get(provider_id) for entry in results.values() if isinstance(entry, dict)] if isinstance(results, dict) else []
    if not provided or any(not isinstance(result, dict) or result != provided[0] for result in provided):
        return "blocked", "execution-error: the adapter evidence does not contain one result for this provider."
    result = provided[0]
    status = result.get("status")
    if status in {"passed", "failed"}:
        evidence = result.get("evidence")
        text = "; ".join(item for item in evidence if isinstance(item, str)) if isinstance(evidence, list) else ""
        return status, text or status
    if status in {"blocked", "not_run"} and isinstance(result.get("reason"), str) and result["reason"].strip():
        return status, result["reason"]
    return "blocked", "execution-error: the adapter evidence has no valid status."


def validated_measurements(path: Path | None, control: str | None, status: str) -> dict[str, Any] | None:
    """Optional finding counts, kept only when the evaluator accepts them for this status."""
    if path is None or control is None or status not in {"passed", "failed"} or not path.is_file():
        return None
    try:
        measurements = read_json(path)
        evaluator_path = next(candidate for candidate in (HERE / "evaluate.py", HERE.parent / "proof" / "evaluate.py")
                              if candidate.is_file())
        spec = importlib.util.spec_from_file_location("provider_check_evaluator", evaluator_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_measurements(control, measurements, status)
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        return None
    return measurements


def run_context(environment: dict[str, str]) -> dict[str, Any]:
    run_id, attempt = environment.get("GITHUB_RUN_ID", ""), environment.get("GITHUB_RUN_ATTEMPT", "")
    context = {
        "run_id": int(run_id) if run_id.isdigit() else None,
        "run_attempt": int(attempt) if attempt.isdigit() else None,
        "event": environment.get("GITHUB_EVENT_NAME", ""),
        "repository": environment.get("GITHUB_REPOSITORY", ""),
        "base_sha": environment.get("BASE_SHA", ""),
        "base_ref": environment.get("BASE_REF", ""),
        "head_sha": environment.get("HEAD_SHA", ""),
    }
    if (
        context["run_id"] is None
        or context["run_attempt"] is None
        or context["event"] != "pull_request_target"
        or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", context["repository"]) is None
        or SHA_PATTERN.fullmatch(context["base_sha"]) is None
        or SHA_PATTERN.fullmatch(context["head_sha"]) is None
        or not context["base_ref"].startswith("refs/heads/")
    ):
        raise ValueError("a pull_request_target run with GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, GITHUB_REPOSITORY, "
                         "BASE_SHA, BASE_REF, and HEAD_SHA is required")
    return context


def evidence_document(
    provider_id: str,
    check_name: str,
    environment: dict[str, str],
    *,
    fragment: Path | None = None,
    status: str | None = None,
    summary: str | None = None,
    withheld: str | None = None,
    control: str | None = None,
    measurements: Path | None = None,
) -> dict[str, Any]:
    if PROVIDER_PATTERN.fullmatch(provider_id) is None or not check_name.strip():
        raise ValueError("a valid provider id and check name are required")
    context = run_context(environment)
    if withheld:
        status, summary = "not_run", f"credential-withheld: {withheld}"
    elif fragment is not None:
        status, summary = fragment_result(fragment, provider_id, context["head_sha"])
    elif status not in STATUSES or not (summary or "").strip():
        status, summary = "blocked", "execution-error: the job reported no valid result."
    document = {
        "version": 1,
        **context,
        "revision": context["head_sha"],
        "provider_id": provider_id,
        "check_name": check_name,
        "status": status,
        "summary": bounded(summary or status),
        "withheld": bool(withheld),
    }
    counts = validated_measurements(measurements, control, status)
    if counts is not None:
        document["control"] = control
        document["measurements"] = counts
    return document


def check_payload(document: dict[str, Any], server_url: str) -> dict[str, Any]:
    status = document["status"]
    conclusion = "action_required" if document.get("withheld") else CONCLUSIONS[status]
    details_url = f"{server_url}/{document['repository']}/actions/runs/{document['run_id']}"
    return {
        "name": document["check_name"],
        "head_sha": document["head_sha"],
        "status": "completed",
        "conclusion": conclusion,
        "details_url": details_url,
        "external_id": f"{external_id_prefix(document['provider_id'])}{document['run_id']}:{document['head_sha']}",
        "output": {
            "title": f"{document['check_name']}: {status.replace('_', ' ')}",
            "summary": f"{document['summary']}\n\nProduced from the default branch's workflow; the pull-request "
                       "head was read as data and never executed.",
        },
    }


def write(path: Path, document: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing to write through a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    evidence = commands.add_parser("evidence", help="write the run-bound evidence document")
    evidence.add_argument("--provider-id", required=True)
    evidence.add_argument("--check-name", required=True)
    source = evidence.add_mutually_exclusive_group(required=True)
    source.add_argument("--fragment", type=Path, help="adapter evidence fragment")
    source.add_argument("--status", help="job result when there is no adapter fragment")
    source.add_argument("--withheld", help="why the credential was not used for this pull request")
    evidence.add_argument("--summary", help="summary for --status")
    evidence.add_argument("--control", help="control id for --measurements")
    evidence.add_argument("--measurements", type=Path, help="optional finding counts")
    evidence.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("check", help="write the check-run payload for an evidence document")
    check.add_argument("--evidence", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "evidence":
            document = evidence_document(
                args.provider_id, args.check_name, dict(os.environ), fragment=args.fragment, status=args.status,
                summary=args.summary, withheld=args.withheld, control=args.control, measurements=args.measurements,
            )
        else:
            document = check_payload(read_json(args.evidence), os.environ.get("GITHUB_SERVER_URL", "https://github.com"))
        write(args.output, document)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"provider check: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
