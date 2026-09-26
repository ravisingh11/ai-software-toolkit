"""Locate the toolkit source tree, the target repository, and its installed runtime."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import VERSION

ROOT = Path(__file__).resolve().parents[2]
BUILD_METADATA = Path(__file__).resolve().parent / "BUILD.json"

# Existing scripts the CLI dispatches to. Source paths are relative to ROOT;
# installed paths are relative to <target>/.guardrails and are preferred for
# evaluation so an installed repository never runs code from the archive.
SCRIPTS = {
    "install": ("tooling/install.py", None),
    "doctor": ("tooling/doctor.py", "doctor.py"),
    "scan": ("tooling/scan_repository.py", "scan.py"),
    "configure": ("tooling/configure_guardrails.py", "configure.py"),
    "skills": ("tooling/install-skills.sh", None),
}


class ToolkitError(ValueError):
    """A user-facing failure; the CLI prints the message and exits 2."""


def build_metadata() -> dict[str, Any]:
    if BUILD_METADATA.is_file():
        try:
            value = json.loads(BUILD_METADATA.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def revision() -> str:
    """The toolkit revision: archive metadata, else git describe, else the version."""
    described = build_metadata().get("revision")
    if isinstance(described, str) and described.strip():
        return described.strip()
    if shutil.which("git") and (ROOT / ".git").exists():
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "describe", "--tags", "--always", "--dirty"],
            text=True, capture_output=True,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout.strip()
    return VERSION


def resolve_target(value: Path | str | None) -> Path:
    target = Path(value or Path.cwd()).resolve()
    if not target.is_dir():
        raise ToolkitError(f"target is not a directory: {target}")
    return target


def installed_runtime(target: Path) -> Path | None:
    runtime = target / ".guardrails"
    return runtime if (runtime / "policy.yaml").is_file() and (runtime / "scan.py").is_file() else None


def script_path(name: str, target: Path, *, prefer_installed: bool = True) -> Path:
    source_relative, installed_relative = SCRIPTS[name]
    if prefer_installed and installed_relative:
        runtime = installed_runtime(target)
        if runtime and (runtime / installed_relative).is_file():
            return runtime / installed_relative
    path = ROOT / source_relative
    if not path.is_file():
        raise ToolkitError(f"toolkit script is missing from this distribution: {source_relative}")
    return path


def run_python(script: Path, arguments: list[str], *, cwd: Path, capture: bool = False,
               environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(script), *arguments]
    return subprocess.run(command, cwd=cwd, text=True, capture_output=capture,
                          env=environment if environment is not None else os.environ.copy())


def run_shell(script: Path, arguments: list[str], *, cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(script), *arguments], cwd=cwd, text=True, capture_output=capture)


def git_output(target: Path, arguments: list[str]) -> str | None:
    if not shutil.which("git"):
        return None
    completed = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *arguments],
        cwd=target, text=True, capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def head_revision(target: Path) -> str | None:
    return git_output(target, ["rev-parse", "--verify", "HEAD^{commit}"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolkitError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ToolkitError(f"{path.name} must contain an object")
    return value


def relative(path: Path, target: Path) -> str:
    try:
        return path.resolve().relative_to(target.resolve()).as_posix()
    except ValueError:
        return str(path)
