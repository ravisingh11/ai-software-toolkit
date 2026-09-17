#!/usr/bin/env python3
"""Validate portable, repository-neutral Guardrails v2 installation contracts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
GUARDRAILS = SCRIPT.parents[1]
ROOT = GUARDRAILS.parent

REQUIRED_FILES = (
    "policy.yaml",
    "profiles.yaml",
    "control-catalog.yaml",
    "providers.yaml",
    "policy.schema.json",
    "evidence.schema.json",
    "profiles.schema.json",
    "providers.schema.json",
    "control-catalog.schema.json",
    "evaluate.py",
    "scorecard.py",
    "configure.py",
    "scan.py",
    "doctor.py",
    "github_evidence.py",
    "produce.py",
    "validate_ground_truth.py",
    "semgrep-rules.yml",
    "validators/validate_documentation.py",
    "validators/inspect_change_scope.py",
    "validators/validate_pr_metadata.py",
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def evaluator_module() -> Any:
    path = GUARDRAILS / "evaluate.py"
    spec = importlib.util.spec_from_file_location("installed_guardrails_evaluator", path)
    if not spec or not spec.loader:
        raise ValueError(f"cannot load {path.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate() -> None:
    missing = [name for name in REQUIRED_FILES if not (GUARDRAILS / name).is_file()]
    if missing:
        raise ValueError(f"installed Guardrails runtime is incomplete: {', '.join(missing)}")
    fixtures = GUARDRAILS / "semgrep-tests" / "fixtures"
    if not fixtures.is_dir() or not any(path.is_file() for path in fixtures.rglob("*")):
        raise ValueError("installed Semgrep rule self-test fixtures are missing")

    for name in (
        "policy.schema.json",
        "evidence.schema.json",
        "profiles.schema.json",
        "providers.schema.json",
        "control-catalog.schema.json",
        "semgrep-rules.yml",
    ):
        load(GUARDRAILS / name)

    evaluator = evaluator_module()
    catalog = load(GUARDRAILS / "control-catalog.yaml")
    controls = evaluator.catalog_map(catalog)
    profiles = load(GUARDRAILS / "profiles.yaml")
    profile_definitions = evaluator.validate_profiles(profiles, controls)
    providers = load(GUARDRAILS / "providers.yaml")
    evaluator.validate_provider_config(providers, controls)
    policy = load(GUARDRAILS / "policy.yaml")
    evaluator.validate_policy(policy, set(profile_definitions), controls)


def main() -> int:
    try:
        validate()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    print("Guardrails v2 installed repository contracts validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
