#!/usr/bin/env python3
"""Install the Guardrails v2 runtime and selected advisory profiles."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "guardrails" / "baseline.yaml"
PRODUCER = ROOT / "tooling" / "produce_guardrail_evidence.py"
SEMGREP_IMAGE = "semgrep/semgrep@sha256:b94b53d02fd4a022f9eac4e2af1380f5c3c4c21400e79d3336bdff1d1db5e796"
GITLEAKS_IMAGE = "ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
VERSION = "2.0.0"
INSTALLER_MARKER = "# Guardrails v2 installer-owned workflow."
RUNTIME_MARKER = "# Guardrails v2 installer-owned runtime."

CORE_WORKFLOWS = {
    "guardrails-scorecard.yml": ROOT / "workflows" / "guardrails-scorecard.yml",
    "change-scope.yml": ROOT / "workflows" / "change-scope.yml",
    "pr-metadata.yml": ROOT / "workflows" / "pr-metadata.yml",
    "repository-validation.yml": ROOT / "workflows" / "repository-validation.yml",
    "build.yml": ROOT / "workflows" / "build.yml",
    "unit-tests.yml": ROOT / "workflows" / "unit-tests.yml",
    "changed-code-coverage.yml": ROOT / "workflows" / "changed-code-coverage.yml",
    "format-and-lint.yml": ROOT / "workflows" / "format-and-lint.yml",
    "migration-validation.yml": ROOT / "workflows" / "migration-validation.yml",
    "semgrep-ce.yml": ROOT / "workflows" / "semgrep-ce.yml",
    "gitleaks.yml": ROOT / "workflows" / "gitleaks.yml",
}
GITHUB_WORKFLOWS = {
    "codeql.yml": ROOT / "workflows" / "codeql.yml",
    "dependency-review.yml": ROOT / "workflows" / "dependency-review.yml",
    "github-secret-protection.yml": ROOT / "workflows" / "github-secret-protection.yml",
    "dependabot-verification.yml": ROOT / "workflows" / "dependabot-verification.yml",
    "artifact-provenance.yml": ROOT / "workflows" / "artifact-provenance.yml",
}
BADGE_WORKFLOWS = {
    "guardrails-scorecard-badge.yml": ROOT / "workflows" / "guardrails-scorecard-badge.yml",
}
PRESERVED_CONFIGURATION = {
    Path(".guardrails/policy.yaml"),
    Path(".guardrails/documentation.yaml"),
    Path(".guardrails/change-scope.yaml"),
    Path(".guardrails/pr-metadata.yaml"),
    Path(".guardrails/ground-truth-ai.yaml"),
}
V1_PATHS = (
    Path(".guardrails/producer-manifest.json"),
    Path(".agentic-guardrails"),
    Path(".ai/guardrails.yaml"),
    Path(".ai/control-catalog.yaml"),
    Path(".ai/documentation.yaml"),
    Path(".ai/change-scope.yaml"),
    Path(".ai/ground-truth.yaml"),
    Path(".ai/producer-manifest.json"),
)


class InstallItem(NamedTuple):
    source: Path
    destination: Path
    kind: str = "file"


def reject_symlink_destinations(target: Path, destinations: list[Path]) -> None:
    for destination in destinations:
        relative = destination.relative_to(target)
        component = target
        for part in relative.parts:
            component /= part
            if component.is_symlink():
                raise ValueError(
                    f"refusing installer destination with symlink component: {component}"
                )


def runtime_sources(target: Path) -> list[InstallItem]:
    files = {
        "policy.yaml": POLICY,
        "profiles.yaml": ROOT / "policies/profiles.yaml",
        "control-catalog.yaml": ROOT / "policies/control-catalog.yaml",
        "providers.yaml": ROOT / "policies/provider-config.yaml",
        "policy.schema.json": ROOT / "guardrails/policy.schema.json",
        "evidence.schema.json": ROOT / "guardrails/evidence.schema.json",
        "profiles.schema.json": ROOT / "guardrails/profiles.schema.json",
        "providers.schema.json": ROOT / "guardrails/providers.schema.json",
        "control-catalog.schema.json": ROOT / "guardrails/control-catalog.schema.json",
        "documentation.yaml": ROOT / "guardrails/defaults/documentation.yaml",
        "change-scope.yaml": ROOT / "guardrails/defaults/change-scope.yaml",
        "pr-metadata.yaml": ROOT / "guardrails/defaults/pr-metadata.yaml",
        "ground-truth-ai.yaml": ROOT / "guardrails/defaults/ground-truth-ai.yaml",
        "evaluate.py": ROOT / "guardrails/evaluate.py",
        "scorecard.py": ROOT / "tooling/guardrail_scorecard.py",
        "configure.py": ROOT / "tooling/configure_guardrails.py",
        "scan.py": ROOT / "tooling/scan_repository.py",
        "doctor.py": ROOT / "tooling/doctor.py",
        "github_evidence.py": ROOT / "tooling/github_evidence.py",
        "produce.py": PRODUCER,
        "adapter.py": ROOT / "tooling/provider_adapter.py",
        "validate_ground_truth.py": ROOT / "tooling/validators/validate_ground_truth.py",
        "semgrep-rules.yml": ROOT / "security/semgrep/guardrails.yml",
    }
    validators = {
        "validate_repository.py": ROOT / "guardrails/validate_repository.py",
        "validate_documentation.py": ROOT / "tooling/validators/validate_documentation.py",
        "inspect_change_scope.py": ROOT / "tooling/validators/inspect_change_scope.py",
        "validate_pr_metadata.py": ROOT / "tooling/validators/validate_pr_metadata.py",
    }
    items = [InstallItem(source, target / ".guardrails" / name) for name, source in files.items()]
    items.extend(InstallItem(source, target / ".guardrails/validators" / name) for name, source in validators.items())
    for source_root, destination_root in (
        (ROOT / "security/semgrep/tests/fixtures", target / ".guardrails/semgrep-tests/fixtures"),
        (ROOT / "skills/prepare-safe-change", target / ".agents/skills/prepare-safe-change"),
    ):
        items.extend(
            InstallItem(source, destination_root / source.relative_to(source_root))
            for source in sorted(source_root.rglob("*"))
            if source.is_file()
        )
    return items


def badge_sources(target: Path) -> list[InstallItem]:
    items = [
        InstallItem(
            ROOT / "tooling" / "render_scorecard_badge.py",
            target / ".guardrails/render_scorecard_badge.py",
        ),
        InstallItem(
            ROOT / "tooling" / "reconcile_scorecard_badge.py",
            target / ".guardrails/reconcile_scorecard_badge.py",
        ),
    ]
    items.extend(
        InstallItem(source, target / ".github/workflows" / name)
        for name, source in BADGE_WORKFLOWS.items()
    )
    return items


def load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot identify existing Guardrails configuration at {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"existing Guardrails configuration must be an object: {path}")
    return value


def validate_provider_document(document: dict) -> None:
    validator_path = ROOT / "tooling" / "validators" / "validate_repository.py"
    spec = importlib.util.spec_from_file_location(
        "guardrails_v2_repository_validator", validator_path
    )
    if not spec or not spec.loader:
        raise ValueError(f"cannot load provider validator: {validator_path}")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    catalog = validator.validate_control_catalog_document(
        load_object(ROOT / "policies" / "control-catalog.yaml")
    )
    validator.validate_provider_document(document, catalog)


def reject_v1(target: Path) -> None:
    conflicts = [path for relative in V1_PATHS if ((path := target / relative).exists() or path.is_symlink())]
    for relative in (Path(".guardrails/policy.yaml"), Path(".guardrails/control-catalog.yaml"), Path(".guardrails/providers.yaml")):
        path = target / relative
        if path.is_file() and load_object(path).get("version") != 2:
            conflicts.append(path)
    if conflicts:
        rendered = ", ".join(str(path.relative_to(target)) for path in conflicts)
        raise ValueError(
            f"Guardrails v1 was detected at {rendered}. Back up and remove the v1 runtime/configuration, then perform a clean reinstall; automatic migration is not supported."
        )


def policy_bytes(existing: Path | None, profiles: list[str]) -> bytes:
    policy = load_object(existing) if existing and existing.is_file() else load_object(POLICY)
    selected = list(policy.get("profiles", ["core"]))
    if "core" not in selected:
        selected.insert(0, "core")
    for profile in profiles:
        if profile not in {"core", "github"}:
            raise ValueError(f"unknown runnable profile: {profile}")
        if profile not in selected:
            selected.append(profile)
    policy["profiles"] = selected
    return (json.dumps(policy, indent=2) + "\n").encode()


def refreshed_provider_bytes(existing: Path) -> bytes:
    canonical_path = ROOT / "policies/provider-config.yaml"
    pristine = load_object(canonical_path)
    canonical = load_object(canonical_path)
    installed = load_object(existing)
    canonical_providers = canonical.get("providers")
    installed_providers = installed.get("providers")
    canonical_selections = canonical.get("selections")
    installed_selections = installed.get("selections")
    if (
        not isinstance(canonical_providers, dict)
        or not isinstance(installed_providers, dict)
        or not isinstance(canonical_selections, dict)
        or not isinstance(installed_selections, dict)
    ):
        raise ValueError(
            "existing Guardrails provider configuration must contain providers and selections objects"
        )
    custom_providers = {
        provider_id: provider
        for provider_id, provider in installed_providers.items()
        if provider_id not in canonical_providers
    }
    for provider_id, canonical_provider in canonical_providers.items():
        installed_provider = installed_providers.get(provider_id)
        if not isinstance(installed_provider, dict):
            continue
        canonical_checks = canonical_provider.get("checks")
        installed_checks = installed_provider.get("checks")
        if not isinstance(canonical_checks, dict) or not isinstance(installed_checks, dict):
            continue
        for capability, canonical_check in canonical_checks.items():
            installed_check = installed_checks.get(capability)
            if not isinstance(canonical_check, dict) or not isinstance(installed_check, dict):
                continue
            installed_trusted = installed_check.get("trusted_paths", [])
            canonical_trusted = canonical_check.get("trusted_paths", [])
            if not isinstance(installed_trusted, list) or not isinstance(canonical_trusted, list):
                continue
            combined = list(dict.fromkeys([*canonical_trusted, *installed_trusted]))
            if combined:
                canonical_check["trusted_paths"] = combined
    merged = dict(canonical_providers)
    merged.update(custom_providers)
    canonical["providers"] = merged
    merged_selections = dict(canonical_selections)
    merged_selections.update(installed_selections)
    canonical["selections"] = merged_selections
    validate_provider_document(canonical)
    if (
        not custom_providers
        and merged_selections == canonical_selections
        and merged == pristine.get("providers")
    ):
        return canonical_path.read_bytes()
    return (json.dumps(canonical, indent=2) + "\n").encode()


def build_plan(target: Path, *, profiles: list[str], no_actions: bool, scorecard_badge: bool = False) -> list[InstallItem]:
    plan = runtime_sources(target)
    if no_actions:
        return plan
    workflows = dict(CORE_WORKFLOWS)
    if "github" in profiles:
        workflows.update(GITHUB_WORKFLOWS)
    plan.extend(
        InstallItem(source, target / ".github/workflows" / name)
        for name, source in workflows.items()
    )
    if scorecard_badge:
        plan.extend(badge_sources(target))
    return plan


def precommit_config() -> str:
    return f"""repos:
  - repo: local
    hooks:
      - id: guardrails-semgrep-ce
        name: Guardrails Semgrep CE
        language: docker_image
        entry: {SEMGREP_IMAGE} semgrep scan --error --config .guardrails/semgrep-rules.yml --exclude .guardrails/semgrep-tests/fixtures --exclude security/semgrep/tests/fixtures .
        pass_filenames: false
      - id: guardrails-gitleaks
        name: Guardrails Gitleaks
        language: docker_image
        entry: {GITLEAKS_IMAGE} git --redact --no-banner .
        pass_filenames: false
"""


def prepare_local_hooks(target: Path, *, dry_run: bool) -> tuple[str | None, Path | None]:
    destination = target / ".pre-commit-config.yaml"
    if destination.exists() or destination.is_symlink():
        raise ValueError(".pre-commit-config.yaml already exists; preserve it and perform a manual merge of the Guardrails hooks.")
    if dry_run:
        return precommit_config(), None
    executable = shutil.which("pre-commit")
    if executable is None:
        raise ValueError("the pre-commit executable is required before --local-hooks can write hook state")
    repository = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=target, text=True, capture_output=True)
    if repository.returncode != 0 or not repository.stdout.strip():
        raise ValueError("--local-hooks requires the target to be a Git repository")
    if Path(repository.stdout.strip()).resolve() != target:
        raise ValueError("--local-hooks requires the target to be the exact Git repository root")
    temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    try:
        temporary.write(precommit_config())
        temporary.close()
        validation = subprocess.run([executable, "validate-config", temporary.name], cwd=target, text=True, capture_output=True)
        if validation.returncode != 0:
            raise ValueError(f"generated pre-commit configuration is invalid: {(validation.stdout + validation.stderr).strip()}")
        return precommit_config(), Path(temporary.name)
    except Exception:
        Path(temporary.name).unlink(missing_ok=True)
        raise


def installer_owned_workflow(path: Path) -> bool:
    try:
        return path.read_text(encoding="utf-8").startswith(INSTALLER_MARKER)
    except OSError:
        return False


def installer_owned_runtime(path: Path, source: Path) -> bool:
    try:
        content = path.read_bytes()
        if content == source.read_bytes():
            return True
        return RUNTIME_MARKER.encode() in content.splitlines()[:3]
    except OSError:
        return False


def installer_owned_badge(item: InstallItem) -> bool:
    if item.destination.parent.name == "workflows":
        return installer_owned_workflow(item.destination)
    return installer_owned_runtime(item.destination, item.source)


def install(
    target: Path,
    *,
    dry_run: bool,
    profiles: list[str] | None = None,
    no_actions: bool = False,
    local_hooks: bool = False,
    merge_existing: bool = False,
    refresh_existing: bool = False,
    scorecard_badge: bool = False,
    remove_scorecard_badge: bool = False,
) -> list[InstallItem]:
    target = target.resolve()
    if scorecard_badge and remove_scorecard_badge:
        raise ValueError("--scorecard-badge and --remove-scorecard-badge cannot be combined")
    if scorecard_badge and no_actions:
        raise ValueError("--scorecard-badge requires GitHub Actions")
    if remove_scorecard_badge and not refresh_existing:
        raise ValueError("--remove-scorecard-badge requires --refresh-existing")
    explicit_profiles = list(profiles or [])
    selected_profiles: list[str] = []
    policy_destination = target / ".guardrails/policy.yaml"
    providers_destination = target / ".guardrails/providers.yaml"
    if refresh_existing and not remove_scorecard_badge and policy_destination.is_file():
        installed_profiles = load_object(policy_destination).get("profiles")
        if not isinstance(installed_profiles, list) or not all(
            isinstance(profile, str) and profile in {"core", "github"}
            for profile in installed_profiles
        ):
            raise ValueError("existing Guardrails policy contains invalid runnable profiles")
        selected_profiles = list(installed_profiles)
    for profile in explicit_profiles:
        if profile not in {"core", "github"}:
            raise ValueError(f"unknown runnable profile: {profile}")
        if profile not in selected_profiles:
            selected_profiles.append(profile)
    badge_items = badge_sources(target)
    installed_badge = any(item.destination.exists() and installer_owned_badge(item) for item in badge_items)
    include_badge = scorecard_badge or (refresh_existing and installed_badge and not remove_scorecard_badge)
    if scorecard_badge and policy_destination.exists() and not refresh_existing:
        raise ValueError("adding the scorecard badge to an existing installation requires --refresh-existing")
    complete_plan = [] if remove_scorecard_badge else build_plan(
        target, profiles=selected_profiles, no_actions=no_actions, scorecard_badge=include_badge
    )
    if include_badge:
        for item in badge_items:
            if item.destination.exists() and not installer_owned_badge(item):
                raise ValueError(f"scorecard badge destination is not installer-owned: {item.destination}")
    if remove_scorecard_badge:
        for item in badge_items:
            if not item.destination.exists() and not item.destination.is_symlink():
                continue
            if not installer_owned_badge(item):
                raise ValueError(f"scorecard badge destination is not installer-owned: {item.destination}")
            complete_plan.append(InstallItem(item.source, item.destination, "remove"))
    destinations = [item.destination for item in complete_plan]
    if local_hooks:
        destinations.append(target / ".pre-commit-config.yaml")
    reject_symlink_destinations(target, destinations)
    if not target.is_dir():
        raise ValueError(f"target is not a directory: {target}")
    if merge_existing and refresh_existing:
        raise ValueError("--merge-existing and --refresh-existing cannot be combined")
    reject_v1(target)
    hook_text, temporary_hook = prepare_local_hooks(target, dry_run=dry_run) if local_hooks else (None, None)
    plan = [item for item in complete_plan if item.source.resolve() != item.destination.resolve()]
    existing = [item.destination for item in plan if item.destination.exists()]
    if existing and not merge_existing and not refresh_existing:
        raise ValueError("refusing to overwrite existing paths: " + ", ".join(map(str, existing)))
    if merge_existing:
        plan = [
            item
            for item in plan
            if not item.destination.exists()
            or (item.destination == policy_destination and selected_profiles)
        ]
    elif refresh_existing:
        filtered: list[InstallItem] = []
        for item in plan:
            relative = item.destination.relative_to(target)
            if relative in PRESERVED_CONFIGURATION and item.destination.exists():
                continue
            if relative.parts[:2] == (".github", "workflows") and item.destination.exists() and not installer_owned_workflow(item.destination):
                continue
            filtered.append(item)
        plan = filtered
    if hook_text is not None:
        plan.append(InstallItem(Path("<generated>"), target / ".pre-commit-config.yaml", "generated"))
    if dry_run:
        if temporary_hook:
            temporary_hook.unlink(missing_ok=True)
        return plan

    try:
        for item in plan:
            if item.kind == "remove":
                item.destination.unlink()
                continue
            item.destination.parent.mkdir(parents=True, exist_ok=True)
            if item.kind == "directory":
                shutil.copytree(item.source, item.destination)
            elif item.kind == "generated":
                item.destination.write_text(hook_text or "", encoding="utf-8")
            elif item.destination == policy_destination and selected_profiles:
                existing_policy = policy_destination if merge_existing else None
                item.destination.write_bytes(policy_bytes(existing_policy, selected_profiles))
            elif refresh_existing and item.destination == providers_destination and item.destination.exists():
                item.destination.write_bytes(refreshed_provider_bytes(item.destination))
            else:
                shutil.copy2(item.source, item.destination)
        if refresh_existing and "github" in selected_profiles and policy_destination.exists():
            policy_destination.write_bytes(policy_bytes(policy_destination, selected_profiles))
        if local_hooks:
            executable = shutil.which("pre-commit")
            assert executable is not None
            installed = subprocess.run([executable, "install"], cwd=target, text=True, capture_output=True)
            if installed.returncode != 0:
                (target / ".pre-commit-config.yaml").unlink(missing_ok=True)
                raise ValueError(f"pre-commit hook installation failed: {(installed.stdout + installed.stderr).strip()}")
    finally:
        if temporary_hook:
            temporary_hook.unlink(missing_ok=True)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--profile", action="append", choices=("core", "github"), default=[])
    parser.add_argument("--no-actions", action="store_true")
    parser.add_argument("--local-hooks", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--merge-existing", action="store_true")
    parser.add_argument("--refresh-existing", action="store_true")
    parser.add_argument("--scorecard-badge", action="store_true")
    parser.add_argument("--remove-scorecard-badge", action="store_true")
    args = parser.parse_args()
    try:
        plan = install(
            args.target,
            dry_run=args.dry_run,
            profiles=args.profile,
            no_actions=args.no_actions,
            local_hooks=args.local_hooks,
            merge_existing=args.merge_existing,
            refresh_existing=args.refresh_existing,
            scorecard_badge=args.scorecard_badge,
            remove_scorecard_badge=args.remove_scorecard_badge,
        )
        print(("Would apply" if args.dry_run else "Applied") + " Guardrails v2:")
        for item in plan:
            action = "remove" if item.kind == "remove" else "install"
            print(f"- {action}: {item.destination}")
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
