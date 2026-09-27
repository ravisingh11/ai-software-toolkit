#!/usr/bin/env python3
"""Validate mutable pull-request metadata and emit revision-bound evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

MAX_PATTERN_LENGTH = 500
MAX_MARKERS = 20


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def validated_config(config: dict[str, Any]) -> tuple[re.Pattern[str], list[str]]:
    if set(config) != {"version", "title_pattern", "required_body_markers"}:
        raise ValueError("PR metadata configuration contains unknown or missing fields")
    if config.get("version") != 2:
        raise ValueError("PR metadata configuration version must be 2")
    pattern = config.get("title_pattern")
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError("title_pattern must be a nonempty string of at most 500 characters")
    try:
        compiled = re.compile(pattern)
    except re.error as error:
        raise ValueError(f"title_pattern is invalid: {error}") from error
    markers = config.get("required_body_markers")
    if (
        not isinstance(markers, list)
        or len(markers) > MAX_MARKERS
        or len(markers) != len(set(markers))
        or any(
            not isinstance(marker, str) or not marker.strip() or len(marker) > 200
            for marker in markers
        )
    ):
        raise ValueError("required_body_markers must be a unique list of up to 20 strings")
    return compiled, markers


def pull_request_fields(event: dict[str, Any]) -> dict[str, Any]:
    repository = event.get("repository")
    pull_request = event.get("pull_request")
    if not isinstance(repository, dict) or not isinstance(pull_request, dict):
        raise ValueError("GitHub event must contain repository and pull_request objects")
    head = pull_request.get("head")
    fields = {
        "repository": repository.get("full_name"),
        "number": pull_request.get("number"),
        "head_sha": head.get("sha") if isinstance(head, dict) else None,
        "updated_at": pull_request.get("updated_at"),
        "title": pull_request.get("title"),
        "body": pull_request.get("body") or "",
    }
    if (
        not isinstance(fields["repository"], str)
        or not fields["repository"].strip()
        or not isinstance(fields["number"], int)
        or isinstance(fields["number"], bool)
        or fields["number"] <= 0
        or any(
            not isinstance(fields[key], str)
            for key in ("head_sha", "updated_at", "title", "body")
        )
        or any(not fields[key].strip() for key in ("head_sha", "updated_at"))
    ):
        raise ValueError("GitHub pull-request event is missing required metadata")
    return fields


def pull_request_revision(event: dict[str, Any]) -> str:
    fields = pull_request_fields(event)
    serialized = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_metadata(event: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    pattern, markers = validated_config(config)
    fields = pull_request_fields(event)
    findings: list[str] = []
    title = fields["title"].strip()
    if not title or pattern.search(title) is None:
        findings.append("Pull-request title does not satisfy title_pattern.")
    for marker in markers:
        if marker not in fields["body"]:
            findings.append(f"Pull-request body is missing required marker: {marker}")
    if findings:
        return {
            "producer": "Repository PR Metadata",
            "status": "failed",
            "evidence": findings,
        }
    return {
        "producer": "Repository PR Metadata",
        "status": "passed",
        "evidence": [
            f"PR {fields['repository']}#{fields['number']} metadata satisfies the configured contract."
        ],
    }


def write_evidence(path: Path, revision: str, result: dict[str, Any]) -> None:
    document = {
        "version": 2,
        "subject": {"type": "pull-request", "revision": revision},
        "results": {"pr-metadata": {"repository-pr-metadata": result}},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        event = load_object(args.event)
        config = load_object(args.config)
        revision = pull_request_revision(event)
        result = validate_metadata(event, config)
        write_evidence(args.output, revision, result)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
