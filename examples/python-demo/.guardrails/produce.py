#!/usr/bin/env python3
"""Produce bounded, revision-bound Guardrails v2 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping

SEMGREP_VERSION = "1.175.0"
GITLEAKS_VERSION = "8.30.1"
SEMGREP_IMAGE = "semgrep/semgrep@sha256:b94b53d02fd4a022f9eac4e2af1380f5c3c4c21400e79d3336bdff1d1db5e796"
GITLEAKS_IMAGE = "ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
MAX_OUTPUT = 1000

COMMAND_PRODUCERS = {
    "build": ("GUARDRAILS_BUILD_COMMAND", "repository-build", "Repository Build Command"),
    "unit-tests": ("GUARDRAILS_UNIT_TEST_COMMAND", "repository-unit-tests", "Repository Unit Test Command"),
    "changed-code-coverage": (
        "GUARDRAILS_CHANGED_COVERAGE_COMMAND",
        "repository-changed-code-coverage",
        "Repository Changed Code Coverage Command",
    ),
    "format-and-lint": (
        "GUARDRAILS_FORMAT_LINT_COMMAND",
        "repository-format-and-lint",
        "Repository Format and Lint Command",
    ),
    "migration-validation": (
        "GUARDRAILS_MIGRATION_VALIDATION_COMMAND",
        "repository-migration-validation",
        "Repository Migration Validation Command",
    ),
}

Runner = Callable[[list[str], Path], tuple[int, str]]


def run(command: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def bounded(value: str) -> str:
    normalized = value.strip() or "command completed without output"
    if len(normalized) <= MAX_OUTPUT:
        return normalized
    marker = "...[truncated]..."
    leading = (MAX_OUTPUT - len(marker)) // 2
    trailing = MAX_OUTPUT - len(marker) - leading
    return normalized[:leading] + marker + normalized[-trailing:]


def producer_result(
    producer: str,
    status: str,
    *,
    evidence: list[str] | None = None,
    reason: str | None = None,
) -> dict:
    result = {"producer": producer, "status": status}
    if evidence is not None:
        result["evidence"] = [bounded(record) for record in evidence]
    if reason is not None:
        result["reason"] = bounded(reason)
    return result


def command_digest(command: str | list[str]) -> str:
    serialized = command if isinstance(command, str) else "\0".join(command)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def exact_clean_head(target: Path, revision: str) -> str:
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=target, text=True, capture_output=True
        )
        if completed.returncode != 0:
            detail = (completed.stdout + completed.stderr).strip()
            raise ValueError(detail or f"git {' '.join(arguments)} failed")
        return completed.stdout.strip()

    head = git("rev-parse", "--verify", "HEAD^{commit}")
    try:
        requested = git("rev-parse", "--verify", f"{revision}^{{commit}}")
    except ValueError as error:
        raise ValueError(f"revision {revision!r} is not a git commit: {error}") from error
    if requested != head:
        raise ValueError(
            f"revision {revision!r} resolves to {requested}, but exact HEAD is {head}"
        )
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("the repository worktree must be clean before producing evidence")
    return head


def command_record(
    producer: str,
    capability: str,
    command: str | list[str],
    code: int,
    output: str,
) -> dict:
    return producer_result(
        producer,
        "passed" if code == 0 else "failed",
        evidence=[
            f"{capability} command digest: sha256:{command_digest(command)}",
            output,
        ],
    )


def repository_command_result(
    control_id: str,
    environment: Mapping[str, str],
    target: Path,
    *,
    runner: Runner = run,
    revision: str | None = None,
) -> dict:
    variable, _, producer = COMMAND_PRODUCERS[control_id]
    command = environment.get(variable, "").strip()
    if not command:
        return producer_result(
            producer,
            "not_run",
            reason=f"{variable} is not configured; this capability has NO RESULT.",
        )
    working = environment.get("GUARDRAILS_WORKING_DIRECTORY", ".").strip() or "."
    cwd = (target / working).resolve()
    try:
        cwd.relative_to(target.resolve())
    except ValueError as error:
        return producer_result(
            producer,
            "not_run",
            reason=f"GUARDRAILS_WORKING_DIRECTORY must stay inside the repository: {error}",
        )
    if not cwd.is_dir():
        return producer_result(
            producer,
            "not_run",
            reason=f"GUARDRAILS_WORKING_DIRECTORY does not exist: {working}",
        )

    if revision is not None:
        try:
            exact_clean_head(target, revision)
        except (OSError, ValueError) as error:
            return producer_result(
                producer,
                "not_run",
                reason=f"Revision-bound evidence could not start: {error}",
            )

    setup = environment.get("GUARDRAILS_SETUP_COMMAND", "").strip()
    if setup:
        code, output = runner(["bash", "-euo", "pipefail", "-c", setup], cwd)
        if revision is not None:
            try:
                exact_clean_head(target, revision)
            except (OSError, ValueError) as error:
                return producer_result(
                    producer,
                    "not_run",
                    reason=f"The repository changed while setup ran: {error}",
                )
        if code != 0:
            return command_record(producer, "setup", setup, code, output)
    code, output = runner(["bash", "-euo", "pipefail", "-c", command], cwd)
    if revision is not None:
        try:
            exact_clean_head(target, revision)
        except (OSError, ValueError) as error:
            return producer_result(
                producer,
                "not_run",
                reason=f"The repository changed while the producer ran: {error}",
            )
    return command_record(producer, control_id, command, code, output)


def exact_host_version(
    binary: str,
    expected: str,
    target: Path,
    runner: Runner,
) -> tuple[bool, str]:
    code, output = runner([binary, "--version"], target)
    if code != 0:
        return False, bounded(output)
    normalized = output.strip().lower().removeprefix("gitleaks version ").removeprefix("semgrep ").lstrip("v")
    return normalized == expected, output.strip()


def semgrep_result(
    target: Path,
    *,
    runner: Runner = run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict:
    rules = target / ".guardrails" / "semgrep-rules.yml"
    producer = "Semgrep Community Edition 1.175.0"
    if not rules.is_file():
        return producer_result(
            producer, "not_run", reason="The installed local Semgrep rule pack is missing."
        )
    if which("docker"):
        code, output = runner(["docker", "version", "--format", "{{.Server.Version}}"], target)
        if code == 0:
            command = [
                "docker", "run", "--rm", "--network", "none",
                "-v", f"{target.resolve()}:/src:ro", "-w", "/src",
                SEMGREP_IMAGE, "semgrep", "scan", "--error",
                "--config", ".guardrails/semgrep-rules.yml",
                "--exclude", ".guardrails/semgrep-tests/fixtures",
                "--exclude", "security/semgrep/tests/fixtures",
                "--exclude", "examples/python-demo/.guardrails/semgrep-tests/fixtures", ".",
            ]
            scan_code, scan_output = runner(command, target)
            return command_record(producer, "semgrep-ce", command, scan_code, scan_output)
        docker_reason = bounded(output)
    else:
        docker_reason = "Docker is not installed."
    if which("semgrep"):
        exact, actual = exact_host_version("semgrep", SEMGREP_VERSION, target, runner)
        if exact:
            command = [
                "semgrep", "scan", "--error", "--config", str(rules),
                "--exclude", ".guardrails/semgrep-tests/fixtures",
                "--exclude", "security/semgrep/tests/fixtures",
                "--exclude", "examples/python-demo/.guardrails/semgrep-tests/fixtures", ".",
            ]
            code, output = runner(command, target)
            return command_record(producer, "semgrep-ce", command, code, output)
        return producer_result(
            producer,
            "not_run",
            reason=f"Host Semgrep version must be exactly {SEMGREP_VERSION}; observed {actual!r}.",
        )
    return producer_result(
        producer,
        "not_run",
        reason=f"Use Docker with {SEMGREP_IMAGE} or install host Semgrep {SEMGREP_VERSION}. {docker_reason}",
    )


def gitleaks_record(producer: str, command: list[str], code: int, output: str) -> dict:
    # Gitleaks can exit successfully after Git fails and no history was scanned.
    if code == 0 and re.search(r"\b0 commits? scanned\b|\bfatal:", output, re.IGNORECASE):
        return producer_result(
            producer, "failed",
            evidence=["Gitleaks did not complete a valid Git history scan.", bounded(output)],
        )
    return command_record(producer, "gitleaks", command, code, output)


def gitleaks_result(
    target: Path,
    *,
    runner: Runner = run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict:
    producer = "Gitleaks CLI 8.30.1"
    shallow_code, shallow_output = runner(["git", "rev-parse", "--is-shallow-repository"], target)
    if shallow_code != 0 or shallow_output.strip() != "false":
        return producer_result(
            producer,
            "not_run",
            reason="Complete Git history is required; shallow or missing history cannot produce secret-detection evidence.",
        )
    if which("docker"):
        code, output = runner(["docker", "version", "--format", "{{.Server.Version}}"], target)
        if code == 0:
            head_code, head = runner(["git", "rev-parse", "--verify", "HEAD^{commit}"], target)
            if head_code != 0 or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head.strip()):
                return producer_result(
                    producer, "not_run", reason="Cannot verify the host Git HEAD for the Docker scan."
                )
            mount = [
                "docker", "run", "--rm", "--network", "none",
                "-v", f"{target.resolve()}:/repo:ro", "-w", "/repo",
            ]
            mount_code, mount_output = runner(
                [*mount, "--entrypoint", "git", GITLEAKS_IMAGE,
                 "rev-parse", "--is-shallow-repository", "HEAD^{commit}"], target,
            )
            if mount_code != 0 or mount_output.strip().splitlines() != ["false", head.strip()]:
                return producer_result(
                    producer, "not_run",
                    reason="Docker must mount complete Git history at the exact host HEAD; mounted history is missing or mismatched.",
                )
            command = [*mount, GITLEAKS_IMAGE, "git", "--redact", "--no-banner", "."]
            scan_code, scan_output = runner(command, target)
            return gitleaks_record(producer, command, scan_code, scan_output)
        docker_reason = bounded(output)
    else:
        docker_reason = "Docker is not installed."
    if which("gitleaks"):
        exact, actual = exact_host_version("gitleaks", GITLEAKS_VERSION, target, runner)
        if exact:
            command = ["gitleaks", "git", "--redact", "--no-banner", "."]
            code, output = runner(command, target)
            return gitleaks_record(producer, command, code, output)
        return producer_result(
            producer,
            "not_run",
            reason=f"Host Gitleaks version must be exactly {GITLEAKS_VERSION}; observed {actual!r}.",
        )
    return producer_result(
        producer,
        "not_run",
        reason=f"Use Docker with {GITLEAKS_IMAGE} or install host Gitleaks {GITLEAKS_VERSION}. {docker_reason}",
    )


def write_evidence(
    path: Path,
    *,
    revision: str,
    control_id: str,
    provider_id: str,
    result: dict,
) -> None:
    document = {
        "version": 2,
        "subject": {"type": "git-commit", "revision": revision},
        "results": {control_id: {provider_id: result}},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("producer", choices=(*COMMAND_PRODUCERS, "semgrep-ce", "gitleaks"))
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.target.resolve()
    try:
        revision = exact_clean_head(target, args.revision)
    except (OSError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2
    if args.producer in COMMAND_PRODUCERS:
        result = repository_command_result(
            args.producer, os.environ, target, revision=revision
        )
        control_id = args.producer
        provider_id = COMMAND_PRODUCERS[args.producer][1]
    elif args.producer == "semgrep-ce":
        result = semgrep_result(target)
        control_id, provider_id = "custom-static-analysis", "semgrep-ce"
    else:
        result = gitleaks_result(target)
        control_id, provider_id = "secret-detection", "gitleaks"
    write_evidence(args.output, revision=revision, control_id=control_id, provider_id=provider_id, result=result)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
