#!/usr/bin/env python3
"""Run local Guardrails v2 producers and render revision-bound artifacts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]


def runtime_path(
    root: Path,
    *,
    scanner_path: Path,
    installed_relative: Path,
    source_relative: Path,
) -> Path:
    source_scanner = root / "tooling" / "scan_repository.py"
    source_mode = scanner_path.resolve() == source_scanner.resolve()
    path = root / (source_relative if source_mode else installed_relative)
    if not path.is_file():
        mode = "source" if source_mode else "installed"
        raise ValueError(f"{mode} runtime is missing: {path}")
    return path


def evaluator_module() -> Any:
    path = runtime_path(
        ROOT,
        scanner_path=Path(__file__),
        installed_relative=Path(".guardrails/evaluate.py"),
        source_relative=Path("guardrails/evaluate.py"),
    )
    spec = importlib.util.spec_from_file_location("guardrails_v2_evaluator", path)
    if not spec or not spec.loader:
        raise ValueError(f"cannot load evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def producer_module() -> Any:
    path = runtime_path(
        ROOT,
        scanner_path=Path(__file__),
        installed_relative=Path(".guardrails/produce.py"),
        source_relative=Path("tooling/produce_guardrail_evidence.py"),
    )
    spec = importlib.util.spec_from_file_location("guardrails_v2_producers", path)
    if not spec or not spec.loader:
        raise ValueError(f"cannot load producers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(command: list[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def default_config_path(target: Path, consumer_path: str, shared_path: str) -> Path:
    if target == ROOT and (target / shared_path).exists():
        return target / shared_path
    return target / consumer_path


def result_for_command(producer: str, command: list[str], code: int, output: str) -> dict[str, Any]:
    return {
        "producer": producer,
        "status": "passed" if code == 0 else "failed",
        "evidence": [" ".join(command), output[-1000:] or "command completed without output"],
    }


def revision_bound_tool_result(
    producers: Any,
    target: Path,
    revision: str,
    producer_name: str,
    callback: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        producers.exact_clean_head(target, revision)
    except (OSError, ValueError) as error:
        return producers.producer_result(
            producer_name,
            "not_run",
            reason=f"Revision-bound tool evidence could not start: {error}",
        )
    result = callback()
    try:
        producers.exact_clean_head(target, revision)
    except (OSError, ValueError) as error:
        return producers.producer_result(
            producer_name,
            "not_run",
            reason=f"The repository changed while the tool ran: {error}",
        )
    return result


def local_binding(target: Path, requested_revision: str) -> tuple[str | None, str | None]:
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=target,
        text=True,
        capture_output=True,
    )
    requested = subprocess.run(
        ["git", "rev-parse", "--verify", f"{requested_revision}^{{commit}}"],
        cwd=target,
        text=True,
        capture_output=True,
    )
    if head.returncode != 0 or requested.returncode != 0:
        return None, "Local evidence requires an exact immutable commit that resolves in this repository."
    head_revision = head.stdout.strip()
    requested_full = requested.stdout.strip()
    if head_revision != requested_full:
        return None, "Local evidence requires the requested revision to exactly match HEAD."
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=target,
        text=True,
        capture_output=True,
    )
    if status.returncode != 0:
        return None, "Local evidence requires repository cleanliness to be verified."
    if status.stdout:
        return None, "Local evidence requires a clean worktree before providers run."
    return head_revision, None


def exact_local_revision(target: Path, reference: str) -> tuple[str | None, str | None]:
    resolved = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{reference}^{{commit}}",
        ],
        cwd=target,
        text=True,
        capture_output=True,
    )
    revision = resolved.stdout.strip()
    if resolved.returncode != 0 or not revision:
        return None, f"Local evidence requires the base revision {reference!r} to resolve to a commit."
    return revision, None


def unavailable_local_evidence(revision: str, reason: str) -> dict[str, Any]:
    results = {}
    for control_id, provider_id, producer in (
        ("repository-validation", "repository-validator", "local repository validation"),
        ("documentation-validation", "repository-validator", "local documentation validation"),
        ("repository-ground-truth", "repository-validator", "repository ground-truth validator"),
        ("change-scope", "repository-change-scope", "local change-scope inspection"),
        ("build", "repository-build", "Repository Build Command"),
        ("unit-tests", "repository-unit-tests", "Repository Unit Test Command"),
        ("changed-code-coverage", "repository-changed-code-coverage", "Repository Changed Code Coverage Command"),
        ("custom-static-analysis", "semgrep-ce", "Semgrep Community Edition 1.175.0"),
        ("secret-detection", "gitleaks", "Gitleaks CLI 8.30.1"),
    ):
        results[control_id] = {
            provider_id: {
                "producer": producer,
                "status": "not_run",
                "reason": reason,
            }
        }
    return {"version": 2, "subject": {"type": "git-commit", "revision": revision}, "results": results}


def configuration_presence_evidence(path: Path, target: Path, provider_name: str) -> dict[str, Any]:
    return {
        "producer": f"{provider_name} configuration inspection",
        "status": "not_run",
        "evidence": [f"configuration: {path.relative_to(target)}"],
        "reason": "Configuration presence is not revision-bound provider evidence and cannot satisfy this capability.",
    }


def local_evidence(target: Path, revision: str, base_ref: str) -> dict[str, Any]:
    bound_revision, binding_error = local_binding(target, revision)
    if binding_error:
        return unavailable_local_evidence(revision, binding_error)
    assert bound_revision is not None
    revision = bound_revision
    base_revision, base_error = exact_local_revision(target, base_ref)
    results: dict[str, dict[str, dict[str, Any]]] = {}
    validators = target / "tooling" / "validators"
    if not validators.is_dir():
        validators = target / ".guardrails" / "validators"
    for control_id, filename, producer in (
        ("repository-validation", "validate_repository.py", "local repository validation"),
        ("documentation-validation", "validate_documentation.py", "local documentation validation"),
    ):
        validator = validators / filename
        if validator.exists():
            command = [sys.executable, str(validator)]
            if filename == "validate_documentation.py":
                if base_error:
                    record = {
                        "producer": producer,
                        "status": "not_run",
                        "reason": base_error,
                    }
                    results[control_id] = {"repository-validator": record}
                    continue
                assert base_revision is not None
                command.extend([
                    "--base-ref", base_revision,
                    "--head-ref", revision,
                ])
            code, output = run(command, target)
            record = result_for_command(producer, command, code, output)
        else:
            record = {
                "producer": producer,
                "status": "not_run",
                "reason": f"{validator.relative_to(target)} is not installed in this repository",
            }
        results[control_id] = {"repository-validator": record}

    ground_truth_validator = target / ".guardrails" / "validate_ground_truth.py"
    ground_truth_policy = target / ".guardrails" / "ground-truth-ai.yaml"
    if ground_truth_validator.exists() and ground_truth_policy.exists():
        command = [sys.executable, str(ground_truth_validator), "--policy", str(ground_truth_policy)]
        code, output = run(command, target)
        record = result_for_command("repository ground-truth validator", command, code, output)
    else:
        record = {
            "producer": "repository ground-truth validator",
            "status": "not_run",
            "reason": "repository ground-truth validator and policy are not both installed",
        }
    results["repository-ground-truth"] = {"repository-validator": record}

    scope_validator = validators / "inspect_change_scope.py"
    if scope_validator.exists() and base_error:
        record = {
            "producer": "local change-scope inspection",
            "status": "not_run",
            "reason": base_error,
        }
    elif scope_validator.exists():
        assert base_revision is not None
        with tempfile.NamedTemporaryFile(suffix=".json") as scope_file:
            command = [
                sys.executable, str(scope_validator), "--base-ref", base_revision,
                "--head-ref", revision, "--output", scope_file.name,
            ]
            code, output = run(command, target)
            if code == 0:
                scope = load(Path(scope_file.name))
                record = {
                    "producer": "local change-scope inspection",
                    "status": scope["status"],
                    "evidence": [json.dumps(scope["metrics"], sort_keys=True)],
                }
                if "thresholds" in scope:
                    record["change_scope"] = {
                        "version": 1,
                        "metrics": scope["metrics"],
                        "thresholds": scope["thresholds"],
                    }
            else:
                record = {
                    "producer": "local change-scope inspection",
                    "status": "not_run",
                    "reason": output[-1000:] or "change scope could not be evaluated",
                }
    else:
        record = {
            "producer": "local change-scope inspection",
            "status": "not_run",
            "reason": f"{scope_validator.relative_to(target)} is not installed in this repository",
        }
    results["change-scope"] = {"repository-change-scope": record}
    producers = producer_module()
    for control_id, (_, provider_id, _) in producers.COMMAND_PRODUCERS.items():
        results[control_id] = {
            provider_id: producers.repository_command_result(
                control_id, os.environ, target, revision=revision
            )
        }
    results["custom-static-analysis"] = {
        "semgrep-ce": revision_bound_tool_result(
            producers,
            target,
            revision,
            "Semgrep Community Edition 1.175.0",
            lambda: producers.semgrep_result(target),
        )
    }
    results["secret-detection"] = {
        "gitleaks": revision_bound_tool_result(
            producers,
            target,
            revision,
            "Gitleaks CLI 8.30.1",
            lambda: producers.gitleaks_result(target),
        )
    }
    return {"version": 2, "subject": {"type": "git-commit", "revision": revision}, "results": results}


def validate_fragment_shape(document: dict[str, Any]) -> None:
    if document.get("version") != 2 or not isinstance(document.get("subject"), dict) or not isinstance(document.get("results"), dict):
        raise ValueError("evidence fragment must use the nested v2 evidence contract")


def merge_external_evidence(evidence: dict[str, Any], directory: Path | None) -> list[str]:
    rejected: list[str] = []
    if directory is None or not directory.exists():
        return rejected
    for path in sorted(directory.glob("*.json")):
        fragment = load(path)
        validate_fragment_shape(fragment)
        if fragment["subject"] != evidence["subject"]:
            rejected.append(path.name)
            continue
        for control_id, provider_results in fragment["results"].items():
            if not isinstance(provider_results, dict):
                raise ValueError(f"evidence {control_id} provider results must be an object")
            destination = evidence["results"].setdefault(control_id, {})
            for provider_id, provider_result in provider_results.items():
                existing = destination.get(provider_id)
                if existing is not None and existing != provider_result:
                    raise ValueError(f"conflicting evidence for {control_id}.{provider_id}")
                destination[provider_id] = provider_result
    return rejected


def add_authoritative_placeholders(
    evidence: dict[str, Any],
    selected: dict[str, dict[str, Any]],
    providers: dict[str, dict[str, Any]],
) -> None:
    for control_id, selection in selected.items():
        authority = selection["authoritative"]
        provider_results = evidence["results"].setdefault(control_id, {})
        provider_results.setdefault(authority, {
            "producer": providers[authority]["display_name"],
            "status": "not_run",
            "reason": "The selected authoritative provider did not produce revision-bound evidence for this scan.",
        })


def scan_subject_contract(
    evaluator: Any,
    policy: dict[str, Any],
    profiles: dict[str, Any],
    catalog: dict[str, Any],
    provider_config: dict[str, Any],
    operation: str,
    requested_subject_type: str | None = None,
) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    contracts = {}
    controls: dict[str, dict[str, Any]] = {}
    providers: dict[str, dict[str, Any]] = {}
    for subject_type in ("git-commit", "artifact", "environment"):
        selected, controls, providers = evaluator.effective_controls(
            policy, profiles, catalog, provider_config, operation, subject_type
        )
        if selected:
            contracts[subject_type] = selected
    if requested_subject_type is not None:
        if requested_subject_type not in contracts:
            activated = ", ".join(sorted(contracts)) or "none"
            raise ValueError(
                f"{operation} scan subject {requested_subject_type!r} is not activated by policy; "
                f"activated subjects: {activated}"
            )
        return requested_subject_type, contracts[requested_subject_type], controls, providers
    if len(contracts) > 1:
        subjects = ", ".join(sorted(contracts))
        raise ValueError(
            f"{operation} scan activates mixed evidence subjects ({subjects}); "
            "scan each subject contract separately"
        )
    if contracts:
        subject_type, selected = next(iter(contracts.items()))
        return subject_type, selected, controls, providers
    return "git-commit", {}, controls, providers


def detailed_output(card: dict[str, Any], evidence_path: str, report_path: str) -> str:
    lines = [
        f"Guardrail Scan: {card['status']} — {card['decision'].upper()}",
        f"Subject: {card['subject']['type']}@{card['subject']['revision']}",
        f"Policy: {card['policy']} / {card['operation']}",
    ]
    for control in card["controls"]:
        provider = control["authoritative_provider"]
        provider_name = provider["display_name"] if provider else "Not activated"
        lines.append(f"{control['readiness']} {control['name']} — {provider_name}: {control['evidence_status']}")
    lines.extend([f"Evidence: {evidence_path}", f"Report: {report_path}"])
    return "\n".join(lines) + "\n"


def detailed_markdown(card: dict[str, Any], evidence_path: str) -> str:
    lines = [
        "# Guardrail Scan Report", "", f"- Status: **{card['status']}**",
        f"- Decision: **{card['decision'].upper()}**", f"- Evidence: `{evidence_path}`",
        "", "| Readiness | Mode | Capability — Provider | Evidence |", "| --- | --- | --- | --- |",
    ]
    for control in card["controls"]:
        provider = control["authoritative_provider"]
        provider_name = provider["display_name"] if provider else "Not activated"
        lines.append(f"| {control['readiness']} | {control['effective_mode']} | {control['name']} — {provider_name} | {control['evidence_status']} |")
    return "\n".join(lines) + "\n"


def default_artifact_paths(target: Path, timestamp: datetime) -> tuple[Path, Path, Path]:
    stamp = timestamp.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    directory = target / ".artifacts" / "guardrails"
    return (
        directory / f"evidence-{stamp}.json",
        directory / "evidence.json",
        directory / f"scorecard-{stamp}.md",
    )


def add_artifact_locations(card: dict[str, Any], evidence_path: Path, report_path: Path) -> None:
    card["artifacts"] = {
        "evidence": str(evidence_path),
        "report": str(report_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local Guardrails v2 producers")
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--providers", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--operation", choices=("change", "release"), default="change")
    parser.add_argument("--subject-type", choices=("git-commit", "artifact", "environment"))
    parser.add_argument("--revision", default="")
    parser.add_argument("--base-ref", default="HEAD~1")
    parser.add_argument("--all-catalog-controls", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    target = args.target.resolve()
    timestamp = datetime.now(timezone.utc)
    default_evidence_path, latest_evidence_path, default_report_path = default_artifact_paths(
        target, timestamp
    )

    def resolve(explicit: Path | None, consumer: str, shared: str) -> Path:
        return (target / explicit).resolve() if explicit else default_config_path(target, consumer, shared)

    policy_path = resolve(args.policy, ".guardrails/policy.yaml", "guardrails/baseline.yaml")
    profiles_path = resolve(args.profiles, ".guardrails/profiles.yaml", "policies/profiles.yaml")
    catalog_path = resolve(args.catalog, ".guardrails/control-catalog.yaml", "policies/control-catalog.yaml")
    providers_path = resolve(args.providers, ".guardrails/providers.yaml", "policies/provider-config.yaml")
    evidence_path = (target / args.evidence).resolve() if args.evidence else default_evidence_path
    evidence_dir = (target / args.evidence_dir).resolve() if args.evidence_dir else target / ".artifacts/guardrails/evidence"
    try:
        policy, profiles, catalog, provider_config = map(load, (policy_path, profiles_path, catalog_path, providers_path))
        evaluator = evaluator_module()
        subject_type, selected, controls, provider_definitions = scan_subject_contract(
            evaluator, policy, profiles, catalog, provider_config, args.operation, args.subject_type
        )
        if subject_type == "git-commit":
            revision = args.revision or run(["git", "rev-parse", "HEAD"], target)[1]
            evidence = local_evidence(target, revision, args.base_ref)
        else:
            if not args.revision:
                raise ValueError(f"{subject_type} scans require --revision for the exact evaluated subject")
            revision = args.revision
            evidence = {
                "version": 2,
                "subject": {"type": subject_type, "revision": revision},
                "results": {},
            }
        merge_external_evidence(evidence, evidence_dir)
        add_authoritative_placeholders(evidence, selected, provider_definitions)
        evaluator.validate_evidence(evidence, controls, provider_definitions)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        rendered_evidence = json.dumps(evidence, indent=2) + "\n"
        evidence_path.write_text(rendered_evidence, encoding="utf-8")
        if not args.evidence:
            latest_evidence_path.write_text(rendered_evidence, encoding="utf-8")

        scorecard_path = ROOT / "tooling" / "guardrail_scorecard.py"
        if not scorecard_path.exists():
            scorecard_path = target / ".guardrails" / "scorecard.py"
        command = [
            sys.executable, str(scorecard_path), "--policy", str(policy_path),
            "--profiles", str(profiles_path), "--catalog", str(catalog_path),
            "--providers", str(providers_path), "--evidence", str(evidence_path),
            "--operation", args.operation, "--revision", revision,
            "--subject-type", subject_type, "--json",
        ]
        if args.all_catalog_controls:
            command.append("--all-catalog-controls")
        completed = subprocess.run(command, cwd=target, text=True, capture_output=True)
        card = json.loads(completed.stdout)
        report_path = (target / args.report).resolve() if args.report else default_report_path
        add_artifact_locations(card, evidence_path, report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(detailed_markdown(card, str(evidence_path)), encoding="utf-8")
        print(json.dumps(card, indent=2) + "\n" if args.json else detailed_output(card, str(evidence_path), str(report_path)), end="")
        return completed.returncode
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
