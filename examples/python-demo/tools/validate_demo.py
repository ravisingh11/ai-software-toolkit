#!/usr/bin/env python3
"""Validate the sample repository's local contracts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MACHINE_PATH = re.compile(
    rf"(/{'Users'}/|/{'private'}/|\\\\{'Users'}\\\\)"
)
CONFIG_PATHS = {
    "policy": ".proof/policy.yaml",
    "profiles": ".proof/profiles.yaml",
    "catalog": ".proof/control-catalog.yaml",
    "providers": ".proof/providers.yaml",
    "ground_truth": ".proof/ground-truth-ai.yaml",
    "documentation": ".proof/documentation.yaml",
    "change_scope": ".proof/change-scope.yaml",
}
RETIRED_CONFIG_PATHS = tuple(
    ".ai" + suffix
    for suffix in (
        "/proof.yaml",
        "/control-catalog.yaml",
        "/ground-truth.yaml",
        "/documentation.yaml",
        "/change-scope.yaml",
    )
)
RUNTIME_CONTRACTS = {
    ".proof/configure.py": (
        CONFIG_PATHS["policy"],
        CONFIG_PATHS["profiles"],
        CONFIG_PATHS["catalog"],
        CONFIG_PATHS["providers"],
    ),
    ".proof/evaluate.py": (),
    ".proof/github_evidence.py": (),
    ".proof/produce.py": (),
    ".proof/scan.py": (
        CONFIG_PATHS["policy"],
        CONFIG_PATHS["profiles"],
        CONFIG_PATHS["catalog"],
        CONFIG_PATHS["providers"],
    ),
    ".proof/scorecard.py": (),
    ".proof/validate_ground_truth.py": (CONFIG_PATHS["ground_truth"],),
    ".proof/validators/inspect_change_scope.py": (),
    ".proof/validators/validate_documentation.py": (),
    ".proof/validators/validate_repository.py": (),
}
WORKFLOW_CONTRACTS = (
    "proof-scorecard.yml",
    "repository-validation.yml",
    "build.yml",
    "unit-tests.yml",
    "changed-code-coverage.yml",
    "semgrep-ce.yml",
    "gitleaks.yml",
    "codeql.yml",
    "dependency-review.yml",
    "github-secret-protection.yml",
    "dependabot-verification.yml",
    "artifact-provenance.yml",
)
FORBIDDEN_ACTIVE_GUIDANCE = (
    ".agentic-guardrails/",
    ".proof/producer-manifest.json",
    "--github-actions",
    "--no-cleanup",
    "semgrep ci",
    "--config auto",
)
BINARY_SUFFIXES = {
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".tar",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}


def fail_if(condition: bool, message: str, failures: list[str]) -> None:
    if condition:
        failures.append(message)


def load_configs(failures: list[str]) -> dict[str, dict[str, object]]:
    configs: dict[str, dict[str, object]] = {}
    for name, relative in CONFIG_PATHS.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing required file: {relative}")
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"{relative} is not valid JSON-compatible YAML: {error}")
            continue
        if not isinstance(value, dict):
            failures.append(f"{relative} must contain an object")
            continue
        configs[name] = value
    return configs


def validate_path_contracts(
    contracts: dict[str, tuple[str, ...]], failures: list[str]
) -> None:
    for relative, canonical_paths in contracts.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing required file: {relative}")
            continue
        content = path.read_text(encoding="utf-8")
        for canonical_path in canonical_paths:
            fail_if(
                canonical_path not in content,
                f"{relative} does not invoke canonical path: {canonical_path}",
                failures,
            )
        for retired_path in RETIRED_CONFIG_PATHS:
            fail_if(
                retired_path in content,
                f"{relative} contains retired path: {retired_path}",
                failures,
            )


def tracked_text_files(failures: list[str]) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        failures.append("cannot enumerate tracked files")
        return []

    paths: list[Path] = []
    for encoded in completed.stdout.split(b"\0"):
        if not encoded:
            continue
        try:
            relative = Path(encoded.decode("utf-8"))
        except UnicodeDecodeError:
            failures.append("tracked path is not valid UTF-8")
            continue
        path = ROOT / relative
        if relative == Path("tools/validate_demo.py") or not path.is_file():
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        paths.append(relative)
    return paths


def run_installed_validator(relative: str, arguments: list[str], failures: list[str]) -> None:
    path = ROOT / relative
    if not path.is_file():
        return
    completed = subprocess.run(
        [sys.executable, str(path), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if not output:
        failures.append(f"{relative} failed without output")
        return
    for line in output.splitlines():
        failures.append(line.removeprefix("ERROR: "))


def validate_ground_truth_paths(
    ground_truth: dict[str, object], failures: list[str]
) -> None:
    documents = ground_truth.get("documents", [])
    if not isinstance(documents, list):
        failures.append("ground-truth policy documents must be a list")
        return
    repository_root = ROOT.resolve()
    for item in documents:
        relative = item.get("path") if isinstance(item, dict) else None
        if not isinstance(relative, str):
            failures.append(f"ground-truth path does not exist: {relative}")
            continue
        declared = Path(relative)
        candidate = (ROOT / declared).resolve()
        try:
            candidate.relative_to(repository_root)
        except ValueError:
            failures.append(
                f"ground-truth path must be repository-relative and contained: {relative}"
            )
            continue
        if declared.is_absolute():
            failures.append(
                f"ground-truth path must be repository-relative and contained: {relative}"
            )
        elif not candidate.is_file():
            failures.append(f"ground-truth path does not exist: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documentation", action="store_true")
    args = parser.parse_args()
    failures: list[str] = []

    required = ("README.md", "AGENTS.md", "app.py", "test_app.py")
    for relative in required:
        fail_if(not (ROOT / relative).is_file(), f"missing required file: {relative}", failures)

    fail_if((ROOT / ".ai").exists(), "retired configuration directory exists: .ai", failures)
    configs = load_configs(failures)
    policy = configs.get("policy", {})
    profiles = configs.get("profiles", {})
    catalog = configs.get("catalog", {})
    providers = configs.get("providers", {})
    ground_truth = configs.get("ground_truth", {})

    fail_if(policy.get("version") != 2, "policy must use contract version 2", failures)
    policy_profiles = policy.get("profiles")
    fail_if(
        policy_profiles != ["core", "github"],
        "demo policy must select the Core profile and additive GitHub profile",
        failures,
    )
    if not isinstance(policy_profiles, list) or not all(
        isinstance(profile_id, str) for profile_id in policy_profiles
    ):
        failures.append("policy profiles must be a list of strings")
        policy_profiles = []

    profile_definitions = profiles.get("profiles")
    if not isinstance(profile_definitions, dict):
        failures.append("runtime profiles must contain a profiles object")
        profile_definitions = {}
    fail_if(
        set(profile_definitions) != {"core", "github"},
        "runtime profiles must define exactly core and github",
        failures,
    )
    fail_if(catalog.get("version") != 2, "control catalog must use version 2", failures)
    fail_if(providers.get("version") != 2, "provider config must use version 2", failures)

    controls = catalog.get("controls")
    if not isinstance(controls, list):
        failures.append("control catalog controls must be a list")
        controls = []
    control_ids = {
        control.get("id")
        for control in controls
        if isinstance(control, dict) and isinstance(control.get("id"), str)
    }
    fail_if(
        any(
            not isinstance(control, dict) or not isinstance(control.get("id"), str)
            for control in controls
        ),
        "control catalog controls must be objects with string ids",
        failures,
    )

    selected: set[str] = set()
    for profile_id in policy_profiles:
        profile = profile_definitions.get(profile_id)
        if not isinstance(profile, dict):
            failures.append(f"runtime profile {profile_id} must be an object")
            continue
        defaults = profile.get("defaults")
        if not isinstance(defaults, dict):
            failures.append(f"runtime profile {profile_id} defaults must be an object")
            continue
        for operation_name, operation in defaults.items():
            if not isinstance(operation, dict) or not all(
                isinstance(control_id, str) and isinstance(mode, str)
                for control_id, mode in operation.items()
            ):
                failures.append(
                    f"runtime profile {profile_id} {operation_name} defaults must be an object of string modes"
                )
                continue
            selected.update(operation)

    overrides = policy.get("overrides")
    if not isinstance(overrides, dict):
        failures.append("policy overrides must be an object")
        overrides = {}
    for operation_name, operation in overrides.items():
        if not isinstance(operation, dict) or not all(
            isinstance(control_id, str) and isinstance(mode, str)
            for control_id, mode in operation.items()
        ):
            failures.append(f"policy override {operation_name} must be an object of string modes")
            continue
        selected.update(operation)

    selections = providers.get("selections")
    if not isinstance(selections, dict):
        failures.append("provider selections must be an object")
        selections = {}
    for capability, selection in selections.items():
        if not isinstance(capability, str) or not isinstance(selection, dict):
            failures.append("provider selections must map capability ids to objects")
            continue
        authoritative = selection.get("authoritative")
        supplemental = selection.get("supplemental", [])
        if not isinstance(authoritative, str) or not authoritative:
            failures.append(f"provider selection {capability} authoritative must be a string")
        if not isinstance(supplemental, list) or not all(
            isinstance(provider_id, str) for provider_id in supplemental
        ):
            failures.append(f"provider selection {capability} supplemental must be a list of strings")

    fail_if(not selected <= control_ids, "policy selects controls absent from catalog", failures)
    fail_if(
        not selected <= set(selections),
        "selected capabilities lack provider selections",
        failures,
    )

    validate_ground_truth_paths(ground_truth, failures)

    validate_path_contracts(RUNTIME_CONTRACTS, failures)
    for installed in WORKFLOW_CONTRACTS:
        installed_path = ROOT / ".github/workflows" / installed
        fail_if(
            not installed_path.is_file(),
            f"missing required file: {installed_path.relative_to(ROOT)}",
            failures,
        )

    fail_if(
        (ROOT / ".proof/producer-manifest.json").exists(),
        "obsolete producer manifest is present",
        failures,
    )
    for relative in (
        ".proof/profiles.schema.json",
        ".proof/providers.schema.json",
        ".proof/evidence.schema.json",
        ".proof/policy.schema.json",
        ".proof/control-catalog.schema.json",
        ".proof/semgrep-rules.yml",
    ):
        fail_if(not (ROOT / relative).is_file(), f"missing required file: {relative}", failures)

    for relative_path in tracked_text_files(failures):
        relative = relative_path.as_posix()
        try:
            content = (ROOT / relative_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            failures.append(f"tracked text file cannot be read as UTF-8: {relative}: {error}")
            continue
        fail_if(bool(MACHINE_PATH.search(content)), f"machine-local path found in {relative}", failures)
        for retired in FORBIDDEN_ACTIVE_GUIDANCE:
            fail_if(
                retired in content.lower(),
                f"retired Proof guidance found in {relative}: {retired}",
                failures,
            )

    diff_check = subprocess.run(["git", "diff", "--check"], cwd=ROOT)
    fail_if(diff_check.returncode != 0, "git diff --check failed", failures)

    if args.documentation:
        run_installed_validator(
            ".proof/validators/validate_documentation.py",
            ["--policy", CONFIG_PATHS["documentation"]],
            failures,
        )
        run_installed_validator(
            ".proof/validate_ground_truth.py",
            ["--policy", CONFIG_PATHS["ground_truth"]],
            failures,
        )
        readme_path = ROOT / "README.md"
        if readme_path.is_file():
            readme = readme_path.read_text(encoding="utf-8")
            fail_if("## Run the example" not in readme, "README is missing the run instructions", failures)
            fail_if("repository-specific ground truth" not in readme, "README does not explain repository ground truth", failures)
        agents_path = ROOT / "AGENTS.md"
        if agents_path.is_file():
            agents = agents_path.read_text(encoding="utf-8")
            fail_if(not agents.strip(), "AGENTS.md is empty", failures)

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print("Demo repository validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
