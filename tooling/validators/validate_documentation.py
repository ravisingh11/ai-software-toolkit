#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / ".proof" / "documentation.yaml"
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def load_policy(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} must use JSON-compatible YAML: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    validate_policy(value)
    return value


def validate_pattern(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or ".." in Path(value).parts
    ):
        raise ValueError(f"{label} must be a relative POSIX path pattern")


def validate_policy(policy: dict[str, Any]) -> None:
    if set(policy) != {"version", "mappings"}:
        raise ValueError("documentation policy requires only version and mappings")
    if policy["version"] != 1:
        raise ValueError("documentation policy version must be 1")
    mappings = policy["mappings"]
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("documentation policy mappings must be a non-empty list")

    names: set[str] = set()
    for index, mapping in enumerate(mappings):
        label = f"mappings[{index}]"
        if not isinstance(mapping, dict) or set(mapping) != {
            "name",
            "triggers",
            "documents",
        }:
            raise ValueError(f"{label} requires name, triggers, and documents")
        name = mapping["name"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)
            or name in names
        ):
            raise ValueError(f"{label}.name must be a unique kebab-case identifier")
        names.add(name)
        for key in ("triggers", "documents"):
            patterns = mapping[key]
            if not isinstance(patterns, list) or not patterns:
                raise ValueError(f"{label}.{key} must be a non-empty list")
            for pattern in patterns:
                validate_pattern(pattern, f"{label}.{key}")


def glob_regex(pattern: str) -> re.Pattern[str]:
    index = 0
    output = ""
    while index < len(pattern):
        if pattern[index : index + 3] == "**/":
            output += "(?:.*/)?"
            index += 3
        elif pattern[index : index + 2] == "**":
            output += ".*"
            index += 2
        elif pattern[index] == "*":
            output += "[^/]*"
            index += 1
        else:
            output += re.escape(pattern[index])
            index += 1
    return re.compile(f"^{output}$")


def matches(path: str, patterns: list[str]) -> bool:
    return any(glob_regex(pattern).fullmatch(path) for pattern in patterns)


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if ".git" not in path.relative_to(root).parts
    )


def link_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0]


def validate_markdown_links(root: Path, counts: dict[str, int] | None = None) -> list[str]:
    failures: list[str] = []
    documents = markdown_files(root)
    checked = 0
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for raw in LINK_PATTERN.findall(text):
            target = link_target(raw)
            if (
                not target
                or target.startswith("#")
                or re.match(r"^(?:https?|mailto|tel|data):", target)
            ):
                continue
            checked += 1
            local = unquote(target.split("#", 1)[0].split("?", 1)[0])
            candidate = (document.parent / local).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                failures.append(
                    f"{document.relative_to(root)} links outside the repository: {target}"
                )
                continue
            if not candidate.exists():
                failures.append(
                    f"{document.relative_to(root)} has missing link target: {target}"
                )
    if counts is not None:
        counts.update(markdown_files=len(documents), links_checked=checked, broken_links=len(failures))
    return failures


def validate_document_targets(
    root: Path,
    policy: dict[str, Any],
) -> list[str]:
    files = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    ]
    failures: list[str] = []
    for mapping in policy["mappings"]:
        for pattern in mapping["documents"]:
            if not matches_any_file(files, pattern):
                failures.append(
                    f"mapping {mapping['name']} document pattern matches no files: "
                    f"{pattern}"
                )
    return failures


def matches_any_file(files: list[str], pattern: str) -> bool:
    expression = glob_regex(pattern)
    return any(expression.fullmatch(path) for path in files)


def validate_changed_files(
    policy: dict[str, Any],
    changed_files: list[str],
) -> list[str]:
    normalized = sorted(set(changed_files))
    failures: list[str] = []
    for mapping in policy["mappings"]:
        triggered = [
            path for path in normalized if matches(path, mapping["triggers"])
        ]
        if triggered and not any(
            matches(path, mapping["documents"]) for path in normalized
        ):
            failures.append(
                f"mapping {mapping['name']} requires a documentation change "
                f"because these files changed: {', '.join(triggered)}"
            )
    return failures


def resolve_commit(root: Path, reference: str) -> str:
    if (
        not reference
        or reference.startswith("-")
        or any(character.isspace() for character in reference)
    ):
        raise ValueError(f"unsafe Git reference: {reference!r}")
    value = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{reference}^{{commit}}",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", value):
        raise ValueError(f"Git returned an invalid commit for {reference!r}")
    return value


def changed_between(
    root: Path,
    base_ref: str,
    head_ref: str,
    fallback_base: str | None,
) -> list[str]:
    base = base_ref
    if set(base_ref) == {"0"}:
        if not fallback_base:
            raise ValueError("a zero base revision requires --fallback-base")
        base = fallback_base
    resolved_base = resolve_commit(root, base)
    resolved_head = resolve_commit(root, head_ref)
    raw = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRD",
            "-z",
            f"{resolved_base}...{resolved_head}",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in raw.split(b"\0")
        if item
    ]


def validate(
    root: Path,
    policy_path: Path,
    changed_files: list[str] | None = None,
    counts: dict[str, int] | None = None,
) -> list[str]:
    policy = load_policy(policy_path)
    link_failures = validate_markdown_links(root, counts)
    mapping_failures = validate_document_targets(root, policy)
    if changed_files is not None:
        mapping_failures.extend(validate_changed_files(policy, changed_files))
    if counts is not None:
        counts["mapping_failures"] = len(mapping_failures)
    return [*link_failures, *mapping_failures]


def record_measurements(counts: dict[str, int]) -> None:
    """Write optional display counts for the scorecard; never affects the result."""
    target = os.environ.get("PROOF_MEASUREMENTS_FILE")
    if not target:
        return
    document = {"version": 1, "source": "pull-request-workflow", "documentation": counts}
    try:
        Path(target).write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"WARNING: documentation measurements were not recorded: {error}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate documentation integrity and change-to-doc mappings"
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--fallback-base")
    parser.add_argument("--changed-file", action="append", default=[])
    args = parser.parse_args()

    try:
        if bool(args.base_ref) != bool(args.head_ref):
            raise ValueError("--base-ref and --head-ref must be used together")
        changed_files: list[str] | None = args.changed_file or None
        if args.base_ref:
            changed_files = changed_between(
                ROOT,
                args.base_ref,
                args.head_ref,
                args.fallback_base,
            )
        counts: dict[str, int] = {}
        failures = validate(ROOT, args.policy, changed_files, counts)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    record_measurements(counts)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    scope = (
        f" and {len(changed_files)} changed files"
        if changed_files is not None
        else ""
    )
    print(f"Documentation validation passed{scope}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
