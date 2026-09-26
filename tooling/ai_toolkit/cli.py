"""``ai-toolkit`` command-line entry point."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import VERSION, config, discovery, report, skills
from .runtime import ROOT, ToolkitError, installed_runtime, relative, resolve_target, revision, run_python, script_path

INSTALLER_MARKER = "# Guardrails v2 installer-owned workflow."
ADAPTER_PROVIDERS = {
    "snyk-code": "snyk code test; SNYK_CODE_ARGS",
    "snyk-open-source": "snyk test; SNYK_OPEN_SOURCE_ARGS",
    "fossa": "fossa analyze then fossa test; FOSSA_ARGS",
}


def _installer():
    """Load tooling/install.py as a module to reuse its plan and ownership helpers."""
    path = ROOT / "tooling" / "install.py"
    spec = importlib.util.spec_from_file_location("ai_toolkit_installer", path)
    if not spec or not spec.loader:
        raise ToolkitError("the installer is missing from this distribution")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _print(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _emit(payload: dict[str, Any], as_json: bool, text: str) -> None:
    _print(json.dumps(payload, indent=2) if as_json else text)


# --------------------------------------------------------------------------- managed files

def installed_profiles(target: Path) -> list[str]:
    policy = target / ".guardrails" / "policy.yaml"
    if not policy.is_file():
        return ["core"]
    try:
        profiles = json.loads(policy.read_text(encoding="utf-8")).get("profiles", ["core"])
    except (OSError, json.JSONDecodeError, AttributeError):
        return ["core"]
    return [profile for profile in profiles if profile in {"core", "github"}] or ["core"]


def guardrails_managed(target: Path, *, profiles: list[str] | None = None, no_actions: bool | None = None) -> list[str]:
    installer = _installer()
    profiles = profiles if profiles is not None else installed_profiles(target)
    if no_actions is None:
        workflows = target / ".github" / "workflows"
        no_actions = not any((workflows / name).is_file() for name in installer.CORE_WORKFLOWS)
    badge = any(
        (target / ".github" / "workflows" / name).is_file() and installer.installer_owned_workflow(target / ".github" / "workflows" / name)
        for name in installer.BADGE_WORKFLOWS
    )
    plan = installer.build_plan(target, profiles=profiles, no_actions=no_actions, scorecard_badge=badge)
    return sorted(relative(item.destination, target) for item in plan)


def skills_managed(target: Path, configuration: dict[str, Any] | None) -> list[str]:
    roots = {target / config.default_configuration("", components=["skills"], clients=[])["agents"]["skills_dir"]}
    if configuration:
        roots.add(target / configuration["agents"]["skills_dir"])
        for client in configuration["agents"]["clients"]:
            roots.add(skills.client_project_dir(client, target))
    managed: list[str] = []
    for root in sorted(roots):
        managed.extend(skills.managed_skill_files(target, root))
    return sorted(set(managed))


def managed_files(target: Path, configuration: dict[str, Any] | None) -> list[str]:
    components = configuration["toolkit"]["components"] if configuration else list(config.COMPONENTS)
    managed: list[str] = []
    if "guardrails" in components and installed_runtime(target):
        managed.extend(guardrails_managed(target))
    if "skills" in components or "qa" in components:
        managed.extend(skills_managed(target, configuration))
    return sorted(set(managed))


def canonical_sources(target: Path, configuration: dict[str, Any] | None) -> dict[str, Path]:
    """Managed repository-relative path -> canonical source file in this distribution."""
    installer = _installer()
    sources: dict[str, Path] = {}
    if installed_runtime(target):
        for item in installer.build_plan(target, profiles=installed_profiles(target), no_actions=False, scorecard_badge=True):
            sources[relative(item.destination, target)] = item.source
    for relative_path in skills_managed(target, configuration):
        parts = Path(relative_path).parts
        canonical = next((skills.source_dir().joinpath(*parts[index:]) for index in range(len(parts))
                          if skills.source_dir().joinpath(*parts[index:]).is_file()), None)
        if canonical is not None:
            sources[relative_path] = canonical
    return sources


def preserved_configuration() -> set[str]:
    return {path.as_posix() for path in _installer().PRESERVED_CONFIGURATION}


def bootstrap_classification(target: Path, managed: list[str], configuration: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Without a lock, use installer ownership to decide what is safe to refresh."""
    installer = _installer()
    preserved = preserved_configuration()
    result: dict[str, list[str]] = {"unmodified": [], "modified": [], "missing": [], "new": [], "removed": []}
    sources = canonical_sources(target, configuration)
    for relative_path in managed:
        path = target / relative_path
        source = sources.get(relative_path)
        if not path.is_file():
            result["missing"].append(relative_path)
        elif relative_path in preserved:
            result["unmodified"].append(relative_path)
        elif relative_path.startswith(".github/workflows/"):
            (result["unmodified"] if installer.installer_owned_workflow(path) else result["modified"]).append(relative_path)
        elif relative_path.startswith(".guardrails/") and source is not None:
            (result["unmodified"] if installer.installer_owned_runtime(path, source) else result["modified"]).append(relative_path)
        else:
            same = source is not None and source.read_bytes() == path.read_bytes()
            (result["unmodified"] if same else result["modified"]).append(relative_path)
    return result


# --------------------------------------------------------------------------- commands

def quiet_environment() -> dict[str, str]:
    """Do not leave bytecode in the target; a dirty worktree blocks local evidence."""
    environment = dict(os.environ)
    environment.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return environment


def cmd_discover(args: argparse.Namespace) -> int:
    target = resolve_target(args.target)
    found = discovery.discover(target)
    _emit(found, args.json, discovery.render(found))
    return 0


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _existing_variables(target: Path) -> set[str] | None:
    if not _gh_available():
        return None
    completed = subprocess.run(["gh", "variable", "list", "--json", "name"], cwd=target, text=True, capture_output=True)
    if completed.returncode != 0:
        return None
    try:
        rows = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return {row.get("name") for row in rows if isinstance(row, dict)}


def apply_variables(target: Path, variables: dict[str, str], *, dry_run: bool) -> list[dict[str, Any]]:
    existing = _existing_variables(target)
    rows = []
    for name, value in sorted(variables.items()):
        if existing is not None and name in existing:
            rows.append({"name": name, "action": "kept", "detail": "already set in the repository"})
            continue
        if dry_run or not _gh_available():
            rows.append({"name": name, "action": "manual", "detail": f"gh variable set {name} --body {json.dumps(value)}"})
            continue
        completed = subprocess.run(["gh", "variable", "set", name, "--body", value], cwd=target, text=True, capture_output=True)
        rows.append({"name": name, "action": "set" if completed.returncode == 0 else "failed",
                     "detail": value if completed.returncode == 0 else (completed.stderr or completed.stdout).strip()})
    return rows


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def cmd_init(args: argparse.Namespace) -> int:
    target = resolve_target(args.target)
    components = [item.strip() for item in args.components.split(",") if item.strip()]
    for component in components:
        if component not in config.COMPONENTS:
            raise ToolkitError(f"unknown component: {component}")
    clients = [item.strip() for item in args.clients.split(",") if item.strip()] if args.clients else []
    found = discovery.discover(target)
    if not clients:
        clients = [name for name, row in found["agent_clients"].items() if row["detected"]] or ["codex"]
    for client in clients:
        if client not in config.CLIENTS:
            raise ToolkitError(f"unknown agent client: {client}")
    existing_configuration = config.read_configuration(target)
    already_installed = bool(installed_runtime(target))
    profiles = ["github"] if args.profile == "github" else []
    preview: dict[str, Any] = {"target": str(target), "components": components, "clients": clients, "discovery": found,
                               "guardrails": [], "skills": [], "variables": [], "adopt_existing": already_installed}

    if "guardrails" in components:
        arguments = ["--target", str(target), "--dry-run"]
        for profile in profiles:
            arguments.extend(["--profile", profile])
        if args.no_actions:
            arguments.append("--no-actions")
        if already_installed:
            arguments.append("--merge-existing")
        completed = run_python(script_path("install", target, prefer_installed=False), arguments, cwd=target, capture=True)
        if completed.returncode != 0:
            raise ToolkitError("installer preview failed: " + (completed.stderr or completed.stdout).strip())
        preview["guardrails"] = [line[len("- install: "):] for line in completed.stdout.splitlines() if line.startswith("- install: ")]
    selected_skills = skills.resolve_skills(args.skills.split(",") if args.skills else ["starter"]) if ("skills" in components or "qa" in components) else []
    if "qa" in components and "qa-bootstrap" not in selected_skills and "qa-bootstrap" in skills.canonical_skills():
        selected_skills.append("qa-bootstrap")
    if "skills" not in components:
        selected_skills = [name for name in selected_skills if name == "qa-bootstrap"]
    for client in clients:
        destination = skills.client_project_dir(client, target)
        rows = skills.install_skills(selected_skills, destination, existing="merge", dry_run=True) if selected_skills else []
        preview["skills"].append({"client": client, "destination": relative(destination, target), "skills": rows})
    preview["variables"] = apply_variables(target, found["variables"], dry_run=True) if found["variables"] else []

    lines = [discovery.render(found), "Planned changes:"]
    if preview["guardrails"]:
        lines.append(f"  Guardrails runtime and workflows ({len(preview['guardrails'])} files){' — filling gaps in the existing installation' if already_installed else ''}:")
        lines.extend(f"    {relative(Path(path), target)}" for path in preview["guardrails"])
    elif "guardrails" in components:
        lines.append("  Guardrails: already installed; nothing to add (use `ai-toolkit update` to refresh).")
    for row in preview["skills"]:
        names = [item["skill"] for item in row["skills"] if item["action"] != "skip"]
        skipped = [item["skill"] for item in row["skills"] if item["action"] == "skip"]
        lines.append(f"  Skills for {row['client']} -> {row['destination']}: {', '.join(names) or 'none'}" + (f" (existing kept: {', '.join(skipped)})" if skipped else ""))
    lines.append("  toolkit.toml and toolkit.lock.json" + (" (update)" if existing_configuration else " (create)"))
    ignore_rules = gitignore_additions(target, found)
    if ignore_rules:
        lines.append(f"  .gitignore: add {', '.join(ignore_rules)} (scan output and bytecode are never committed)")
    if preview["variables"]:
        lines.append("  Repository variables (set with --apply-variables, or run these yourself):")
        lines.extend(f"    {row['detail']}" for row in preview["variables"])
    lines.append("")
    if args.preview:
        lines.append("Preview only; nothing was written.")
        _emit(preview, args.json, "\n".join(lines))
        return 0
    if not args.yes and not _confirm("Apply these changes? [y/N] "):
        lines.append("Nothing was written. Re-run with --yes to apply, or --preview to inspect.")
        _emit(preview, args.json, "\n".join(lines))
        return 0

    applied: dict[str, Any] = {"guardrails": [], "skills": [], "variables": [], "files": []}
    if "guardrails" in components and preview["guardrails"]:
        arguments = ["--target", str(target)]
        for profile in profiles:
            arguments.extend(["--profile", profile])
        if args.no_actions:
            arguments.append("--no-actions")
        if already_installed:
            arguments.append("--merge-existing")
        completed = run_python(script_path("install", target, prefer_installed=False), arguments, cwd=target, capture=True)
        if completed.returncode != 0:
            raise ToolkitError("installer failed: " + (completed.stderr or completed.stdout).strip())
        applied["guardrails"] = preview["guardrails"]
    for client in clients:
        destination = skills.client_project_dir(client, target)
        rows = skills.install_skills(selected_skills, destination, existing="merge") if selected_skills else []
        applied["skills"].append({"client": client, "destination": relative(destination, target), "skills": rows})
    if args.apply_variables and found["variables"]:
        applied["variables"] = apply_variables(target, found["variables"], dry_run=False)
    configuration = config.default_configuration(revision(), components=components, clients=clients,
                                                 skills_dir=skills.CLIENT_PROJECT_DIRS[clients[0]])
    config.write_configuration(target, configuration)
    managed = managed_files(target, configuration)
    config.write_lock(target, config.build_lock(revision(), components=components, managed=config.hash_managed(target, managed)))
    applied["files"] = [config.TOML_NAME, config.LOCK_NAME]
    if ensure_gitignore(target, found):
        applied["files"].append(".gitignore")
    lines = ["Applied.", f"  Guardrails files: {len(applied['guardrails'])}"]
    for row in applied["skills"]:
        lines.append(f"  Skills for {row['client']}: " + ", ".join(f"{item['skill']} ({item['action']})" for item in row["skills"]))
    for row in applied["variables"]:
        lines.append(f"  Variable {row['name']}: {row['action']} — {row['detail']}")
    lines.append(f"  Wrote {config.TOML_NAME} and {config.LOCK_NAME} ({len(managed)} managed files).")
    lines.append("")
    lines.append("Next: commit these files, set any variables listed above, then run `ai-toolkit doctor` and `ai-toolkit check`.")
    _emit({"preview": preview, "applied": applied}, args.json, "\n".join(lines))
    return 0


def gitignore_additions(target: Path, found: dict[str, Any]) -> list[str]:
    """Ignore rules the scan needs that .gitignore lacks; existing rules are never changed."""
    path = target / ".gitignore"
    existing = {line.strip().lstrip("/") for line in (path.read_text(encoding="utf-8").splitlines() if path.is_file() else [])}
    wanted = [".artifacts/"]
    if any(row["language"] == "python" for row in found.get("languages", [])):
        wanted.append("__pycache__/")
    return [rule for rule in wanted if rule not in existing and rule.rstrip("/") not in existing]


def ensure_gitignore(target: Path, found: dict[str, Any]) -> bool:
    """Merge required ignore rules into .gitignore; never overwrite existing rules."""
    path = target / ".gitignore"
    additions = gitignore_additions(target, found)
    if path.is_symlink() or not additions:
        return False
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + separator + "# AI Software Toolkit scan artifacts\n" + "".join(rule + "\n" for rule in additions), encoding="utf-8")
    return True


def component_states(target: Path, configuration: dict[str, Any] | None, lock: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    runtime = installed_runtime(target)
    components = configuration["toolkit"]["components"] if configuration else list(config.COMPONENTS)
    if "guardrails" in components:
        if runtime:
            states["guardrails"] = {"state": "installed", "message": f".guardrails/ runtime present (profiles: {', '.join(installed_profiles(target))})."}
        else:
            states["guardrails"] = {"state": "missing", "message": ".guardrails/ runtime is not installed.", "next_step": "Run `ai-toolkit init`."}
    if "skills" in components or "qa" in components:
        found = []
        for client in (configuration["agents"]["clients"] if configuration else config.CLIENTS):
            root = skills.client_project_dir(client, target)
            names = sorted(path.name for path in root.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()) if root.is_dir() else []
            found.append(f"{client}: {len(names)} skills in {relative(root, target)}" if names else f"{client}: none")
        state = "installed" if any(": none" not in item for item in found) else "missing"
        states["skills"] = {"state": state, "message": "; ".join(found), **({} if state == "installed" else {"next_step": "Run `ai-toolkit skills install --skill starter`."})}
    if "qa" in components:
        qa = discovery.detect_toolkit_state(target)["qa_configurations"]
        states["qa"] = {"state": "configured" if qa else "missing", "message": ("QA configuration: " + ", ".join(qa)) if qa else "No generated qa skill found.",
                        **({} if qa else {"next_step": "Run the qa-bootstrap skill in your agent to generate the qa orchestrator."})}
    states["toolkit"] = {
        "state": "configured" if configuration and lock else "installed" if configuration or lock else "missing",
        "message": f"{config.TOML_NAME} {'present' if configuration else 'absent'}; {config.LOCK_NAME} {'present' if lock else 'absent'}"
                   + (f"; revision {lock['toolkit'].get('revision')}" if lock else ""),
        **({} if configuration and lock else {"next_step": "Run `ai-toolkit init` to record the installation."}),
    }
    return states


def cmd_doctor(args: argparse.Namespace) -> int:
    target = resolve_target(args.target)
    configuration = config.read_configuration(target)
    lock = config.read_lock(target)
    components = component_states(target, configuration, lock)
    doctor_report: dict[str, Any] = {"checks": [], "summary": {}}
    rows: list[dict[str, Any]] = []
    exit_code = 0
    if installed_runtime(target):
        arguments = ["--target", str(target), "--operation", args.operation, "--json"]
        if args.github:
            arguments.extend(["--github", args.github])
        completed = run_python(script_path("doctor", target), arguments, cwd=target, capture=True, environment=quiet_environment())
        if not completed.stdout.strip():
            raise ToolkitError("setup diagnostic unavailable: " + (completed.stderr or "").strip())
        doctor_report = json.loads(completed.stdout)
        rows = report.verified_rows(target, doctor_report)
        exit_code = 1 if doctor_report.get("summary", {}).get("action_needed") else 0
    else:
        exit_code = 1
    payload = {"version": 1, "kind": "toolkit-doctor", "components": components, "capabilities": rows, "guardrails": doctor_report}
    _emit(payload, args.json, report.render_doctor(target, doctor_report, rows, components))
    return exit_code


def cmd_check(args: argparse.Namespace) -> int:
    target = resolve_target(args.target)
    if not installed_runtime(target):
        raise ToolkitError("the Guardrails runtime is not installed; run `ai-toolkit init` first")
    arguments = ["--target", str(target), "--operation", args.operation, "--base-ref", args.base_ref, "--json"]
    if args.revision:
        arguments.extend(["--revision", args.revision])
    completed = run_python(script_path("scan", target), arguments, cwd=target, capture=True, environment=quiet_environment())
    if not completed.stdout.strip():
        raise ToolkitError("scan failed: " + (completed.stderr or "").strip())
    try:
        card = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ToolkitError(f"scan produced unreadable output: {error}") from error
    artifacts = card.get("artifacts", {}) if isinstance(card.get("artifacts"), dict) else {}
    _emit(card, args.json, report.render_check(card, evidence_path=artifacts.get("evidence"), report_path=artifacts.get("report")))
    return 0 if card.get("decision") == "allow" else 1


def providers_document(target: Path) -> dict[str, Any]:
    runtime = installed_runtime(target)
    path = runtime / "providers.yaml" if runtime else ROOT / "policies" / "provider-config.yaml"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolkitError(f"cannot read provider configuration: {error}") from error
    return document


def declared_credential_names(provider: dict[str, Any]) -> list[str]:
    """Names of the GitHub secrets a provider declares. Values are never read or printed."""
    for key, value in provider.items():
        if key == "secrets" and isinstance(value, list):
            return [name for name in value if isinstance(name, str)]
    return []


def cmd_providers(args: argparse.Namespace) -> int:
    target = resolve_target(args.target)
    document = providers_document(target)
    providers = document.get("providers", {})
    selections = document.get("selections", {})
    if args.action == "select":
        if not args.selection:
            raise ToolkitError("select requires CAPABILITY=PROVIDER")
        completed = run_python(script_path("configure", target), ["--select-provider", args.selection], cwd=target)
        return completed.returncode
    rows = []
    for provider_id, provider in sorted(providers.items()):
        authoritative = sorted(capability for capability, selection in selections.items()
                               if isinstance(selection, dict) and selection.get("authoritative") == provider_id)
        rows.append({
            "id": provider_id,
            "display_name": provider.get("display_name", provider_id),
            "activation": provider.get("activation"),
            "capabilities": provider.get("capabilities", []),
            "authoritative_for": authoritative,
            "credential_names": declared_credential_names(provider),
            "template": provider.get("template"),
            "template_available": bool(provider.get("template_available")),
            "enabled_by_default": bool(provider.get("enabled_by_default")),
        })
    if args.action == "show":
        rows = [row for row in rows if row["id"] == args.provider_id]
        if not rows:
            raise ToolkitError(f"unknown provider: {args.provider_id}")
    if args.json:
        _print(json.dumps({"providers": rows}, indent=2))
        return 0
    lines = []
    for row in rows:
        lines.append(f"{row['id']}  ({row['display_name']}; {row['activation']}; {'default' if row['enabled_by_default'] else 'opt-in'})")
        lines.append(f"  capabilities: {', '.join(row['capabilities'])}")
        lines.append(f"  authoritative for: {', '.join(row['authoritative_for']) or 'none'}")
        if row["credential_names"]:
            lines.append(f"  credentials: {', '.join(row['credential_names'])} (names only; values stay in GitHub secrets)")
        lines.append("  template: " + (row["template"] if row["template_available"] and row["template"] else "none shipped; the consumer owns the workflow"))
        if row["id"] in ADAPTER_PROVIDERS:
            lines.append(f"  commands: adapter-owned ({ADAPTER_PROVIDERS[row['id']]}); consumers supply arguments only")
    lines.append("")
    lines.append("Select a provider: ai-toolkit providers select CAPABILITY=PROVIDER (runs .guardrails/configure.py).")
    _print("\n".join(lines))
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    target = resolve_target(args.target)
    if args.action == "list":
        names = skills.canonical_skills()
        _emit({"skills": names}, args.json, "\n".join(names))
        return 0
    requested = skills.resolve_skills(args.skill or ["starter"])
    clients = [item.strip() for item in args.client.split(",") if item.strip()]
    for client in clients:
        if client not in config.CLIENTS:
            raise ToolkitError(f"unknown agent client: {client}")
    existing = "replace" if args.action == "refresh" else args.existing
    results = []
    for client in clients:
        destination = skills.client_user_dir(client) if args.user else skills.client_project_dir(client, target)
        rows = skills.install_skills(requested, destination, existing=existing, dry_run=args.dry_run)
        results.append({"client": client, "destination": str(destination), "skills": rows})
    lines = []
    for row in results:
        lines.append(f"{row['client']} -> {row['destination']}" + (" (dry run)" if args.dry_run else ""))
        lines.extend(f"  {item['skill']}: {item['action']} ({len(item['files'])} files)" for item in row["skills"])
    _emit({"results": results}, args.json, "\n".join(lines))
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    target = resolve_target(args.target)
    state = discovery.detect_toolkit_state(target)
    if args.action == "status":
        workflows = [row["path"] for row in discovery.detect_workflows(target) if row["path"].endswith(("/qa.yml", "/qa-report.yml"))]
        payload = {"configurations": state["qa_configurations"], "workflows": workflows}
        lines = ["QA status"]
        lines.append("  generated qa configuration: " + (", ".join(state["qa_configurations"]) or "none"))
        lines.append("  QA workflows: " + (", ".join(workflows) or "none"))
        if not state["qa_configurations"]:
            lines.append("  Next: run `ai-toolkit qa bootstrap`, then ask your agent to use the qa-bootstrap skill.")
        else:
            lines.append("  Next: ask your agent to run the `qa` skill, or open a PR to run the QA workflow.")
        _emit(payload, args.json, "\n".join(lines))
        return 0
    clients = [item.strip() for item in args.client.split(",") if item.strip()]
    results = []
    for client in clients:
        if client not in config.CLIENTS:
            raise ToolkitError(f"unknown agent client: {client}")
        destination = skills.client_project_dir(client, target)
        results.append({"client": client, "skills": skills.install_skills(["qa-bootstrap"], destination, existing="merge", dry_run=args.dry_run)})
    lines = ["Installed the qa-bootstrap skill for: " + ", ".join(clients) + (" (dry run)" if args.dry_run else ""),
             "Next: in your agent, run the qa-bootstrap skill. It analyzes the repository, asks only what it cannot detect, and generates the qa orchestrator; the generated qa skill runs QA."]
    _emit({"results": results}, args.json, "\n".join(lines))
    return 0


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _backup(target: Path, paths: list[str]) -> Path:
    backup_root = target / ".artifacts" / "ai-toolkit" / "backup" / _timestamp()
    for relative_path in paths:
        source = target / relative_path
        if source.is_file():
            destination = backup_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    backup_root.mkdir(parents=True, exist_ok=True)
    return backup_root


def _restore(target: Path, backup_root: Path, paths: list[str]) -> list[str]:
    restored = []
    for relative_path in paths:
        source = backup_root / relative_path
        if source.is_file():
            destination = target / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            restored.append(relative_path)
    return restored


def cmd_update(args: argparse.Namespace) -> int:
    target = resolve_target(args.target)
    configuration = config.read_configuration(target)
    lock = config.read_lock(target)
    if args.rollback:
        return _rollback(target, configuration, lock, args)
    if configuration is None:
        raise ToolkitError(f"{config.TOML_NAME} is missing; run `ai-toolkit init` first")
    current = revision()
    managed = managed_files(target, configuration)
    classification = config.classify(target, lock, managed) if lock else bootstrap_classification(target, managed, configuration)
    preserved = preserved_configuration()
    up_to_date = bool(lock) and lock["toolkit"].get("revision") == current and not classification["modified"] and not classification["missing"] and not classification["new"]
    payload: dict[str, Any] = {"target": str(target), "from": lock["toolkit"].get("revision") if lock else None, "to": current,
                               "classification": classification, "applied": False}
    lines = [f"Toolkit update: {payload['from'] or 'unrecorded'} -> {current}"]
    if lock is None:
        lines.append(f"No {config.LOCK_NAME}; ownership was inferred from installer markers and canonical copies.")
    lines.append(f"  refresh (unmodified): {len(classification['unmodified'])}")
    lines.append(f"  preserve (modified):  {len(classification['modified'])}")
    for relative_path in classification["modified"]:
        lines.append(f"    {relative_path}")
    if classification["missing"]:
        lines.append(f"  restore (missing):    {len(classification['missing'])}")
    if classification["new"]:
        lines.append(f"  add (new):            {len(classification['new'])}")
    if up_to_date and not args.force:
        lines.append("Up to date; nothing to do.")
        _emit(payload, args.json, "\n".join(lines))
        return 0
    if args.dry_run:
        lines.append("Dry run; nothing was written.")
        _emit(payload, args.json, "\n".join(lines))
        return 0

    backup_root = _backup(target, managed)
    conflicts_root = target / ".artifacts" / "ai-toolkit" / "conflicts"
    conflicts: list[dict[str, str]] = []
    components = configuration["toolkit"]["components"]
    if "guardrails" in components and installed_runtime(target):
        completed = run_python(script_path("install", target, prefer_installed=False), ["--target", str(target), "--refresh-existing"], cwd=target, capture=True)
        if completed.returncode != 0:
            _restore(target, backup_root, managed)
            raise ToolkitError("installer refresh failed; previous files were restored: " + (completed.stderr or completed.stdout).strip())
    if "skills" in components or "qa" in components:
        for client in configuration["agents"]["clients"]:
            root = skills.client_project_dir(client, target)
            present = [path.name for path in root.iterdir() if path.is_dir() and path.name in set(skills.canonical_skills()) | {skills.SHARED_BUNDLE}] if root.is_dir() else []
            if present:
                skills.install_skills([name for name in present if name != skills.SHARED_BUNDLE], root, existing="replace")
    sources = canonical_sources(target, configuration)
    for relative_path in classification["modified"]:
        if relative_path in preserved or relative_path not in sources:
            continue
        conflict_copy = conflicts_root / (relative_path + ".toolkit")
        conflict_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sources[relative_path], conflict_copy)
        conflicts.append({"path": relative_path, "canonical": relative(conflict_copy, target)})
    _restore(target, backup_root, [row["path"] for row in conflicts])
    previous = {"revision": lock["toolkit"].get("revision") if lock else None, "backup": relative(backup_root, target),
                "managed": lock.get("managed", {}) if lock else {}}
    configuration["toolkit"]["revision"] = current
    config.write_configuration(target, configuration)
    managed = managed_files(target, configuration)
    config.write_lock(target, config.build_lock(current, components=components, managed=config.hash_managed(target, managed), previous=previous))
    payload.update({"applied": True, "conflicts": conflicts, "backup": relative(backup_root, target)})
    lines.append(f"Applied. Backup: {relative(backup_root, target)} (use `ai-toolkit update --rollback` to restore).")
    if conflicts:
        lines.append("Preserved your modified files; the canonical versions are beside them for comparison:")
        lines.extend(f"  {row['path']}  <->  {row['canonical']}" for row in conflicts)
    lines.append(f"Updated {config.TOML_NAME} and {config.LOCK_NAME}.")
    _emit(payload, args.json, "\n".join(lines))
    return 0


def _rollback(target: Path, configuration: dict[str, Any] | None, lock: dict[str, Any] | None, args: argparse.Namespace) -> int:
    previous = lock.get("previous") if lock else None
    if not isinstance(previous, dict) or not isinstance(previous.get("backup"), str):
        raise ToolkitError("no previous installation is recorded in the lock; nothing to roll back")
    backup_root = (target / previous["backup"]).resolve()
    if not backup_root.is_relative_to(target) or not backup_root.is_dir():
        raise ToolkitError("the recorded backup directory is missing or outside the repository")
    paths = sorted(path.relative_to(backup_root).as_posix() for path in backup_root.rglob("*") if path.is_file())
    if args.dry_run:
        _emit({"restore": paths}, args.json, "Would restore:\n" + "\n".join(f"  {path}" for path in paths))
        return 0
    restored = _restore(target, backup_root, paths)
    # Managed files absent from the backup did not exist before the update; remove them.
    for relative_path in sorted(set(lock.get("managed", {})) - set(paths)):
        path = target / relative_path
        if path.is_file():
            path.unlink()
    if configuration and isinstance(previous.get("revision"), str):
        configuration["toolkit"]["revision"] = previous["revision"]
        config.write_configuration(target, configuration)
    components = configuration["toolkit"]["components"] if configuration else list(config.COMPONENTS)
    recorded = previous.get("managed") if isinstance(previous.get("managed"), dict) else {}
    managed = recorded or config.hash_managed(target, managed_files(target, configuration))
    config.write_lock(target, config.build_lock(previous.get("revision") or revision(), components=components, managed=managed))
    _emit({"restored": restored}, args.json, f"Restored {len(restored)} files from {previous['backup']}.")
    return 0


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-toolkit", description="AI Software Toolkit: install, diagnose, check, and update Guardrails, skills, and QA.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION} ({revision()})")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--target", type=Path, default=None, help="repository root (default: current directory)")
        sub.add_argument("--json", action="store_true")

    sub = subparsers.add_parser("discover", help="detect repository structure, commands, workflows, and agent clients (read-only)")
    common(sub)
    sub.set_defaults(func=cmd_discover)

    sub = subparsers.add_parser("init", help="discover, preview, and install selected components")
    common(sub)
    sub.add_argument("--components", default=",".join(config.COMPONENTS), help="comma-separated: guardrails,skills,qa")
    sub.add_argument("--clients", default="", help="comma-separated agent clients: codex,claude-code (default: detected)")
    sub.add_argument("--skills", default="", help="comma-separated skills, 'starter' (default), or 'all'")
    sub.add_argument("--profile", choices=("core", "github"), default="core")
    sub.add_argument("--no-actions", action="store_true", help="install the runtime without GitHub Actions workflows")
    sub.add_argument("--preview", action="store_true", help="show the plan and exit without writing")
    sub.add_argument("--yes", action="store_true", help="apply without prompting")
    sub.add_argument("--apply-variables", action="store_true", help="set discovered repository variables with gh (never written to files)")
    sub.set_defaults(func=cmd_init)

    sub = subparsers.add_parser("doctor", help="report installed / configured / verified state without executing anything")
    common(sub)
    sub.add_argument("--operation", choices=("change", "release"), default="change")
    sub.add_argument("--github", metavar="OWNER/REPO")
    sub.set_defaults(func=cmd_doctor)

    sub = subparsers.add_parser("check", help="run the installed scanner and report what ran, failed, and remains unverified")
    common(sub)
    sub.add_argument("--operation", choices=("change", "release"), default="change")
    sub.add_argument("--base-ref", default="HEAD~1")
    sub.add_argument("--revision", default="")
    sub.set_defaults(func=cmd_check)

    sub = subparsers.add_parser("providers", help="list providers, show prerequisites, or select one")
    common(sub)
    sub.add_argument("action", nargs="?", choices=("list", "show", "select"), default="list")
    sub.add_argument("provider_id", nargs="?")
    sub.add_argument("--selection", metavar="CAPABILITY=PROVIDER")
    sub.set_defaults(func=cmd_providers)

    sub = subparsers.add_parser("skills", help="list, install, or refresh canonical skills for Codex and Claude Code")
    common(sub)
    sub.add_argument("action", nargs="?", choices=("list", "install", "refresh"), default="list")
    sub.add_argument("--skill", action="append", help="skill name, 'starter', or 'all' (repeatable)")
    sub.add_argument("--client", default="codex", help="comma-separated: codex,claude-code")
    sub.add_argument("--user", action="store_true", help="install into the client's user directory instead of the project")
    sub.add_argument("--existing", choices=("skip", "merge", "replace"), default="skip")
    sub.add_argument("--dry-run", action="store_true")
    sub.set_defaults(func=cmd_skills)

    sub = subparsers.add_parser("qa", help="QA status, or install the qa-bootstrap skill")
    common(sub)
    sub.add_argument("action", nargs="?", choices=("status", "bootstrap"), default="status")
    sub.add_argument("--client", default="codex")
    sub.add_argument("--dry-run", action="store_true")
    sub.set_defaults(func=cmd_qa)

    sub = subparsers.add_parser("update", help="refresh managed files, preserve modified ones, and record the lock")
    common(sub)
    sub.add_argument("--dry-run", action="store_true")
    sub.add_argument("--force", action="store_true", help="refresh even when the lock says the installation is current")
    sub.add_argument("--rollback", action="store_true", help="restore the previous managed files from the recorded backup")
    sub.set_defaults(func=cmd_update)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ToolkitError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2
