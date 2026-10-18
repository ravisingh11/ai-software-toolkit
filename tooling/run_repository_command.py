#!/usr/bin/env python3
"""Run explicitly configured producer commands in unprivileged candidate jobs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

VARIABLES = {
    "build": "PROOF_BUILD_COMMAND",
    "unit-tests": "PROOF_UNIT_TEST_COMMAND",
    "format-and-lint": "PROOF_FORMAT_LINT_COMMAND",
    "migration-validation": "PROOF_MIGRATION_VALIDATION_COMMAND",
    "changed-code-coverage": "PROOF_CHANGED_COVERAGE_COMMAND",
}
MAX_BYTES = 65536


def configuration(root: Path) -> dict:
    parent = root / ".proof"
    path = parent / "commands.json"
    if parent.is_symlink() or path.is_symlink():
        raise ValueError("commands configuration must not be a symlink")
    if not path.exists():
        return {}
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
            raise ValueError("commands configuration must be a bounded regular file")
        data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("commands configuration grew beyond the supported size")
        document = json.loads(data)
    if not isinstance(document, dict) or type(document.get("version")) is not int or document.get("version") != 1:
        raise ValueError("commands configuration requires version 1")
    if set(document) - {"version", "commands", "setup", "working_directory"}:
        raise ValueError("unknown commands configuration fields")
    commands = document.get("commands", {})
    if not isinstance(commands, dict) or set(commands) - VARIABLES.keys():
        raise ValueError("unknown producer commands")
    if any(not isinstance(value, str) for value in [*commands.values(), document.get("setup", ""), document.get("working_directory", ".")]):
        raise ValueError("command configuration values must be strings")
    return document


def selected(root: Path, name: str) -> tuple[str, str, Path]:
    config = configuration(root)
    command = os.environ.get(VARIABLES[name]) or config.get("commands", {}).get(name, "")
    setup = os.environ.get("PROOF_SETUP_COMMAND") or config.get("setup", "")
    relative = os.environ.get("PROOF_WORKING_DIRECTORY") or config.get("working_directory", ".")
    directory = Path(relative)
    if directory.is_absolute() or ".." in directory.parts:
        raise ValueError("working directory must be relative within the repository")
    directory = (root / directory).resolve()
    if not directory.is_relative_to(root.resolve()) or not directory.is_dir():
        raise ValueError("working directory must exist within the repository")
    return command, setup, directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", choices=VARIABLES, required=True)
    parser.add_argument("--phase", choices=("all", "setup", "producer"), default="all")
    parser.add_argument("--configured", action="store_true", help="Print selection only; do not execute setup or producer")
    args = parser.parse_args()
    try:
        command, setup, directory = selected(Path.cwd(), args.command)
        if args.configured:
            print("true" if command.strip() else "false")
            return 0
        if not command.strip():
            raise ValueError("producer command is not configured")
        phases = {
            "all": ((True, setup), (False, command)),
            "setup": ((True, setup),),
            "producer": ((False, command),),
        }
        for is_setup, value in phases[args.phase]:
            if value.strip():
                environment = os.environ.copy()
                if not is_setup:
                    # Match the former separate Actions steps: nested producers
                    # must not inherit this repository's setup configuration.
                    environment.pop("PROOF_SETUP_COMMAND", None)
                result = subprocess.run(["bash", "-euo", "pipefail", "-c", value], cwd=directory, env=environment)
                if result.returncode:
                    return result.returncode if result.returncode > 0 else 1
        return 0
    except (ValueError, OSError) as error:
        # Configuration/parser errors may contain command text; report only class.
        print(f"Repository command configuration failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
