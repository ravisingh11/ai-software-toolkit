"""Unified reports: what ran, what failed, what remains unverified, what to do next.

Reports are rendered from the evaluator's result card and the scanner's
evidence document. They never change a status; they group and explain it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime import head_revision, load_json

# Capability -> repair skill recommended when its authoritative result is failed.
REPAIR_SKILLS = {
    "build": "fix-ci",
    "unit-tests": "fix-ci",
    "format-and-lint": "fix-ci",
    "migration-validation": "fix-ci",
    "changed-code-coverage": "generate-unit-tests",
    "custom-static-analysis": "fix-security-finding",
    "deep-sast": "fix-security-finding",
    "secret-detection": "fix-security-finding",
    "platform-secret-protection": "fix-security-finding",
    "static-quality": "fix-security-finding",
    "dependency-change-review": "dependency-upgrade",
    "dependency-vulnerability": "dependency-upgrade",
    "dependency-remediation": "dependency-upgrade",
    "license-compliance": "dependency-upgrade",
    "ai-engineering-review": "address-pr-findings",
    "ai-security-review": "address-pr-findings",
    "ai-qa-review": "address-pr-findings",
    "ai-repository-standards-review": "address-pr-findings",
    "functional-qa": "qa",
}

# Existing review skills that apply before a repair skill exists (Stage 3
# implements the repair skills; until then the report points at these).
REVIEW_SKILLS = {
    "fix-ci": "github-actions-hardening, full-test-suite",
    "generate-unit-tests": "test-gap-finder",
    "fix-security-finding": "security-audit-lite",
    "dependency-upgrade": "dependency-risk-review, dependency-remediation",
    "address-pr-findings": "code-review",
    "qa": "qa-bootstrap",
}


def latest_evidence(target: Path) -> dict[str, Any] | None:
    path = target / ".artifacts" / "guardrails" / "evidence.json"
    if not path.is_file():
        return None
    try:
        return load_json(path)
    except ValueError:
        return None


def evidence_binding(target: Path, evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Whether the latest local evidence is bound to the current HEAD."""
    head = head_revision(target)
    subject = evidence.get("subject", {}) if evidence else {}
    revision = subject.get("revision") if isinstance(subject, dict) else None
    return {
        "head": head,
        "evidence_revision": revision,
        "bound": bool(head and revision and head == revision and subject.get("type") == "git-commit"),
    }


def group_controls(card: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {"passed": [], "failed": [], "unverified": [], "not_activated": []}
    for row in card.get("controls", []):
        mode = row.get("effective_mode")
        status = row.get("authoritative_evidence_status", "missing")
        if mode == "not_activated":
            groups["not_activated"].append(row)
        elif status == "passed":
            groups["passed"].append(row)
        elif status == "failed":
            groups["failed"].append(row)
        else:
            groups["unverified"].append(row)
    return groups


def next_action(row: dict[str, Any]) -> str:
    control_id = row.get("id", "")
    status = row.get("authoritative_evidence_status", "missing")
    result = row.get("authoritative_result") or {}
    reason = result.get("reason") or ""
    provider = (row.get("authoritative_provider") or {}).get("display_name", "the authoritative provider")
    if status == "failed":
        skill = REPAIR_SKILLS.get(control_id)
        if skill:
            return f"Run the `{skill}` skill with this finding attached (review skills today: {REVIEW_SKILLS.get(skill, skill)})."
        return f"Investigate the {provider} result and fix the underlying problem."
    if status == "blocked":
        return f"{provider} could not complete: {reason or 'see the evidence'}. Resolve the blocker and rerun."
    if status in {"not_run", "no_result", "missing"}:
        if "clean worktree" in reason:
            return "Commit or stash local changes (and ignore .artifacts/), then rerun check."
        if "not configured" in reason or "unset" in reason:
            return f"Configure the command or credential named in the reason, then rerun: {reason}"
        if not reason:
            return f"No evidence from {provider} for this revision; run the producer (or open a PR) and rerun."
        return f"{provider} produced no result: {reason} Run the producer (or open a PR) and rerun."
    return "No action."


def render_check(card: dict[str, Any], *, evidence_path: str | None = None, report_path: str | None = None) -> str:
    groups = group_controls(card)
    subject = card.get("subject", {})
    lines = [
        f"Toolkit check: {card.get('status', 'UNKNOWN')} / {card.get('decision', 'unknown')} — policy {card.get('policy', '?')}, operation {card.get('operation', '?')}",
        f"Subject: {subject.get('type', '?')} {subject.get('revision', '?')}",
        "",
        f"What ran and passed ({len(groups['passed'])}):",
    ]
    if groups["passed"]:
        lines.extend(f"  PASS  {row['id']} — {(row.get('authoritative_provider') or {}).get('display_name', '?')}" for row in groups["passed"])
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"What failed ({len(groups['failed'])}):")
    if groups["failed"]:
        for row in groups["failed"]:
            lines.append(f"  FAIL  {row['id']} [{row.get('effective_mode')}] — {(row.get('authoritative_provider') or {}).get('display_name', '?')}")
            lines.append(f"        Next: {next_action(row)}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"What remains unverified ({len(groups['unverified'])}):")
    if groups["unverified"]:
        for row in groups["unverified"]:
            lines.append(f"  {row.get('authoritative_evidence_status', 'missing').upper():<9} {row['id']} [{row.get('effective_mode')}]")
            lines.append(f"        Next: {next_action(row)}")
    else:
        lines.append("  (none)")
    if groups["not_activated"]:
        lines.append("")
        lines.append(f"Not activated ({len(groups['not_activated'])}): " + ", ".join(row["id"] for row in groups["not_activated"]))
    for finding in card.get("findings", []):
        if finding.get("kind") == "subject_mismatch":
            lines.append("")
            lines.append("Subject mismatch: " + finding.get("message", ""))
    if evidence_path or report_path:
        lines.append("")
        lines.append(f"Evidence: {evidence_path or '-'}\nScorecard: {report_path or '-'}")
    return "\n".join(lines) + "\n"


def verified_rows(target: Path, doctor_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-capability installed / configured / verified rows from doctor output and evidence.

    ``verified`` means a revision-bound evidence record exists for the current
    HEAD and the authoritative provider returned ``passed`` or ``failed``. Nothing
    is executed here.
    """
    evidence = latest_evidence(target)
    binding = evidence_binding(target, evidence)
    checks = {row["id"]: row for row in doctor_report.get("checks", [])}
    capabilities = sorted({
        identifier.split(".", 2)[-1]
        for identifier in checks
        if identifier.startswith(("local.command.", "producer.", "workflow.", "local.tool."))
        and not identifier.startswith("local.tool.")
    })
    results = evidence.get("results", {}) if evidence and binding["bound"] else {}
    rows = []
    installed = checks.get("runtime", {}).get("status") == "configured"
    for capability in capabilities:
        command = checks.get(f"local.command.{capability}")
        workflow = checks.get(f"workflow.{capability}")
        configured = (command is None or command["status"] == "configured") and (workflow is None or workflow["status"] == "configured")
        provider_results = results.get(capability, {}) if isinstance(results, dict) else {}
        statuses = [row.get("status") for row in provider_results.values() if isinstance(row, dict)]
        observed = next((status for status in statuses if status in {"passed", "failed"}), None)
        state = "verified" if installed and observed else "configured" if installed and configured else "installed" if installed else "missing"
        if state == "verified":
            action = f"Latest evidence for HEAD shows {observed}; keep it current by rerunning check after changes."
        elif state == "configured":
            action = "Run `ai-toolkit check` (or open a PR) to produce revision-bound evidence."
        elif state == "installed":
            gap = command or workflow or {}
            action = gap.get("next_step", "Configure the capability's command, credential, or workflow.")
        else:
            action = "Run `ai-toolkit init` to install the Guardrails runtime."
        rows.append({"capability": capability, "state": state, "observed": observed, "next_step": action})
    return rows


def render_doctor(target: Path, doctor_report: dict[str, Any], rows: list[dict[str, Any]], components: dict[str, dict[str, Any]]) -> str:
    binding = evidence_binding(target, latest_evidence(target))
    lines = ["Toolkit doctor (read-only; nothing was executed)", ""]
    lines.append("Components:")
    for name, row in components.items():
        lines.append(f"  {row['state']:<10} {name}: {row['message']}")
        if row.get("next_step"):
            lines.append(f"             Next: {row['next_step']}")
    lines.append("")
    if binding["bound"]:
        lines.append(f"Evidence: latest local evidence is bound to HEAD {binding['head'][:12]}.")
    elif binding["evidence_revision"]:
        lines.append(f"Evidence: latest local evidence is for {str(binding['evidence_revision'])[:12]}, not HEAD {str(binding['head'] or '?')[:12]}; capabilities cannot be verified from it.")
    else:
        lines.append("Evidence: no local evidence found; run `ai-toolkit check` to produce it.")
    lines.append("")
    lines.append("Capabilities:")
    for row in rows:
        lines.append(f"  {row['state']:<10} {row['capability']}")
        lines.append(f"             Next: {row['next_step']}")
    counts = {state: sum(row["state"] == state for row in rows) for state in ("verified", "configured", "installed", "missing")}
    lines.append("")
    lines.append(" | ".join(f"{state}: {count}" for state, count in counts.items()))
    lines.append("")
    lines.append("Guardrails diagnostics:")
    for row in doctor_report.get("checks", []):
        lines.append(f"  [{row['status'].upper()}] {row['id']}: {row['message']}")
    return "\n".join(lines) + "\n"
