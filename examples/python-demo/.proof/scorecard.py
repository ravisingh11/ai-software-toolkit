#!/usr/bin/env python3
"""Render a provider-aware Proof scorecard."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = ROOT / "proof" / "evaluate.py"
if not EVALUATOR_PATH.exists():
    EVALUATOR_PATH = ROOT / ".proof" / "evaluate.py"

PUBLIC_STATUS = {
    "passed": "passed",
    "failed": "failed",
    "blocked": "blocked",
    "not_run": "no_result",
    "missing": "no_result",
}


def evaluator_module() -> Any:
    spec = importlib.util.spec_from_file_location("proof_evaluator", EVALUATOR_PATH)
    if not spec or not spec.loader:
        raise ValueError(f"cannot load evaluator: {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def percentage(passed: int, total: int) -> float | None:
    return round((passed / total) * 100, 1) if total else None


def normalize_public(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_public(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_public(item) for item in value]
    if value in {"not_run", "missing"}:
        return "no_result"
    return value


def scorecard(
    policy: dict[str, Any],
    profiles: dict[str, Any],
    catalog: dict[str, Any],
    providers: dict[str, Any],
    evidence: dict[str, Any],
    operation: str,
    revision: str,
    *,
    subject_type: str,
    all_catalog_controls: bool = False,
    companions: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    result = evaluator_module().evaluate(
        policy, profiles, catalog, providers, evidence, operation, revision,
        subject_type, all_catalog_controls=all_catalog_controls, companions=companions,
    )
    controls = []
    readiness = {color: 0 for color in ("GREEN", "ORANGE", "GRAY", "RED")}
    for row in result["controls"]:
        public = dict(row)
        public["evidence_status"] = (
            "not_activated"
            if row["effective_mode"] == "not_activated"
            else PUBLIC_STATUS[row["authoritative_evidence_status"]]
        )
        public["supplemental"] = [
            {**item, "status": PUBLIC_STATUS[item["status"]]}
            for item in row["supplemental"]
        ]
        controls.append(public)
        readiness[row["readiness"]] += 1
    findings = []
    for finding in result["findings"]:
        public = dict(finding)
        if finding.get("status") in PUBLIC_STATUS:
            public["status"] = PUBLIC_STATUS[finding["status"]]
        findings.append(public)
    card = {
        "version": 2,
        "status": result["status"],
        "decision": result["decision"],
        "policy": result["policy"],
        "operation": operation,
        "subject": result["subject"],
        "enforced": {**result["summary"]["enforced"], "percent": percentage(**result["summary"]["enforced"])},
        "advisory": {**result["summary"]["advisory"], "percent": percentage(**result["summary"]["advisory"])},
        "readiness": readiness,
        "controls": controls,
        "findings": findings,
    }
    if "companion_subjects" in result:
        card["companion_subjects"] = result["companion_subjects"]
    return normalize_public(card)


def render(card: dict[str, Any]) -> str:
    subject = card["subject"]
    lines = [
        f"Proof Scorecard: {card['status']}",
        f"Decision: {card['decision'].upper()}",
        f"Policy: {card['policy']} ({card['operation']})",
        f"Subject: {subject['type']}@{subject['revision']}",
        *(f"Companion subject: {item['type']}@{item['revision']}" for item in card.get("companion_subjects", [])),
        f"Enforced: {card['enforced']['passed']}/{card['enforced']['total']} passed",
        f"Advisory: {card['advisory']['passed']}/{card['advisory']['total']} passed",
    ]
    for control in card["controls"]:
        provider = control["authoritative_provider"]
        provider_name = provider["display_name"] if provider else "Not activated"
        if control.get("inactive_reason") == "other_subject":
            provider_name = f"Checked separately on the {control['evidence_subject']} subject"
        line = f"  {control['readiness']} {control['name']} — {provider_name}: {control['evidence_status']}"
        if control["supplemental"]:
            details = ", ".join(f"{item['display_name']}={item['status']}" for item in control["supplemental"])
            line += f" (supplemental: {details})"
        lines.append(line)
        if control["readiness"] in {"ORANGE", "RED"}:
            result = control.get("authoritative_result") or {}
            evidence = result.get("evidence")
            reason = result.get("reason")
            if isinstance(evidence, list) and evidence:
                lines.append(f"    evidence: {bounded_summary(evidence[0])}")
            elif isinstance(reason, str) and reason:
                lines.append(f"    reason: {bounded_summary(reason)}")
    for finding in card["findings"]:
        lines.append(f"- {finding.get('mode', finding['kind'])}: {finding['message']}")
    return "\n".join(lines) + "\n"


def bounded_summary(value: str, maximum: int = 240) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= maximum else compact[: maximum - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Proof scorecard")
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--providers", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--operation", required=True, choices=("change", "release"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--subject-type", required=True, choices=("git-commit", "artifact", "environment", "pull-request"))
    parser.add_argument("--all-catalog-controls", action="store_true")
    parser.add_argument(
        "--pull-request-revision",
        help="Also score pull-request-subject controls against this exact pull-request revision",
    )
    parser.add_argument(
        "--pull-request-evidence", type=Path,
        help="Pull-request-subject evidence; omitted means no pull-request result was produced",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.pull_request_evidence and not args.pull_request_revision:
        parser.error("--pull-request-evidence requires --pull-request-revision")
    try:
        companions = None
        if args.pull_request_revision:
            if args.subject_type == "pull-request":
                raise ValueError("--pull-request-revision needs a primary subject other than pull-request")
            pull_request_evidence = (
                load_json_object(args.pull_request_evidence)
                if args.pull_request_evidence
                # No producer result: pull-request controls report no result, never a pass.
                else {"version": 2, "subject": {"type": "pull-request", "revision": args.pull_request_revision}, "results": {}}
            )
            companions = [("pull-request", args.pull_request_revision, pull_request_evidence)]
        card = scorecard(
            load_json_object(args.policy), load_json_object(args.profiles),
            load_json_object(args.catalog), load_json_object(args.providers),
            load_json_object(args.evidence), args.operation, args.revision,
            subject_type=args.subject_type,
            all_catalog_controls=args.all_catalog_controls,
            companions=companions,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(card, indent=2) + "\n" if args.json else render(card), end="")
    return 0 if card["decision"] == "allow" else 1


if __name__ == "__main__":
    raise SystemExit(main())
