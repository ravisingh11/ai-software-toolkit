#!/usr/bin/env python3
"""Mutate Proof policy and provider selections."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODES = ("advisory", "enforced", "not_activated")
OPERATIONS = ("change", "release")
DEFAULT_POLICY = Path(".proof/policy.yaml")
DEFAULT_PROFILES = Path(".proof/profiles.yaml")
DEFAULT_CATALOG = Path(".proof/control-catalog.yaml")
DEFAULT_PROVIDERS = Path(".proof/providers.yaml")


def evaluator_module() -> Any:
    path = ROOT / "proof" / "evaluate.py"
    if not path.exists():
        path = ROOT / ".proof" / "evaluate.py"
    spec = importlib.util.spec_from_file_location("proof_v2_evaluator", path)
    if not spec or not spec.loader:
        raise ValueError(f"cannot load evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON-compatible YAML {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write_temp_file(path: Path, content: str, mode: int | None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    if mode is not None:
        os.chmod(temporary, mode)
    return temporary


def restore_file(path: Path, existed: bool, content: bytes, mode: int | None) -> None:
    if not existed:
        if path.exists():
            path.unlink()
        return
    temporary = write_temp_file(path, content.decode("utf-8"), mode)
    os.replace(temporary, path)


def write_configuration_pair(
    policy_path: Path,
    provider_path: Path,
    policy: dict[str, Any],
    providers: dict[str, Any],
) -> None:
    if policy_path.resolve() == provider_path.resolve():
        raise ValueError("policy and provider configuration must use different paths")
    policy_content = json.dumps(policy, indent=2) + "\n"
    provider_content = json.dumps(providers, indent=2) + "\n"
    originals = {}
    for path in (policy_path, provider_path):
        existed = path.exists()
        originals[path] = (
            existed,
            path.read_bytes() if existed else b"",
            (path.stat().st_mode & 0o7777) if existed else None,
        )
    policy_temp = write_temp_file(policy_path, policy_content, originals[policy_path][2])
    provider_temp = write_temp_file(provider_path, provider_content, originals[provider_path][2])
    try:
        os.replace(policy_temp, policy_path)
        policy_temp = None
        os.replace(provider_temp, provider_path)
        provider_temp = None
    except OSError:
        rollback_errors = []
        for path in (policy_path, provider_path):
            try:
                restore_file(path, *originals[path])
            except OSError as error:
                rollback_errors.append(f"{path}: {error}")
        if rollback_errors:
            raise RuntimeError(
                "configuration pair write failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            )
        raise
    finally:
        for temporary in (policy_temp, provider_temp):
            if temporary is not None and temporary.exists():
                temporary.unlink()


def parse_choice(choice: str, label: str) -> tuple[str, str]:
    if "=" not in choice:
        raise ValueError(f"invalid {label} {choice!r}; expected CONTROL=VALUE")
    control_id, value = choice.split("=", 1)
    if not control_id or not value:
        raise ValueError(f"invalid {label} {choice!r}; expected CONTROL=VALUE")
    return control_id, value


def validate_documents(
    policy: dict[str, Any], profiles: dict[str, Any], catalog: dict[str, Any], providers: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    evaluator = evaluator_module()
    controls = evaluator.catalog_map(catalog)
    profile_definitions = evaluator.validate_profiles(profiles, controls)
    provider_definitions, _ = evaluator.validate_provider_config(providers, controls)
    evaluator.validate_policy(policy, set(profile_definitions), controls)
    return controls, profile_definitions, provider_definitions


def provider_for_capability(
    provider_definitions: dict[str, dict[str, Any]], control_id: str, provider_id: str
) -> dict[str, Any]:
    if provider_id not in provider_definitions:
        raise ValueError(f"unknown provider: {provider_id}")
    provider = provider_definitions[provider_id]
    if control_id not in provider["capabilities"]:
        raise ValueError(f"provider {provider_id} does not provide {control_id}")
    return provider


def apply_changes(
    policy: dict[str, Any],
    profiles: dict[str, Any],
    catalog: dict[str, Any],
    provider_config: dict[str, Any],
    *,
    operation: str,
    all_operations: bool,
    enable_profiles: list[str] | None = None,
    disable_profiles: list[str] | None = None,
    select_providers: list[str] | None = None,
    add_supplemental: list[str] | None = None,
    remove_supplemental: list[str] | None = None,
    sets: list[str] | None = None,
) -> None:
    controls, profile_definitions, provider_definitions = validate_documents(
        policy, profiles, catalog, provider_config
    )
    enable_profiles = enable_profiles or []
    disable_profiles = disable_profiles or []
    select_providers = select_providers or []
    add_supplemental = add_supplemental or []
    remove_supplemental = remove_supplemental or []
    sets = sets or []
    if operation not in OPERATIONS:
        raise ValueError(f"unknown operation: {operation}")

    for profile_id in enable_profiles:
        if profile_id not in profile_definitions:
            raise ValueError(f"unknown profile: {profile_id}")
        if profile_id not in policy["profiles"]:
            policy["profiles"].append(profile_id)
    for profile_id in disable_profiles:
        if profile_id not in profile_definitions:
            raise ValueError(f"unknown profile: {profile_id}")
        if profile_id not in policy["profiles"]:
            raise ValueError(f"profile is not enabled: {profile_id}")
        if len(policy["profiles"]) == 1:
            raise ValueError("cannot remove the last profile")
        policy["profiles"].remove(profile_id)

    for choice in remove_supplemental:
        control_id, provider_id = parse_choice(choice, "supplemental removal")
        if control_id not in provider_config["selections"]:
            raise ValueError(f"unknown control: {control_id}")
        supplemental = provider_config["selections"][control_id]["supplemental"]
        if provider_id not in supplemental:
            raise ValueError(f"provider {provider_id} is not supplemental for {control_id}")
        supplemental.remove(provider_id)

    for choice in select_providers:
        control_id, provider_id = parse_choice(choice, "provider selection")
        if control_id not in provider_config["selections"]:
            raise ValueError(f"unknown control: {control_id}")
        provider_for_capability(provider_definitions, control_id, provider_id)
        selection = provider_config["selections"][control_id]
        if provider_id in selection["supplemental"]:
            raise ValueError(f"remove it from supplemental before selecting {provider_id} as authority for {control_id}")
        selection["authoritative"] = provider_id

    for choice in add_supplemental:
        control_id, provider_id = parse_choice(choice, "supplemental provider")
        if control_id not in provider_config["selections"]:
            raise ValueError(f"unknown control: {control_id}")
        provider_for_capability(provider_definitions, control_id, provider_id)
        selection = provider_config["selections"][control_id]
        if provider_id == selection["authoritative"]:
            raise ValueError(f"provider {provider_id} is authoritative for {control_id}")
        if provider_id in selection["supplemental"]:
            raise ValueError(f"duplicate supplemental provider {provider_id} for {control_id}")
        selection["supplemental"].append(provider_id)

    target_operations = list(OPERATIONS) if all_operations else [operation]
    evaluator = evaluator_module()
    mode_updates: list[tuple[str, str]] = []
    for choice in sets:
        control_id, mode = parse_choice(choice, "mode selection")
        if control_id not in controls:
            raise ValueError(f"unknown control: {control_id}")
        if controls[control_id]["availability"] == "evidence-only":
            raise ValueError(f"cannot set evidence-only control: {control_id}")
        if mode not in MODES:
            raise ValueError(f"mode must be one of: {', '.join(MODES)}")
        for target_operation in target_operations:
            if not evaluator.operation_supports_stage(
                target_operation,
                controls[control_id]["stage"],
            ):
                raise ValueError(f"{control_id} cannot be configured for {target_operation}")
        mode_updates.append((control_id, mode))

    for control_id, mode in mode_updates:
        for target_operation in target_operations:
            policy["overrides"][target_operation][control_id] = mode

    validate_documents(policy, profiles, catalog, provider_config)


def effective_modes(policy: dict[str, Any], profile_definitions: dict[str, dict[str, Any]], operation: str) -> dict[str, str]:
    modes: dict[str, str] = {}
    for profile_id in policy["profiles"]:
        for control_id, mode in profile_definitions[profile_id]["defaults"][operation].items():
            previous = modes.get(control_id)
            if previous is not None and previous != mode:
                raise ValueError(f"conflicting profile defaults for {control_id}")
            modes[control_id] = mode
    modes.update(policy["overrides"][operation])
    return modes


def render_listing(
    policy: dict[str, Any], profiles: dict[str, Any], catalog: dict[str, Any],
    provider_config: dict[str, Any], operation: str,
) -> str:
    controls, profile_definitions, provider_definitions = validate_documents(
        policy, profiles, catalog, provider_config
    )
    modes = effective_modes(policy, profile_definitions, operation)
    lines = [f"Profiles: {', '.join(policy['profiles'])}", f"Operation: {operation}"]
    for control_id, control in controls.items():
        mode = modes.get(control_id, "not_activated")
        selection = provider_config["selections"].get(control_id)
        if selection:
            authority = provider_definitions[selection["authoritative"]]["display_name"]
            supplemental = ", ".join(provider_definitions[item]["display_name"] for item in selection["supplemental"]) or "none"
        else:
            authority = supplemental = "evidence-only"
        lines.append(f"{mode:13} {control['name']} — {authority} (supplemental: {supplemental})")
    return "\n".join(lines) + "\n"


def render_effective_mode(
    policy: dict[str, Any],
    profiles: dict[str, Any],
    catalog: dict[str, Any],
    provider_config: dict[str, Any],
    operation: str,
    control_id: str,
) -> str:
    controls, profile_definitions, _ = validate_documents(
        policy, profiles, catalog, provider_config
    )
    if control_id not in controls:
        raise ValueError(f"unknown control: {control_id}")
    mode = effective_modes(policy, profile_definitions, operation).get(
        control_id, "not_activated"
    )
    return json.dumps(
        {"control_id": control_id, "mode": mode, "operation": operation}
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Proof profiles, modes, and providers")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--providers", type=Path, default=DEFAULT_PROVIDERS)
    parser.add_argument("--enable-profile", action="append", default=[])
    parser.add_argument("--disable-profile", action="append", default=[])
    parser.add_argument("--select-provider", action="append", default=[], metavar="CONTROL=PROVIDER")
    parser.add_argument("--add-supplemental", action="append", default=[], metavar="CONTROL=PROVIDER")
    parser.add_argument("--remove-supplemental", action="append", default=[], metavar="CONTROL=PROVIDER")
    parser.add_argument("--set", action="append", default=[], metavar="CONTROL=MODE")
    parser.add_argument("--operation", choices=OPERATIONS, default="change")
    parser.add_argument("--all-operations", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--effective-mode", metavar="CONTROL")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        policy = load_object(args.policy)
        profiles = load_object(args.profiles)
        catalog = load_object(args.catalog)
        providers = load_object(args.providers)
        if args.list and args.effective_mode:
            raise ValueError("use either --list or --effective-mode")
        if args.effective_mode:
            print(
                render_effective_mode(
                    policy,
                    profiles,
                    catalog,
                    providers,
                    args.operation,
                    args.effective_mode,
                ),
                end="",
            )
            return 0
        if args.list:
            print(render_listing(policy, profiles, catalog, providers, args.operation), end="")
            return 0
        mutations = [
            *args.enable_profile, *args.disable_profile, *args.select_provider,
            *args.add_supplemental, *args.remove_supplemental, *args.set,
        ]
        if not mutations:
            raise ValueError("provide a v2 configuration mutation or use --list")
        apply_changes(
            policy, profiles, catalog, providers, operation=args.operation,
            all_operations=args.all_operations,
            enable_profiles=args.enable_profile, disable_profiles=args.disable_profile,
            select_providers=args.select_provider, add_supplemental=args.add_supplemental,
            remove_supplemental=args.remove_supplemental, sets=args.set,
        )
        if args.dry_run:
            print(json.dumps({"policy": policy, "provider_config": providers}, indent=2) + "\n")
        else:
            write_configuration_pair(args.policy, args.providers, policy, providers)
            print(f"Updated {args.policy} and {args.providers}")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
