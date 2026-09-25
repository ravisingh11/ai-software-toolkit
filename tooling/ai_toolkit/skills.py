"""Install canonical skills into Codex and Claude Code locations.

One canonical source (``skills/`` in the toolkit) is copied to client-specific
directories. Existing skill directories are never overwritten unless the
caller chooses ``merge`` (add missing files) or ``replace``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .runtime import ROOT, ToolkitError, sha256_file

SHARED_BUNDLE = "_shared-project-ops"
STARTER_SKILLS = (
    "toolkit-setup",
    "prepare-safe-change",
    "code-review",
    "test-gap-finder",
    "security-audit-lite",
    "dependency-risk-review",
    "qa-bootstrap",
)
CLIENT_PROJECT_DIRS = {"codex": ".agents/skills", "claude-code": ".claude/skills"}


def source_dir() -> Path:
    return ROOT / "skills"


def canonical_skills() -> list[str]:
    return sorted(path.parent.name for path in source_dir().glob("*/SKILL.md"))


def client_user_dir(client: str, environment: dict[str, str] | None = None) -> Path:
    environment = dict(os.environ) if environment is None else environment
    home = Path(environment.get("HOME", str(Path.home())))
    if client == "codex":
        return Path(environment.get("CODEX_HOME", str(home / ".codex"))) / "skills"
    if client == "claude-code":
        return Path(environment.get("CLAUDE_CONFIG_DIR", str(home / ".claude"))) / "skills"
    raise ToolkitError(f"unknown agent client: {client}")


def client_project_dir(client: str, target: Path) -> Path:
    try:
        return target / CLIENT_PROJECT_DIRS[client]
    except KeyError as error:
        raise ToolkitError(f"unknown agent client: {client}") from error


def resolve_skills(names: list[str]) -> list[str]:
    available = canonical_skills()
    if names == ["all"]:
        return available
    if names == ["starter"]:
        return [name for name in STARTER_SKILLS if name in available]
    missing = [name for name in names if name not in available]
    if missing:
        raise ToolkitError("unknown skills: " + ", ".join(missing))
    return list(dict.fromkeys(names))


def skill_files(name: str) -> list[Path]:
    root = source_dir() / name
    if not root.is_dir():
        raise ToolkitError(f"skill not found: {name}")
    return sorted(path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)


def _reject_symlinks(destination_root: Path, path: Path) -> None:
    component = destination_root
    for part in path.relative_to(destination_root).parts:
        component /= part
        if component.is_symlink():
            raise ToolkitError(f"refusing to write through a symlink: {component}")


def install_skills(names: list[str], destination_root: Path, *, existing: str = "skip", dry_run: bool = False) -> list[dict[str, Any]]:
    """Copy skills; returns one row per skill with the action taken and the files written."""
    if existing not in {"skip", "merge", "replace"}:
        raise ToolkitError("existing must be skip, merge, or replace")
    selected = list(names)
    if selected and SHARED_BUNDLE not in selected and (source_dir() / SHARED_BUNDLE).is_dir():
        selected.append(SHARED_BUNDLE)
    rows = []
    for name in selected:
        files = skill_files(name)
        destination = destination_root / name
        if destination.exists() and not destination.is_dir():
            raise ToolkitError(f"skill destination exists but is not a directory: {destination}")
        if destination.is_dir():
            action = existing
        else:
            action = "install"
        written: list[str] = []
        if action == "skip":
            rows.append({"skill": name, "action": "skip", "destination": str(destination), "files": []})
            continue
        for source in files:
            relative_path = source.relative_to(source_dir() / name)
            file_destination = destination / relative_path
            if action == "merge" and file_destination.exists():
                continue
            written.append(f"{name}/{relative_path.as_posix()}")
            if dry_run or (file_destination.is_file() and sha256_file(file_destination) == sha256_file(source)):
                continue
            file_destination.parent.mkdir(parents=True, exist_ok=True)
            _reject_symlinks(destination_root, file_destination)
            shutil.copy2(source, file_destination)
        if action == "replace" and not dry_run:
            expected = {(destination / source.relative_to(source_dir() / name)) for source in files}
            for path in sorted(destination.rglob("*"), reverse=True):
                if path.is_file() and path not in expected:
                    path.unlink()
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
        rows.append({"skill": name, "action": action, "destination": str(destination), "files": written})
    return rows


def managed_skill_files(target: Path, skills_root: Path) -> list[str]:
    """Repository-relative files of canonical skills present under ``skills_root``."""
    managed = []
    if not skills_root.is_dir():
        return managed
    canonical = set(canonical_skills()) | {SHARED_BUNDLE}
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or entry.name not in canonical:
            continue
        for source in skill_files(entry.name):
            relative_path = entry / source.relative_to(source_dir() / entry.name)
            managed.append(relative_path.relative_to(target).as_posix())
    return managed
