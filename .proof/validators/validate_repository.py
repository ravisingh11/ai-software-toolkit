#!/usr/bin/env python3
"""Validate portable, repository-neutral Proof installation contracts."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
PROOF = SCRIPT.parents[1]
ROOT = PROOF.parent

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
    "adapter.py",
    "measurements.py",
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
    path = PROOF / "evaluate.py"
    spec = importlib.util.spec_from_file_location("installed_proof_evaluator", path)
    if not spec or not spec.loader:
        raise ValueError(f"cannot load {path.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_runtime_files() -> None:
    missing = [name for name in REQUIRED_FILES if not (PROOF / name).is_file()]
    if missing:
        raise ValueError(f"installed Proof runtime is incomplete: {', '.join(missing)}")


def check_semgrep_fixtures() -> None:
    fixtures = PROOF / "semgrep-tests" / "fixtures"
    if not fixtures.is_dir() or not any(path.is_file() for path in fixtures.rglob("*")):
        raise ValueError("installed Semgrep rule self-test fixtures are missing")


def check_schemas() -> None:
    for name in (
        "policy.schema.json",
        "evidence.schema.json",
        "profiles.schema.json",
        "providers.schema.json",
        "control-catalog.schema.json",
        "semgrep-rules.yml",
    ):
        load(PROOF / name)


def check_configuration() -> None:
    evaluator = evaluator_module()
    catalog = load(PROOF / "control-catalog.yaml")
    controls = evaluator.catalog_map(catalog)
    profiles = load(PROOF / "profiles.yaml")
    profile_definitions = evaluator.validate_profiles(profiles, controls)
    providers = load(PROOF / "providers.yaml")
    evaluator.validate_provider_config(providers, controls)
    policy = load(PROOF / "policy.yaml")
    evaluator.validate_policy(policy, set(profile_definitions), controls)


# Ordered contract groups. Each depends on the ones before it, so the first
# failure stops the run and the remaining groups are reported as not run.
CONTRACTS = (check_runtime_files, check_semgrep_fixtures, check_schemas, check_configuration)


def validate(counts: dict[str, int] | None = None) -> None:
    passed = 0
    try:
        for contract in CONTRACTS:
            contract()
            passed += 1
    finally:
        if counts is not None:
            failed = int(passed < len(CONTRACTS))
            counts.update(total=len(CONTRACTS), passed=passed, failed=failed,
                          not_run=len(CONTRACTS) - passed - failed)


def record_measurements(counts: dict[str, int]) -> None:
    """Write optional display counts for the scorecard; never affects the result."""
    target = os.environ.get("PROOF_MEASUREMENTS_FILE")
    if not target or set(counts) != {"total", "passed", "failed", "not_run"}:
        return
    document = {"version": 1, "source": "pull-request-workflow", "contracts": counts}
    try:
        Path(target).write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"WARNING: repository measurements were not recorded: {error}", file=sys.stderr)


def main() -> int:
    counts: dict[str, int] = {}
    try:
        validate(counts)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        record_measurements(counts)
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    record_measurements(counts)
    print(f"Proof installed repository contracts validated ({counts['passed']} contract groups)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
