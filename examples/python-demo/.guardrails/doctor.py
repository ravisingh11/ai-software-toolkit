#!/usr/bin/env python3
"""Inspect setup without executing producers, changing settings, or creating evidence."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def trusted_module(source: str, installed: str):
    """Load this distribution's helpers, never executable code from --target."""
    here = Path(__file__).resolve()
    path = here.parent / installed if here.parent.name == ".guardrails" else here.parents[1] / source
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location(f"doctor_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (Exception, SystemExit):
        raise ValueError(f"Cannot load runtime helper {path.name}; refresh the installation.") from None
    finally:
        sys.dont_write_bytecode = previous
    return module


def read_object(target: Path, relative: str) -> dict:
    path = (target / relative).resolve()
    if not path.is_relative_to(target):
        raise ValueError("configuration must stay within the target")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("configuration must be an object")
    return value


def probe(command: list[str], target: Path) -> tuple[int, str]:
    """Only fixed, read-only probes call this; configured commands are never run."""
    try:
        completed = subprocess.run(command, cwd=target, text=True, capture_output=True, timeout=20)
        return completed.returncode, completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        # Distinct from Git's completed exit 1 meaning "no config matches".
        return -1, ""


def git_probe(arguments: list[str], target: Path) -> tuple[int, str]:
    # Even status can execute fsmonitor and clean/process filters. Do not run
    # repository commands while inspecting setup, including in submodules.
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
               "-c", f"core.hooksPath={os.devnull}"]
    if arguments[0] == "status":
        code, keys = probe([*command, "config", "--null", "--name-only", "--get-regexp",
                            r"^filter\..*\.(clean|smudge|process|required)$"], target)
        if code not in (0, 1):
            return 1, ""
        for key in keys.split("\0"):
            if key:
                # -c parses KEY=VALUE. Unusual subsection names (notably '=')
                # cannot be safely round-tripped through that encoding.
                if not re.fullmatch(r"filter\.[A-Za-z0-9_.-]+\.(clean|smudge|process|required)", key):
                    return -1, ""
                command.extend(["-c", key + ("=false" if key.endswith(".required") else "=")])
        arguments = [*arguments, "--ignore-submodules=all"]
    return probe([*command, *arguments], target)


def github_setup(target: Path, repository: str, selected: dict, providers: dict, producer) -> list[dict]:
    """Read setup metadata using the caller's gh credentials, never secret values."""
    rows = []

    def add(identifier, status, message, next_step):
        rows.append({"id": identifier, "status": status, "message": message, "next_step": next_step})

    def api(suffix="", paginated=False):
        command = ["gh", "api", "--hostname", "github.com", "--method", "GET"]
        if paginated:
            command.extend(["--paginate", "--slurp"])
        code, output = probe([*command, f"repos/{repository}{suffix}"], target)
        try:
            return json.loads(output) if code == 0 else None
        except ValueError:
            return None

    def collection(suffix, key):
        pages = api(suffix + "?per_page=100", True)
        if not isinstance(pages, list) or not pages:
            return None
        result = {}
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get(key), list):
                return None
            for item in page[key]:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    return None
                result[item["name"]] = item.get("value", "")
        return result

    variables = collection("/actions/variables", "variables")
    secrets = collection("/actions/secrets", "secrets")
    selected_providers = {entry["authoritative"] for entry in selected.values()}
    needed_variables = {command[0]: None for control, command in producer.COMMAND_PRODUCERS.items()
                        if control in selected and command[1] == selected[control]["authoritative"]}
    if "github-codeql" in selected_providers:
        needed_variables["GUARDRAILS_CODEQL_LANGUAGES"] = None
    if "github-dependency-review" in selected_providers:
        needed_variables["GUARDRAILS_DEPENDENCY_REVIEW_ENABLED"] = "true"
    if "github-artifact-attestations" in selected_providers:
        needed_variables["GUARDRAILS_ARTIFACT_PATH"] = None
    for name, expected in sorted(needed_variables.items()):
        value = variables.get(name) if variables is not None else None
        status = "unverified" if value is None else "configured" if isinstance(value, str) and value.strip() and (expected is None or value == expected) else "action_needed"
        add(f"github.variable.{name}", status,
            "Repository-level variable is set; command correctness and execution are not verified." if status == "configured"
            else "Repository-level variable is empty or not enabled." if status == "action_needed"
            else "Repository-level variable was not found or could not be read; inherited values were not queried.",
            f"Verify effective Actions variable {name}" + (f"={expected}" if expected else "") + "; run the corresponding workflow.")
    for name in sorted({name for provider_id in selected_providers for name in providers[provider_id].get("secrets", [])}):
        present = secrets is not None and name in secrets
        add(f"github.secret.{name}", "configured" if present else "unverified",
            "Repository-level secret name exists; its value, validity, permissions, and workflow availability are unverified." if present
            else "Repository-level secret name was not found or could not be read; organization/environment secrets were not queried.",
            f"Verify {name} is available to the producer workflow; never put its value in policy, logs, or this report.")
    if "github-secret-protection" in selected_providers:
        repository_data = api()
        settings = repository_data.get("security_and_analysis") if isinstance(repository_data, dict) else None
        values = [settings.get(key, {}).get("status") if isinstance(settings, dict) and isinstance(settings.get(key), dict) else None
                  for key in ("secret_scanning", "secret_scanning_push_protection")]
        status = "action_needed" if "disabled" in values else "configured" if values == ["enabled", "enabled"] else "unverified"
        add("github.secret-protection", status,
            "Secret scanning and push protection are enabled; alerts and workflow token permissions were not checked." if status == "configured"
            else "GitHub explicitly reports a disabled secret protection setting." if status == "action_needed"
            else "GitHub did not expose both settings; lack of visibility is not evidence they are disabled.",
            "Inspect repository Settings > Code security; the Secret Scan workflow must verify settings and alerts with SECURITY_SETTINGS_TOKEN.")
    add("github.producer-evidence", "unverified", "Only setup metadata was queried; no check runs, findings, or secret values were collected.",
        "Open a representative PR and inspect its Guardrail Scorecard; metadata alone cannot satisfy a control.")
    return rows


def diagnose(target: Path, *, operation: str = "change", environment: dict | None = None, github: str | None = None) -> dict:
    target = target.resolve()
    if not target.is_dir():
        raise ValueError("--target must name an existing repository directory")
    if github is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", github):
        raise ValueError("--github must be OWNER/REPO on github.com")
    environment = dict(os.environ) if environment is None else environment
    checks = []

    def add(identifier, status, message, next_step):
        checks.append({"id": identifier, "status": status, "message": message, "next_step": next_step})

    validator = trusted_module("guardrails/validate_repository.py", "validators/validate_repository.py")
    missing = [name for name in validator.REQUIRED_FILES if not (target / ".guardrails" / name).is_file()]
    add("runtime", "action_needed" if missing else "configured",
        "Missing runtime files: " + ", ".join(missing) if missing else "Installed runtime files are present; contents have not been executed.",
        "Run tooling/install.py --target <repo> --refresh-existing from a trusted release." if missing
        else "Use the repository validation check to validate installed contracts.")

    evaluator = trusted_module("guardrails/evaluate.py", "evaluate.py")
    producer = trusted_module("tooling/produce_guardrail_evidence.py", "produce.py")
    selected, providers = {}, {}
    try:
        documents = [read_object(target, f".guardrails/{name}.yaml")
                     for name in ("policy", "profiles", "control-catalog", "providers")]
        for subject in ("git-commit", "pull-request", "artifact", "environment"):
            active, _, providers = evaluator.effective_controls(*documents, operation, subject)
            selected.update(active)
        for provider in providers.values():
            secrets = provider.get("secrets", [])
            if not isinstance(secrets, list) or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in secrets):
                raise ValueError("invalid provider secret metadata")
        add("configuration", "configured", f"Valid contracts; {len(selected)} selected capabilities for {operation}.",
            "Run a scan or PR to obtain exact-subject evidence; selection is not a pass.")
    except (OSError, ValueError, KeyError, TypeError):
        selected, providers = {}, {}
        add("configuration", "action_needed", "Installed policy, profiles, catalog, or providers are unreadable or invalid.",
            "Validate .guardrails/*.yaml with the repository validator; review the policy and provider selections.")

    code, root = git_probe(["rev-parse", "--show-toplevel"], target)
    repository = code == 0 and Path(root).resolve() == target
    add("git.repository", "configured" if repository else "action_needed",
        "Target is a Git repository root." if repository else "Target must be the root of a Git repository.",
        "Run from the repository root, or pass --target /path/to/repo.")
    if repository:
        code, _ = git_probe(["rev-parse", "--verify", "HEAD^{commit}"], target)
        add("git.head", "configured" if code == 0 else "action_needed",
            "HEAD resolves to a commit." if code == 0 else "No committed HEAD is available.",
            "Review and commit the intended files before scanning.")
        code, status = git_probe(["status", "--porcelain", "--untracked-files=normal"], target)
        clean = code == 0 and not status
        submodules = (target / ".gitmodules").exists()
        add("git.clean", "action_needed" if not clean else "unverified" if submodules else "configured",
            "No changes detected with hooks and filters disabled; submodule contents were not inspected." if clean
            else "Worktree differs with Git hooks/filters disabled, or cannot be inspected.",
            "Review git status in a trusted checkout (including filters and submodules); commit intended changes without discarding work.")
        code, _ = git_probe(["rev-parse", "--verify", "HEAD~1^{commit}"], target)
        add("git.base", "configured" if code == 0 else "action_needed",
            "Default comparison base HEAD~1 exists." if code == 0 else "Default comparison base HEAD~1 is unavailable.",
            "Fetch full history or supply scan.py --base-ref <existing-base-commit>.")

    if "repository-ground-truth" in selected:
        try:
            truth = read_object(target, ".guardrails/ground-truth-ai.yaml")
            entries = truth.get("documents")
            valid = truth.get("version") == 1 and isinstance(entries, list) and bool(entries)
            if valid:
                for item in entries:
                    if not isinstance(item, dict) or set(item) != {"path"} or not isinstance(item["path"], str) or not item["path"].strip():
                        valid = False
                        break
                    path = (target / item["path"]).resolve()
                    if Path(item["path"]).is_absolute() or not path.is_relative_to(target) or not path.is_file() or not path.read_text(encoding="utf-8").strip():
                        valid = False
                        break
        except (OSError, ValueError):
            valid = False
        add("ground-truth", "configured" if valid else "action_needed",
            "Declared documents exist and are nonempty; accuracy still needs review." if valid else "Ground-truth declaration is invalid, empty, or references missing/empty documents.",
            "Set .guardrails/ground-truth-ai.yaml documents to real repository-relative documentation paths.")

    working_directory = environment.get("GUARDRAILS_WORKING_DIRECTORY", ".").strip() or "."
    working = (target / working_directory).resolve()
    valid_working = working.is_relative_to(target) and working.is_dir()
    add("local.working-directory", "configured" if valid_working else "action_needed",
        "Working directory is inside the repository." if valid_working else "Working directory is missing or escapes the repository.",
        "Set GUARDRAILS_WORKING_DIRECTORY to an existing repository-relative directory.")

    for control_id, selection in sorted(selected.items()):
        provider_id = selection["authoritative"]
        command = producer.COMMAND_PRODUCERS.get(control_id)
        if command and command[1] == provider_id:
            variable = command[0]
            configured = bool(environment.get(variable, "").strip())
            add(f"local.command.{control_id}", "configured" if configured else "action_needed",
                f"{variable} is set locally; not executed." if configured else f"{variable} is unset locally.",
                f"Export {variable} with a real repository command, then run scan.py; configure the Actions variable separately.")
        elif provider_id in {"semgrep-ce", "gitleaks"}:
            binary = "semgrep" if provider_id == "semgrep-ce" else "gitleaks"
            version = producer.SEMGREP_VERSION if binary == "semgrep" else producer.GITLEAKS_VERSION
            available = bool(shutil.which("docker") or shutil.which(binary))
            add(f"local.tool.{provider_id}", "unverified" if available else "action_needed",
                "Executable located; daemon, image, version, and scan not verified." if available else f"Neither Docker nor {binary} is on PATH.",
                f"Provide working Docker or {binary} {version}, then run scan.py; it verifies the pinned runtime.")
        else:
            add(f"producer.{control_id}", "unverified", f"Selected provider {provider_id}; no producer was run.",
                "Run the applicable local scan, PR, or release producer and inspect its exact-subject evidence.")
        contract = providers[provider_id].get("checks", {}).get(control_id, {})
        path = contract.get("workflow_path")
        if path:
            workflow = (target / path).resolve()
            present = workflow.is_relative_to(target) and workflow.is_file()
            add(f"workflow.{control_id}", "configured" if present else "unverified",
                "Workflow file present; GitHub execution is not verified." if present else "Workflow file absent; local-only installations may intentionally omit Actions.",
                "For PR automation, install/configure the selected provider workflow and verify a representative PR.")

    if github and selected:
        checks.extend(github_setup(target, github, selected, providers, producer))
    return {"version": 1, "kind": "setup-diagnostics", "operation": operation, "github_repository": github,
            "checks": checks, "summary": {status: sum(row["status"] == status for row in checks)
                                           for status in ("configured", "action_needed", "unverified")}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    parser.add_argument("--operation", choices=("change", "release"), default="change")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--github", metavar="OWNER/REPO", help="Optionally read github.com setup metadata using existing gh authentication")
    args = parser.parse_args()
    try:
        report = diagnose(args.target, operation=args.operation, github=args.github)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Setup diagnostic unavailable: {error}\n")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Guardrails Setup Diagnostic\nConfiguration is not passing evidence. No producers were run.\n")
        for row in report["checks"]:
            print(f"[{row['status'].upper()}] {row['id']}: {row['message']}\n  Next: {row['next_step']}")
        print("\n" + " | ".join(f"{key}: {value}" for key, value in report["summary"].items()))
    return 1 if report["summary"]["action_needed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
