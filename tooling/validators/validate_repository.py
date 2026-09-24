#!/usr/bin/env python3
"""Validate the canonical guardrails repository."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ABSOLUTE_PATH_PATTERN = re.compile(r"(/Users/|/private/|\\\\Users\\\\)")
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
REPO_RELATIVE_PATH_PATTERN = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)(?!.*\\)[^\x00-\x1f\x7f]+$"
)
CONTROL_FIELDS = {
    "id", "name", "purpose", "stage", "availability", "evidence_subject",
    "enforcement_policy",
}
OPERATIONS = {"change", "release"}
MODES = {"advisory", "enforced", "not_activated"}
CONTROL_STAGES = {
    "change", "change-and-release", "pre-release", "release",
    "deployment", "post-deployment", "runtime",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(f"{path.relative_to(ROOT)} is not JSON-compatible YAML: {error}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must contain an object")
    return value


def validate_skills() -> int:
    count = 0
    for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
        lines = skill.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---" or not any(
            line.lstrip().startswith("description:") for line in lines
        ):
            fail(f"{skill.relative_to(ROOT)} is missing valid frontmatter")
        if not (skill.parent / "agents" / "openai.yaml").exists():
            fail(f"{skill.parent.relative_to(ROOT)} is missing agents/openai.yaml")
        count += 1
    if count == 0:
        fail("skills/ must contain at least one skill")
    return count


def valid_identifier(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 80 and bool(IDENTIFIER_PATTERN.fullmatch(value))


def require_nonempty_string(value: object, label: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def validate_control_catalog_document(catalog: dict) -> dict[str, dict]:
    if catalog.get("version") != 2 or set(catalog) != {"version", "controls"}:
        raise ValueError("control catalog must contain only version 2 and controls")
    if not isinstance(catalog.get("controls"), list) or not catalog["controls"]:
        raise ValueError("control catalog controls must be a non-empty list")
    seen: set[str] = set()
    for control in catalog["controls"]:
        if not isinstance(control, dict) or set(control) != CONTROL_FIELDS:
            raise ValueError("every control must define exactly the v2 control fields")
        control_id = control["id"]
        if not valid_identifier(control_id):
            raise ValueError("control id must be a valid identifier")
        if control_id in seen:
            raise ValueError(f"duplicate control id: {control_id}")
        seen.add(control_id)
        for field, maximum in (("name", 200), ("purpose", 500), ("stage", 200)):
            require_nonempty_string(
                control[field], f"control {control_id} {field}", maximum
            )
        if control["stage"] not in CONTROL_STAGES:
            raise ValueError(f"control {control_id} stage is invalid")
        if control["availability"] not in {"runnable", "evidence-only"}:
            raise ValueError(f"control {control_id} availability is invalid")
        if control["evidence_subject"] not in {"git-commit", "artifact", "environment", "pull-request"}:
            raise ValueError(f"control {control_id} evidence_subject is invalid")
        if control["enforcement_policy"] not in {"promotable", "advisory-only"}:
            raise ValueError(f"control {control_id} enforcement_policy is invalid")
    return {control["id"]: control for control in catalog["controls"]}


def validate_profiles_document(profiles: dict, catalog: dict[str, dict]) -> None:
    if profiles.get("version") != 2 or set(profiles) != {"version", "profiles"}:
        raise ValueError("profiles must contain only version 2 and profiles")
    definitions = profiles.get("profiles")
    if not isinstance(definitions, dict) or set(definitions) != {"core", "github"}:
        raise ValueError("core and github must be the only runnable profiles")
    for profile_id, profile in definitions.items():
        if not isinstance(profile, dict) or set(profile) != {
            "display_name", "description", "runnable", "defaults"
        }:
            raise ValueError(f"profile {profile_id} has invalid fields")
        require_nonempty_string(profile["display_name"], f"profile {profile_id} display_name")
        require_nonempty_string(profile["description"], f"profile {profile_id} description", 500)
        if profile["runnable"] is not True:
            raise ValueError(f"profile {profile_id} must be runnable")
        defaults = profile["defaults"]
        if not isinstance(defaults, dict) or set(defaults) != OPERATIONS:
            raise ValueError(f"profile {profile_id} defaults must define change and release")
        for operation, modes in defaults.items():
            if not isinstance(modes, dict):
                raise ValueError(f"profile {profile_id} {operation} defaults must be an object")
            for control_id, mode in modes.items():
                if control_id not in catalog:
                    raise ValueError(f"profile {profile_id} references unknown control: {control_id}")
                if mode != "advisory":
                    raise ValueError(f"profile {profile_id} defaults must be advisory")


def validate_provider_document(config: dict, catalog: dict[str, dict]) -> None:
    if config.get("version") != 2 or set(config) != {"version", "providers", "selections"}:
        raise ValueError("provider config must contain version 2, providers, and selections")
    providers = config.get("providers")
    selections = config.get("selections")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("providers must be a non-empty object")
    if not isinstance(selections, dict):
        raise ValueError("selections must be an object")
    provider_fields = {
        "display_name", "activation", "capabilities", "checks", "template",
        "template_available", "secrets", "enabled_by_default",
    }
    for provider_id, provider in providers.items():
        if not valid_identifier(provider_id) or not isinstance(provider, dict):
            raise ValueError("provider entries must use valid identifiers and objects")
        if set(provider) not in (provider_fields, provider_fields | {"reviews"}):
            raise ValueError(f"provider {provider_id} has invalid fields")
        require_nonempty_string(provider["display_name"], f"provider {provider_id} display_name")
        if provider["activation"] not in {"repository", "github", "external"}:
            raise ValueError(f"provider {provider_id} activation is invalid")
        capabilities = provider["capabilities"]
        if (
            not isinstance(capabilities, list)
            or not capabilities
            or len(capabilities) != len(set(capabilities))
            or any(capability not in catalog for capability in capabilities)
        ):
            raise ValueError(f"provider {provider_id} capabilities are invalid")
        checks = provider["checks"]
        if not isinstance(checks, dict) or any(capability not in capabilities for capability in checks):
            raise ValueError(f"provider {provider_id} checks are invalid")
        for capability, check in checks.items():
            if (
                not isinstance(check, dict)
                or not {"check_name", "workflow"}.issubset(check)
                or set(check) - {
                    "check_name", "workflow", "workflow_path", "app_slug", "external_id_prefix",
                    "artifact_name_prefix", "artifact_member", "trusted_paths",
                }
            ):
                raise ValueError(f"provider {provider_id} {capability} check is invalid")
            require_nonempty_string(check["check_name"], f"provider {provider_id} check_name")
            require_nonempty_string(check["workflow"], f"provider {provider_id} workflow")
            if "workflow_path" in check:
                require_nonempty_string(
                    check["workflow_path"],
                    f"provider {provider_id} {capability} workflow_path",
                )
            if "app_slug" in check:
                require_nonempty_string(
                    check["app_slug"],
                    f"provider {provider_id} {capability} app_slug",
                    100,
                )
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", check["app_slug"]) is None:
                    raise ValueError(f"provider {provider_id} {capability} app_slug is invalid")
            if ("workflow_path" in check) == ("app_slug" in check):
                raise ValueError(
                    f"provider {provider_id} {capability} must declare exactly one of workflow_path or app_slug"
                )
            trusted_paths = check.get("trusted_paths")
            if trusted_paths is not None:
                if (
                    "workflow_path" not in check
                    or not isinstance(trusted_paths, list)
                    or not trusted_paths
                    or any(not isinstance(path, str) for path in trusted_paths)
                    or len(trusted_paths) != len(set(trusted_paths))
                    or any(
                        len(path) > 300
                        or REPO_RELATIVE_PATH_PATTERN.fullmatch(path) is None
                        for path in trusted_paths
                    )
                ):
                    raise ValueError(
                        f"provider {provider_id} {capability} trusted_paths are invalid"
                    )
            if "external_id_prefix" in check:
                require_nonempty_string(
                    check["external_id_prefix"],
                    f"provider {provider_id} {capability} external_id_prefix",
                    150,
                )
            if "artifact_name_prefix" in check:
                require_nonempty_string(
                    check["artifact_name_prefix"],
                    f"provider {provider_id} {capability} artifact_name_prefix",
                    150,
                )
            if "artifact_member" in check:
                require_nonempty_string(
                    check["artifact_member"],
                    f"provider {provider_id} {capability} artifact_member",
                    100,
                )
                if re.fullmatch(r"[A-Za-z0-9._-]+", check["artifact_member"]) is None:
                    raise ValueError(f"provider {provider_id} {capability} artifact_member is invalid")
            artifact_fields = {"artifact_name_prefix", "artifact_member"}
            if "external_id_prefix" in check and not artifact_fields.issubset(check):
                raise ValueError(f"provider {provider_id} {capability} custom check artifact contract is incomplete")
            if "external_id_prefix" not in check and artifact_fields.intersection(check):
                raise ValueError(f"provider {provider_id} {capability} artifact contract requires external_id_prefix")
            if "external_id_prefix" in check and "workflow_path" not in check:
                raise ValueError(f"provider {provider_id} {capability} artifact contract requires workflow_path")
        reviews = provider.get("reviews", {})
        if not isinstance(reviews, dict) or any(
            capability not in capabilities for capability in reviews
        ):
            raise ValueError(f"provider {provider_id} reviews are invalid")
        overlapping_contracts = sorted(set(checks).intersection(reviews))
        if overlapping_contracts:
            raise ValueError(
                f"provider {provider_id} {overlapping_contracts[0]} cannot declare both a check and a review"
            )
        for capability, review in reviews.items():
            if not isinstance(review, dict) or set(review) != {"review_author"}:
                raise ValueError(f"provider {provider_id} {capability} review is invalid")
            author = review["review_author"]
            if (
                not isinstance(author, str)
                or len(author) > 100
                or re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?",
                    author,
                ) is None
            ):
                raise ValueError(
                    f"provider {provider_id} {capability} review_author is invalid"
                )
        template = provider["template"]
        if template is not None:
            require_nonempty_string(template, f"provider {provider_id} template")
            expected_path = f".github/workflows/{Path(template).name}"
            for capability, check in checks.items():
                if check.get("workflow_path") != expected_path:
                    raise ValueError(
                        f"provider {provider_id} {capability} workflow_path must be {expected_path}"
                    )
        if not isinstance(provider["template_available"], bool):
            raise ValueError(f"provider {provider_id} template_available must be boolean")
        secrets = provider["secrets"]
        if (
            not isinstance(secrets, list)
            or len(secrets) != len(set(secrets))
            or any(not isinstance(secret, str) or not secret for secret in secrets)
        ):
            raise ValueError(f"provider {provider_id} secrets are invalid")
        if not isinstance(provider["enabled_by_default"], bool):
            raise ValueError(f"provider {provider_id} enabled_by_default must be boolean")

    runnable = {
        control_id for control_id, control in catalog.items()
        if control.get("availability") == "runnable"
    }
    if set(selections) != runnable:
        raise ValueError("selections must cover exactly the runnable controls")
    for capability, selection in selections.items():
        if not isinstance(selection, dict) or set(selection) != {"authoritative", "supplemental"}:
            raise ValueError(f"selection {capability} must define authoritative and supplemental")
        authority = selection["authoritative"]
        if not isinstance(authority, str) or not authority:
            raise ValueError(f"selection {capability} authoritative must be exactly one provider")
        if authority not in providers:
            raise ValueError(f"selection {capability} references unknown provider: {authority}")
        if capability not in providers[authority]["capabilities"]:
            raise ValueError(f"provider {authority} does not provide {capability}")
        supplemental = selection["supplemental"]
        if not isinstance(supplemental, list) or any(not isinstance(item, str) for item in supplemental):
            raise ValueError(f"selection {capability} supplemental must be a list")
        if len(supplemental) != len(set(supplemental)):
            raise ValueError(f"selection {capability} has duplicate supplemental providers")
        if authority in supplemental:
            raise ValueError(f"selection {capability} authority is also supplemental")
        for provider_id in supplemental:
            if provider_id not in providers:
                raise ValueError(f"selection {capability} references unknown provider: {provider_id}")
            if capability not in providers[provider_id]["capabilities"]:
                raise ValueError(f"provider {provider_id} does not provide {capability}")


def validate_provider_template_names(config: dict, root: Path = ROOT) -> None:
    for provider_id, provider in config["providers"].items():
        template = provider["template"]
        if not provider["template_available"]:
            continue
        if template is None:
            raise ValueError(
                f"provider {provider_id} declares a template available without a template path"
            )
        template_path = root / template
        if not template_path.is_file():
            raise ValueError(f"provider {provider_id} template does not exist: {template}")
        workflow_name = None
        for line in template_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("name:"):
                workflow_name = line.split(":", 1)[1].strip().strip("'\"")
                break
        if not workflow_name:
            raise ValueError(f"provider {provider_id} template workflow name is missing")
        for capability, check in provider["checks"].items():
            if check["workflow"] != workflow_name:
                raise ValueError(
                    f"provider {provider_id} {capability} template workflow name "
                    f"{workflow_name!r} does not match contract {check['workflow']!r}"
                )


def validate_policy_document(
    policy: dict, profiles: set[str], controls: dict[str, dict]
) -> None:
    if not isinstance(policy, dict) or policy.get("version") != 2:
        raise ValueError("policy version must be 2")
    if set(policy) not in ({"version", "name", "profiles", "overrides"}, {"$schema", "version", "name", "profiles", "overrides"}):
        raise ValueError("policy has invalid fields")
    require_nonempty_string(policy.get("name"), "policy name", 100)
    selected = policy.get("profiles")
    if (
        not isinstance(selected, list)
        or not selected
        or len(selected) != len(set(selected))
        or any(profile not in profiles for profile in selected)
    ):
        raise ValueError("policy profiles are invalid")
    overrides = policy.get("overrides")
    if not isinstance(overrides, dict) or set(overrides) != OPERATIONS:
        raise ValueError("policy overrides must define change and release")
    for operation, modes in overrides.items():
        if not isinstance(modes, dict):
            raise ValueError(f"policy {operation} overrides must be an object")
        for control_id, mode in modes.items():
            if not valid_identifier(control_id) or mode not in MODES:
                raise ValueError(f"policy {operation} override is invalid")
            if control_id not in controls:
                raise ValueError(
                    f"policy {operation} override references unknown control: {control_id}"
                )
            if (
                mode == "enforced"
                and controls[control_id].get("enforcement_policy") != "promotable"
            ):
                raise ValueError(
                    f"control {control_id} is advisory-only and cannot be enforced"
                )


def validate_evidence_document(
    document: dict, catalog: dict[str, dict], providers: dict[str, dict]
) -> None:
    if not isinstance(document, dict) or document.get("version") != 2:
        raise ValueError("evidence version must be 2")
    if set(document) not in ({"version", "subject", "results"}, {"$schema", "version", "subject", "results"}):
        raise ValueError("evidence has invalid fields")
    subject = document.get("subject")
    if not isinstance(subject, dict) or set(subject) != {"type", "revision"}:
        raise ValueError("evidence subject is invalid")
    if subject["type"] not in {
        "git-commit", "artifact", "environment", "pull-request"
    }:
        raise ValueError("evidence subject type is invalid")
    require_nonempty_string(subject["revision"], "evidence subject revision")
    results = document.get("results")
    if not isinstance(results, dict):
        raise ValueError("evidence results must be an object")
    for control_id, provider_results in results.items():
        if not valid_identifier(control_id) or not isinstance(provider_results, dict):
            raise ValueError("evidence control results must be provider objects")
        if control_id not in catalog:
            raise ValueError(f"evidence references unknown control: {control_id}")
        if not provider_results:
            raise ValueError(f"evidence {control_id} must contain at least one provider")
        required_subject = catalog[control_id]["evidence_subject"]
        if subject["type"] != required_subject:
            raise ValueError(
                f"evidence {control_id} requires {required_subject} subject"
            )
        for provider_id, result in provider_results.items():
            if not valid_identifier(provider_id) or not isinstance(result, dict):
                raise ValueError(f"evidence {control_id} provider result is invalid")
            if provider_id not in providers:
                raise ValueError(
                    f"evidence {control_id} references unknown provider: {provider_id}"
                )
            if control_id not in providers[provider_id]["capabilities"]:
                raise ValueError(f"provider {provider_id} does not provide {control_id}")
            if set(result) - {"producer", "status", "evidence", "reason"}:
                raise ValueError(f"evidence {control_id}.{provider_id} has invalid fields")
            require_nonempty_string(result.get("producer"), f"evidence {control_id}.{provider_id} producer")
            status = result.get("status")
            if status not in {"passed", "failed", "blocked", "not_run"}:
                raise ValueError(f"evidence {control_id}.{provider_id} status is invalid")
            records = result.get("evidence")
            invalid_records = (
                not isinstance(records, list)
                or not records
                or any(
                    not isinstance(record, str)
                    or not record.strip()
                    or len(record) > 1000
                    for record in records
                )
            )
            if (records is not None and invalid_records) or (
                status in {"passed", "failed"} and records is None
            ):
                raise ValueError(f"evidence {control_id}.{provider_id} evidence records are required")
            reason = result.get("reason")
            invalid_reason = (
                not isinstance(reason, str) or not reason.strip() or len(reason) > 1000
            )
            if (reason is not None and invalid_reason) or (
                status in {"blocked", "not_run"} and reason is None
            ):
                raise ValueError(f"evidence {control_id}.{provider_id} reason is required")


def validate_control_catalog() -> int:
    catalog = load_json_object(ROOT / "policies" / "control-catalog.yaml")
    try:
        controls = validate_control_catalog_document(catalog)
    except ValueError as error:
        fail(str(error))
    return len(controls)


def validate_guardrail_contract() -> None:
    catalog = validate_control_catalog_document(
        load_json_object(ROOT / "policies" / "control-catalog.yaml")
    )
    profiles = load_json_object(ROOT / "policies" / "profiles.yaml")
    validate_profiles_document(profiles, catalog)
    provider_config = load_json_object(ROOT / "policies" / "provider-config.yaml")
    validate_provider_document(provider_config, catalog)
    validate_provider_template_names(provider_config)
    validate_policy_document(
        load_json_object(ROOT / "guardrails" / "baseline.yaml"),
        set(profiles["profiles"]),
        catalog,
    )
    validate_evidence_document(
        load_json_object(ROOT / "guardrails" / "evidence-example.yaml"),
        catalog,
        provider_config["providers"],
    )
    for name in (
        "control-catalog.schema.json", "profiles.schema.json", "providers.schema.json",
        "policy.schema.json", "evidence.schema.json",
    ):
        schema = load_json_object(ROOT / "guardrails" / name)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            fail(f"{name} must use JSON Schema 2020-12")
        if schema.get("properties", {}).get("version", {}).get("const") != 2:
            fail(f"{name} must describe version 2")


def validate_links_and_docs() -> None:
    subprocess.run(
        [sys.executable, "tooling/validators/validate_documentation.py"],
        cwd=ROOT,
        check=True,
    )


def validate_no_machine_paths() -> None:
    for path in ROOT.rglob("*"):
        relative_path = path.relative_to(ROOT)
        if not path.is_file() or ".git" in path.parts:
            continue
        if relative_path.parts[0] in {".artifacts", ".superpowers"}:
            continue
        if path.name in {"validate_repository.py", "validate-skills.py"}:
            continue
        if path.suffix not in {".md", ".py", ".yaml", ".yml", ".sh"}:
            continue
        if ABSOLUTE_PATH_PATTERN.search(path.read_text(encoding="utf-8")):
            fail(f"{relative_path} contains a machine-local path")


def main() -> int:
    skills = validate_skills()
    controls = validate_control_catalog()
    validate_guardrail_contract()
    validate_links_and_docs()
    validate_no_machine_paths()
    print(f"Validated {skills} skills, {controls} controls, guardrail schemas, and documentation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
