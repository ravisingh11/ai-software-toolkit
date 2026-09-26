"""``toolkit.toml`` and ``toolkit.lock.json``.

``toolkit.toml`` holds only what nothing else owns: installed components, agent
client preferences, and the paths of the authoritative Guardrails files. Policy
and provider selection stay in ``.guardrails/`` and are mutated only through
``configure.py``. Repository commands are never stored here.

``toolkit.lock.json`` records the toolkit revision, installed components, and a
SHA-256 for every managed file so ``update`` can tell unmodified files (refresh)
from modified ones (preserve and report) and unmanaged ones (never touch).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .runtime import ToolkitError, load_json, sha256_file

COMPONENTS = ("guardrails", "skills", "qa")
CLIENTS = ("codex", "claude-code")
TOML_NAME = "toolkit.toml"
LOCK_NAME = "toolkit.lock.json"
LOCK_VERSION = 1

TOML_TEMPLATE = """# AI Software Toolkit configuration. Policy and provider selection live in
# .guardrails/ and are changed with .guardrails/configure.py; repository
# commands live in GitHub repository variables, never in this file.

[toolkit]
revision = {revision}
components = [{components}]

[agents]
clients = [{clients}]
skills_dir = {skills_dir}

[guardrails]
policy = {policy}
providers = {providers}
profiles = {profiles}
"""


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_list(values: list[str]) -> str:
    return ", ".join(_toml_string(value) for value in values)


def default_configuration(revision: str, *, components: list[str], clients: list[str], skills_dir: str = ".agents/skills") -> dict[str, Any]:
    return {
        "toolkit": {"revision": revision, "components": list(components)},
        "agents": {"clients": list(clients), "skills_dir": skills_dir},
        "guardrails": {
            "policy": ".guardrails/policy.yaml",
            "providers": ".guardrails/providers.yaml",
            "profiles": ".guardrails/profiles.yaml",
        },
    }


def validate_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
    toolkit = configuration.get("toolkit")
    agents = configuration.get("agents", {})
    guardrails = configuration.get("guardrails", {})
    if not isinstance(toolkit, dict) or not isinstance(agents, dict) or not isinstance(guardrails, dict):
        raise ToolkitError(f"{TOML_NAME} must contain [toolkit], [agents], and [guardrails] tables")
    components = toolkit.get("components")
    if not isinstance(components, list) or not components or any(item not in COMPONENTS for item in components):
        raise ToolkitError(f"{TOML_NAME} components must be a nonempty list drawn from {', '.join(COMPONENTS)}")
    clients = agents.get("clients", [])
    if not isinstance(clients, list) or any(item not in CLIENTS for item in clients):
        raise ToolkitError(f"{TOML_NAME} agents.clients must be drawn from {', '.join(CLIENTS)}")
    skills_dir = agents.get("skills_dir", ".agents/skills")
    if not isinstance(skills_dir, str) or not skills_dir.strip() or Path(skills_dir).is_absolute() or ".." in Path(skills_dir).parts:
        raise ToolkitError(f"{TOML_NAME} agents.skills_dir must be a repository-relative directory")
    for key in ("policy", "providers", "profiles"):
        value = guardrails.get(key, f".guardrails/{key}.yaml")
        if not isinstance(value, str) or Path(value).is_absolute() or ".." in Path(value).parts:
            raise ToolkitError(f"{TOML_NAME} guardrails.{key} must be a repository-relative path")
        guardrails[key] = value
    revision = toolkit.get("revision", "")
    if not isinstance(revision, str):
        raise ToolkitError(f"{TOML_NAME} toolkit.revision must be a string")
    return {"toolkit": {"revision": revision, "components": list(components)},
            "agents": {"clients": list(clients), "skills_dir": skills_dir},
            "guardrails": {key: guardrails[key] for key in ("policy", "providers", "profiles")}}


def render_configuration(configuration: dict[str, Any]) -> str:
    configuration = validate_configuration(configuration)
    return TOML_TEMPLATE.format(
        revision=_toml_string(configuration["toolkit"]["revision"]),
        components=_toml_list(configuration["toolkit"]["components"]),
        clients=_toml_list(configuration["agents"]["clients"]),
        skills_dir=_toml_string(configuration["agents"]["skills_dir"]),
        policy=_toml_string(configuration["guardrails"]["policy"]),
        providers=_toml_string(configuration["guardrails"]["providers"]),
        profiles=_toml_string(configuration["guardrails"]["profiles"]),
    )


def read_configuration(target: Path) -> dict[str, Any] | None:
    path = target / TOML_NAME
    if not path.is_file():
        return None
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise ToolkitError(f"cannot read {TOML_NAME}: {error}") from error
    return validate_configuration(document)


def write_configuration(target: Path, configuration: dict[str, Any]) -> Path:
    path = target / TOML_NAME
    if path.is_symlink():
        raise ToolkitError(f"refusing to write through a symlink: {path}")
    path.write_text(render_configuration(configuration), encoding="utf-8")
    return path


def hash_managed(target: Path, paths: list[str]) -> dict[str, str]:
    hashes = {}
    for relative_path in sorted(set(paths)):
        path = target / relative_path
        if path.is_file():
            hashes[relative_path] = sha256_file(path)
    return hashes


def build_lock(revision: str, *, components: list[str], managed: dict[str, str], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    lock = {"version": LOCK_VERSION, "toolkit": {"revision": revision}, "components": sorted(components), "managed": dict(sorted(managed.items()))}
    if previous:
        lock["previous"] = previous
    return lock


def read_lock(target: Path) -> dict[str, Any] | None:
    path = target / LOCK_NAME
    if not path.is_file():
        return None
    lock = load_json(path)
    managed = lock.get("managed")
    if lock.get("version") != LOCK_VERSION or not isinstance(lock.get("toolkit"), dict) or not isinstance(managed, dict):
        raise ToolkitError(f"{LOCK_NAME} has an unsupported shape; delete it and run update to rebuild it")
    for relative_path, digest in managed.items():
        if not isinstance(relative_path, str) or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts or not isinstance(digest, str):
            raise ToolkitError(f"{LOCK_NAME} contains an invalid managed entry")
    return lock


def write_lock(target: Path, lock: dict[str, Any]) -> Path:
    path = target / LOCK_NAME
    if path.is_symlink():
        raise ToolkitError(f"refusing to write through a symlink: {path}")
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return path


def classify(target: Path, lock: dict[str, Any] | None, managed_now: list[str]) -> dict[str, list[str]]:
    """Split the managed set into unmodified, modified, missing, and new paths."""
    recorded = lock.get("managed", {}) if lock else {}
    result: dict[str, list[str]] = {"unmodified": [], "modified": [], "missing": [], "new": [], "removed": []}
    for relative_path in sorted(set(managed_now)):
        path = target / relative_path
        if relative_path not in recorded:
            result["new"].append(relative_path)
        elif not path.is_file():
            result["missing"].append(relative_path)
        elif sha256_file(path) == recorded[relative_path]:
            result["unmodified"].append(relative_path)
        else:
            result["modified"].append(relative_path)
    result["removed"] = sorted(set(recorded) - set(managed_now))
    return result
