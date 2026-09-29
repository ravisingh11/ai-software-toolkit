#!/usr/bin/env python3
"""Enforce this repository's ground truth that it has no database migrations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


MIGRATION_SUFFIXES = (
    ("migrations",),
    ("db", "migrate"),
    ("alembic", "versions"),
    ("prisma", "migrations"),
    ("src", "main", "resources", "db", "migration"),
    ("src", "main", "resources", "db", "changelog"),
)
EXCLUDED_DIRECTORIES = {
    ".artifacts",
    ".git",
    ".venv",
    ".worktrees",
    "__pycache__",
    "node_modules",
    "vendor",
    "venv",
}


def migration_paths(root: Path) -> list[Path]:
    found: list[Path] = []
    for current, directories, _files in os.walk(root, followlinks=False):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory.casefold() not in EXCLUDED_DIRECTORIES
        )
        current_path = Path(current)
        for directory in list(directories):
            relative = (current_path / directory).relative_to(root)
            parts = tuple(part.casefold() for part in relative.parts)
            if any(
                len(parts) >= len(suffix) and parts[-len(suffix) :] == suffix
                for suffix in MIGRATION_SUFFIXES
            ):
                found.append(relative)
                directories.remove(directory)
    return sorted(found)


def record_measurements(found: int) -> None:
    """Write optional display counts for the scorecard; never affects the result.

    With no declared migration surface, every surface found is a failed check.
    """
    target = os.environ.get("PROOF_MEASUREMENTS_FILE")
    if not target:
        return
    document = {"version": 1, "source": "pull-request-workflow",
                "migrations": {"checked": found, "failed": found}}
    try:
        Path(target).write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"WARNING: migration measurements were not recorded: {error}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail if a database migration surface is introduced without a real validator."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    found = migration_paths(args.root.resolve())
    record_measurements(len(found))
    if found:
        rendered = ", ".join(path.as_posix() for path in found)
        print(
            "Database migration paths were introduced but this repository declares no "
            f"migration surface: {rendered}. Replace this check with the migration "
            "framework's real validation command before merging.",
            file=sys.stderr,
        )
        return 1
    print("No database migration surface is present, matching repository ground truth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
