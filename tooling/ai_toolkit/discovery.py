"""Detect repository structure, candidate commands, workflows, and agent clients.

Discovery only reads files. It proposes repository commands as GitHub
repository variables; it never writes them into a committed file, so a pull
request cannot change what CI executes.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

# Capability -> GitHub repository variable the installed workflows read.
COMMAND_VARIABLES = {
    "setup": "GUARDRAILS_SETUP_COMMAND",
    "build": "GUARDRAILS_BUILD_COMMAND",
    "unit-tests": "GUARDRAILS_UNIT_TEST_COMMAND",
    "format-and-lint": "GUARDRAILS_FORMAT_LINT_COMMAND",
    "changed-code-coverage": "GUARDRAILS_CHANGED_COVERAGE_COMMAND",
    "codeql-languages": "GUARDRAILS_CODEQL_LANGUAGES",
}

# Existing workflow content that identifies an integration already present.
WORKFLOW_SIGNATURES = {
    "sonarqube": ("sonarsource/sonarqube-scan-action", "sonarqube-quality-gate-action", "sonar-scanner"),
    "snyk": ("snyk/actions", "snyk test", "snyk code test"),
    "fossa": ("fossas/fossa-action", "fossa analyze", "fossa test"),
    "codeql": ("github/codeql-action",),
    "semgrep": ("semgrep",),
    "gitleaks": ("gitleaks",),
    "dependency-review": ("actions/dependency-review-action",),
}

PROVIDER_CONFIG_FILES = {
    "sonarqube": ("sonar-project.properties",),
    "snyk": (".snyk",),
    "fossa": (".fossa.yml", ".fossa.yaml"),
    "semgrep": (".semgrep.yml", ".semgrep.yaml", ".semgrep"),
}

DOCUMENTATION_FILES = ("README.md", "CONTRIBUTING.md", "AGENTS.md", "SECURITY.md", "ARCHITECTURE.md", "TESTING.md")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def _command(value: str, source: str) -> dict[str, str]:
    return {"command": value, "source": source}


def detect_python(target: Path) -> dict[str, Any] | None:
    pyproject = target / "pyproject.toml"
    markers = [name for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "requirements-dev.txt", "Pipfile", "poetry.lock", "uv.lock")
               if (target / name).is_file()]
    top_level_modules = sorted(path.name for path in target.glob("*.py") if path.is_file())
    if not markers and not top_level_modules:
        return None
    markers.extend(top_level_modules[:3])
    data = _read_toml(pyproject) if pyproject.is_file() else {}
    tool = data.get("tool", {}) if isinstance(data.get("tool"), dict) else {}
    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    dependency_text = " ".join(
        str(item) for item in project.get("dependencies", []) if isinstance(item, str)
    ) + " " + json.dumps(project.get("optional-dependencies", {})) + " " + _read_text(target / "requirements-dev.txt") + " " + _read_text(target / "requirements.txt")
    package_manager = "pip"
    if "poetry.lock" in markers or "poetry" in tool:
        package_manager = "poetry"
    elif "uv.lock" in markers:
        package_manager = "uv"
    elif "Pipfile" in markers:
        package_manager = "pipenv"
    commands: dict[str, dict[str, str]] = {}
    if package_manager == "pip":
        requirement_files = [name for name in ("requirements-dev.txt", "requirements.txt") if (target / name).is_file()]
        if requirement_files:
            commands["setup"] = _command(f"python3 -m pip install -r {requirement_files[0]}", requirement_files[0])
    elif package_manager == "poetry":
        commands["setup"] = _command("poetry install", "poetry.lock")
    elif package_manager == "uv":
        commands["setup"] = _command("uv sync", "uv.lock")
    else:
        commands["setup"] = _command("pipenv install --dev", "Pipfile")
    uses_pytest = "pytest" in tool or "pytest" in dependency_text or (target / "pytest.ini").is_file() or (target / "conftest.py").is_file()
    if uses_pytest:
        commands["unit-tests"] = _command("python3 -m pytest", "pytest configuration or dependency")
    elif any(path.name.startswith("test_") for path in target.rglob("test_*.py") if ".git" not in path.parts):
        commands["unit-tests"] = _command("python3 -m unittest discover", "test_*.py files")
    if "build-system" in data:
        commands["build"] = _command("python3 -m build", "pyproject.toml [build-system]")
    else:
        commands["build"] = _command("python3 -m compileall -q .", "no build-system declared; bytecode compilation only")
    if "ruff" in tool or (target / "ruff.toml").is_file() or "ruff" in dependency_text:
        commands["format-and-lint"] = _command("ruff check .", "ruff configuration or dependency")
    elif (target / ".flake8").is_file() or "flake8" in dependency_text:
        commands["format-and-lint"] = _command("python3 -m flake8", "flake8 configuration or dependency")
    return {"language": "python", "package_manager": package_manager, "markers": markers,
            "codeql_language": "python", "commands": commands}


def detect_node(target: Path) -> dict[str, Any] | None:
    package_json = target / "package.json"
    if not package_json.is_file():
        return None
    data = _read_json(package_json)
    scripts = data.get("scripts", {}) if isinstance(data.get("scripts"), dict) else {}
    package_manager = "npm"
    declared = data.get("packageManager")
    if isinstance(declared, str) and declared.strip():
        package_manager = declared.split("@", 1)[0].strip() or "npm"
        source = "package.json packageManager"
    elif (target / "pnpm-lock.yaml").is_file():
        package_manager, source = "pnpm", "pnpm-lock.yaml"
    elif (target / "yarn.lock").is_file():
        package_manager, source = "yarn", "yarn.lock"
    elif (target / "bun.lockb").is_file() or (target / "bun.lock").is_file():
        package_manager, source = "bun", "bun lockfile"
    else:
        source = "package-lock.json" if (target / "package-lock.json").is_file() else "default"
    run = {"npm": "npm run", "pnpm": "pnpm run", "yarn": "yarn", "bun": "bun run"}.get(package_manager, "npm run")
    install = {"npm": "npm ci", "pnpm": "pnpm install --frozen-lockfile", "yarn": "yarn install --frozen-lockfile", "bun": "bun install --frozen-lockfile"}.get(package_manager, "npm ci")
    commands = {"setup": _command(install, source)}
    for capability, names in (("unit-tests", ("test",)), ("build", ("build",)), ("format-and-lint", ("lint", "check"))):
        for name in names:
            script = scripts.get(name)
            if isinstance(script, str) and script.strip() and "no test specified" not in script:
                commands[capability] = _command(f"{run} {name}", f"package.json scripts.{name}")
                break
    typescript = (target / "tsconfig.json").is_file()
    return {"language": "node", "package_manager": package_manager,
            "markers": ["package.json", *(name for name in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "tsconfig.json") if (target / name).is_file())],
            "codeql_language": "javascript-typescript" if typescript else "javascript", "commands": commands}


def detect_workflows(target: Path) -> list[dict[str, Any]]:
    directory = target / ".github" / "workflows"
    if not directory.is_dir():
        return []
    rows = []
    for path in sorted(directory.iterdir()):
        if path.suffix not in {".yml", ".yaml"} or not path.is_file():
            continue
        text = _read_text(path)
        lowered = text.lower()
        name_match = re.search(r"^name:\s*(.+?)\s*$", text, re.MULTILINE)
        integrations = sorted(
            key for key, signatures in WORKFLOW_SIGNATURES.items()
            if any(signature in lowered for signature in signatures)
        )
        rows.append({
            "path": f".github/workflows/{path.name}",
            "name": name_match.group(1).strip().strip("'\"") if name_match else path.stem,
            "installer_owned": text.startswith("# Guardrails v2 installer-owned"),
            "integrations": integrations,
        })
    return rows


def detect_provider_configuration(target: Path) -> dict[str, list[str]]:
    return {
        provider: [name for name in names if (target / name).exists()]
        for provider, names in PROVIDER_CONFIG_FILES.items()
        if any((target / name).exists() for name in names)
    }


def detect_agent_clients(target: Path, environment: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    environment = dict(os.environ) if environment is None else environment
    home = Path(environment.get("HOME", str(Path.home())))
    codex_home = Path(environment.get("CODEX_HOME", str(home / ".codex")))
    claude_home = Path(environment.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
    return {
        "codex": {
            "detected": codex_home.is_dir(),
            "user_skills_dir": str(codex_home / "skills"),
            "project_skills_dir": ".agents/skills",
            "present_in_project": (target / ".agents" / "skills").is_dir(),
        },
        "claude-code": {
            "detected": claude_home.is_dir(),
            "user_skills_dir": str(claude_home / "skills"),
            "project_skills_dir": ".claude/skills",
            "present_in_project": (target / ".claude" / "skills").is_dir(),
        },
    }


def detect_toolkit_state(target: Path) -> dict[str, Any]:
    guardrails = target / ".guardrails"
    qa_config = [str(path.relative_to(target).as_posix()) for path in target.glob("**/qa/config.yaml")
                 if ".git" not in path.parts and "node_modules" not in path.parts]
    return {
        "guardrails_installed": (guardrails / "policy.yaml").is_file(),
        "guardrails_version": _read_json(guardrails / "policy.yaml").get("version") if (guardrails / "policy.yaml").is_file() else None,
        "toolkit_toml": (target / "toolkit.toml").is_file(),
        "toolkit_lock": (target / "toolkit.lock.json").is_file(),
        "qa_configurations": qa_config,
    }


def discover(target: Path, environment: dict[str, str] | None = None) -> dict[str, Any]:
    languages = [row for row in (detect_python(target), detect_node(target)) if row]
    commands: dict[str, dict[str, str]] = {}
    for row in languages:
        for capability, command in row["commands"].items():
            commands.setdefault(capability, command)
    if languages:
        commands["codeql-languages"] = _command(",".join(row["codeql_language"] for row in languages), "detected languages")
    return {
        "version": 1,
        "kind": "toolkit-discovery",
        "languages": languages,
        "commands": commands,
        "variables": {COMMAND_VARIABLES[capability]: row["command"] for capability, row in commands.items() if capability in COMMAND_VARIABLES},
        "workflows": detect_workflows(target),
        "provider_configuration": detect_provider_configuration(target),
        "documentation": [name for name in DOCUMENTATION_FILES if (target / name).is_file()] + (["docs/"] if (target / "docs").is_dir() else []),
        "agent_clients": detect_agent_clients(target, environment),
        "toolkit": detect_toolkit_state(target),
    }


def existing_integrations(discovery: dict[str, Any]) -> dict[str, list[str]]:
    """Integrations already present, keyed by provider, with the files that show them."""
    found: dict[str, list[str]] = {}
    for workflow in discovery.get("workflows", []):
        for integration in workflow.get("integrations", []):
            found.setdefault(integration, []).append(workflow["path"])
    for provider, files in discovery.get("provider_configuration", {}).items():
        found.setdefault(provider, []).extend(files)
    return found


def render(discovery: dict[str, Any]) -> str:
    lines = ["Discovery"]
    if discovery["languages"]:
        for row in discovery["languages"]:
            lines.append(f"- {row['language']} ({row['package_manager']}): {', '.join(row['markers'])}")
    else:
        lines.append("- No Python or Node project markers found; commands must be supplied manually.")
    if discovery["commands"]:
        lines.append("Proposed repository variables (never committed; set with gh or in repository settings):")
        for capability, row in sorted(discovery["commands"].items()):
            lines.append(f"  {COMMAND_VARIABLES[capability]}={row['command']!r}  # from {row['source']}")
    integrations = existing_integrations(discovery)
    if integrations:
        lines.append("Existing integrations (will not be duplicated):")
        for provider, files in sorted(integrations.items()):
            lines.append(f"  {provider}: {', '.join(sorted(set(files)))}")
    workflows = [row for row in discovery["workflows"] if not row["installer_owned"]]
    if workflows:
        lines.append("Existing workflows not owned by the installer: " + ", ".join(row["path"] for row in workflows))
    clients = [name for name, row in discovery["agent_clients"].items() if row["detected"]]
    lines.append("Agent clients detected: " + (", ".join(clients) if clients else "none"))
    state = discovery["toolkit"]
    lines.append("Guardrails installed: " + ("yes" if state["guardrails_installed"] else "no")
                 + "; toolkit.toml: " + ("present" if state["toolkit_toml"] else "absent")
                 + "; lock: " + ("present" if state["toolkit_lock"] else "absent"))
    if state["qa_configurations"]:
        lines.append("QA configuration: " + ", ".join(state["qa_configurations"]))
    return "\n".join(lines) + "\n"
