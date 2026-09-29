#!/usr/bin/env python3
"""Validate repository-declared ground-truth documents."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def record_measurements(declared: int, missing: int) -> None:
    """Write optional display counts for the scorecard; never affects the result."""
    target = os.environ.get("PROOF_MEASUREMENTS_FILE")
    if not target:
        return
    document = {"version": 1, "source": "pull-request-workflow", "documents": {
        "declared": declared, "found": declared - missing, "missing": missing,
    }}
    try:
        Path(target).write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"WARNING: ground-truth measurements were not recorded: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repository ground-truth documents")
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(".proof/ground-truth-ai.yaml"),
    )
    args = parser.parse_args()
    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: cannot read ground-truth policy: {error}")
        return 1
    if policy.get("version") != 1 or not isinstance(policy.get("documents"), list):
        print("ERROR: ground-truth policy requires version 1 and documents")
        return 1
    for index, item in enumerate(policy["documents"], start=1):
        if (
            not isinstance(item, dict)
            or set(item) != {"path"}
            or not isinstance(item["path"], str)
            or not item["path"].strip()
        ):
            print(
                f"ERROR: invalid document entry {index}; "
                "expected an object with exactly one non-empty string path"
            )
            return 1
    repository_root = Path.cwd().resolve()
    resolved_documents: list[tuple[str, Path]] = []
    for item in policy["documents"]:
        declared_path = item["path"]
        document_path = Path(declared_path)
        if document_path.is_absolute():
            print(f"ERROR: document path must be repository-relative: {declared_path}")
            return 1
        resolved_path = (repository_root / document_path).resolve()
        if not resolved_path.is_relative_to(repository_root):
            print(
                "ERROR: document path must resolve within repository root: "
                f"{declared_path}"
            )
            return 1
        resolved_documents.append((declared_path, resolved_path))
    missing = [
        declared_path
        for declared_path, resolved_path in resolved_documents
        if not resolved_path.is_file()
    ]
    record_measurements(len(resolved_documents), len(missing))
    if missing:
        print("Missing repository ground-truth documents:")
        for path in missing:
            print(f"- {path}")
        return 1
    print(f"Repository ground truth passed ({len(policy['documents'])} documents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
