#!/usr/bin/env python3
"""Read-only SDLC presentation. Never executes producers or evaluates policy.

Workflow-step observations and supplied evaluator output stay separate. The
retained JSON is a presentation record, never a Proof evidence document.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

GUIDE = "https://github.com/ravisingh11/ai-software-toolkit/blob/main/docs/activation.md"
GROUPS = ("Passed", "Failed", "Blocked", "Unverified / not run", "Stale evidence", "Inactive")
SKILL_CAPABILITIES = {
    "fix-ci": ("build", "unit-tests", "format-and-lint", "migration-validation"),
    "generate-unit-tests": ("changed-code-coverage",),
    "fix-security-finding": ("custom-static-analysis", "deep-sast", "secret-detection", "platform-secret-protection", "static-quality"),
    "dependency-upgrade": ("dependency-change-review", "dependency-vulnerability", "dependency-remediation", "license-compliance"),
    "address-pr-findings": ("ai-engineering-review", "ai-security-review", "ai-qa-review", "ai-repository-standards-review"),
    "qa": ("functional-qa",),
}
REPAIR_SKILLS = {capability: skill for skill, capabilities in SKILL_CAPABILITIES.items() for capability in capabilities}
REVIEW_ALTERNATIVES = {
    "fix-ci": "code-review", "generate-unit-tests": "test-gap-finder",
    "fix-security-finding": "security-audit-lite", "dependency-upgrade": "dependency-risk-review",
    "address-pr-findings": "code-review",
}


def text(value: object) -> str:
    return html.escape(str(value), quote=True).replace("|", "&#124;").replace("`", "&#96;").replace("\n", "<br>").replace("\r", "")


def link(label: str, url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or any(ord(c) < 33 for c in url):
        return text(label) + " (link unavailable)"
    return f"[{text(label)}]({quote(url, safe='/:?#=&%+-._~')})"


def installed_skills(target: Path) -> dict[str, str]:
    found = {}
    for directory in (".agents/skills", ".claude/skills"):
        for path in sorted((target / directory).glob("*/SKILL.md")):
            if path.is_file() and path.resolve().is_relative_to(target.resolve()):
                found.setdefault(path.parent.name, path.relative_to(target).as_posix())
    return found


def capture(target: Path, scope: str, environment: dict) -> dict:
    # Only named invocation metadata is captured. Never serialize the environment,
    # GitHub event payload, step outputs, credentials, or command output logs.
    event = environment.get("GITHUB_EVENT_NAME", "unknown")
    action = environment.get("INVOCATION_ACTION", "")
    ref = environment.get("GITHUB_REF", "not supplied")
    checkpoint = "PR review" if event == "pull_request" else "Post-merge/main validation" if event == "push" and ref == "refs/heads/main" else "Explicit verification"
    decision = "Ready for review?" if checkpoint == "PR review" else "Is the resulting main revision healthy?" if checkpoint == "Post-merge/main validation" else "What does this run establish?"
    revision = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
    server = environment.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = environment.get("GITHUB_REPOSITORY", "")
    run_id, attempt = environment.get("GITHUB_RUN_ID", ""), environment.get("GITHUB_RUN_ATTEMPT", "")
    run_url = f"{server}/{repository}/actions/runs/{run_id}/attempts/{attempt}"
    return {
        "checkpoint": checkpoint, "decision": decision, "event": event, "action": action,
        "invocation": event + (":" + action if action else ""), "ref": ref,
        "tested_revision": revision, "event_revision": environment.get("GITHUB_SHA") or None,
        "scope": scope if event == "pull_request" else "Main revision" if checkpoint == "Post-merge/main validation" else "Explicitly selected ref",
        "pr_head": environment.get("INVOCATION_PR_HEAD") or None,
        "comparison_base": environment.get("INVOCATION_PR_BASE") or None,
        "run_url": run_url, "installed_skills": installed_skills(target),
    }


def display_group(row: dict, card: dict) -> str:
    """Describe existing facts; never replace the evaluator's status or score."""
    if row.get("effective_mode") == "not_activated":
        return "Inactive"
    subject_type = row.get("evidence_subject") or card.get("subject", {}).get("type")
    # A mismatch on one companion subject must not taint another subject's rows.
    if any(f.get("kind") == "subject_mismatch" and f.get("observed_subject", {}).get("type") == subject_type
           for f in card.get("findings", [])):
        return "Stale evidence"
    result = row.get("authoritative_result") or {}
    if str(result.get("reason", "")).startswith("revision-mismatch:"):
        return "Stale evidence"
    return {"passed": "Passed", "failed": "Failed", "blocked": "Blocked"}.get(row.get("authoritative_evidence_status"), "Unverified / not run")


def next_step(row: dict, group: str, skills: dict) -> str:
    if group == "Inactive":
        return "Evaluated on another subject; inspect that evaluation." if row.get("inactive_reason") == "other_subject" else "No activation requested. Adopt explicitly if useful."
    if group == "Passed":
        return "Inspect the recorded scope; reassess when its subject or relevant inputs change."
    if group == "Stale evidence":
        return "Obtain authoritative evidence for the expected subject; retain the original result identity."
    if group == "Blocked":
        return "Inspect the producer reason and restore the missing prerequisite before an authorized rerun."
    if group == "Failed":
        skill = REPAIR_SKILLS.get(row.get("id"))
        if skill not in skills:
            skill = REVIEW_ALTERNATIVES.get(skill)
        recommendation = f" Consider installed {skill} ({skills[skill]}); recommendation only, not executed." if skill in skills else ""
        return "Review the authoritative finding and fix its cause before an authorized rerun." + recommendation
    return "Obtain matching evidence from the selected authoritative provider; supplemental success is insufficient."


def render_card(card: dict, *, skills: dict | None = None) -> str:
    skills = skills or {}
    rows = card.get("controls", [])
    lines = ["## Supplied Proof evaluation", "",
             f"Evaluator decision: {text(card.get('decision', 'unknown'))}; status: {text(card.get('status', 'unknown'))}.",
             f"Policy: {text(card.get('policy', 'unknown'))}; operation: {text(card.get('operation', 'unknown'))}.",
             f"Subject: {text(card.get('subject', {}).get('type', 'unknown'))} {text(card.get('subject', {}).get('revision', 'unknown'))}.", "",
             "Original evaluator decision, statuses and scores are preserved. Display groups are explanations, not new policy outcomes.", ""]
    for mode, counts in card.get("summary", {}).items():
        lines.append(f"- {text(mode)}: {text(counts.get('passed', '?'))}/{text(counts.get('total', '?'))} passed.")
    for group in GROUPS:
        members = [row for row in rows if display_group(row, card) == group]
        lines.extend(["", f"### {group} ({len(members)})", ""])
        if not members:
            lines.append("None recorded.")
        for row in members:
            provider = row.get("authoritative_provider") or {}
            result = row.get("authoritative_result") or {}
            identifier = row.get("id", "unknown")
            lines.extend([
                f"- **{text(row.get('name', identifier))}** — authoritative provider: {text(provider.get('display_name', 'not evaluated for this subject' if row.get('inactive_reason') == 'other_subject' else 'not selected'))} ({text(provider.get('id', 'none'))}).",
                f"  Original status: {text(row.get('authoritative_evidence_status', 'missing'))}; mode: {text(row.get('effective_mode', 'unknown'))}.",
                f"  Reason: {text(result.get('reason') or ('Expected and observed subjects differ; inspect subject_mismatch findings.' if group == 'Stale evidence' else 'No additional producer reason recorded.'))}",
                f"  Next: {text(next_step(row, group, skills))}",
                f"  Guide: {link(identifier, GUIDE + '#' + str(identifier))}.",
            ])
            for item in result.get("evidence", []):
                # Preserve receipts and link URLs actually present in them.
                lines.append("  Evidence: " + (link("Open evidence", item) if isinstance(item, str) and item.startswith(("https://", "http://")) else text(item)))
                if isinstance(item, str) and not item.startswith(("https://", "http://")):
                    for url in re.findall(r'https?://[^\s<>"\']+', item):
                        lines.append("  " + link("Open recorded evidence", url.rstrip(".,;")))
    for finding in card.get("findings", []):
        if finding.get("kind") == "subject_mismatch":
            lines.extend(["", "Subject mismatch: " + text(json.dumps(finding, sort_keys=True))])
    lines.extend(["", link("All 33 checks and activation guidance", GUIDE),
                  "Only selected, applicable checks affect the existing evaluation. Inactive includes checks on other subjects when identified by the evaluator.",
                  "An allow decision grants no authority to merge, release or deploy."])
    return "\n".join(lines) + "\n"


def workflow_rows(config: dict, steps: dict) -> list[dict]:
    rows = []
    for definition in config["steps"]:
        observation = steps.get(definition["id"], {})
        # Outcome is the actual result, even if continue-on-error changed conclusion.
        outcome = observation.get("outcome") or "not_observed"
        rows.append({**definition, "outcome": outcome, "conclusion": observation.get("conclusion") or "not_observed",
                     "display_group": {"success": "Passed", "failure": "Failed", "cancelled": "Blocked"}.get(outcome, "Unverified / not run")})
    return rows


def render_workflow(context: dict, rows: list[dict], *, evaluation: dict | None = None) -> str:
    lines = ["# SDLC checkpoint report", ""]
    for key, label in (("checkpoint", "Checkpoint"), ("decision", "Decision considered"), ("invocation", "Hook / invocation"),
                       ("scope", "Evidence scope"), ("tested_revision", "Tested revision"), ("event_revision", "Event revision"),
                       ("pr_head", "PR head"), ("comparison_base", "Comparison base"), ("ref", "Git ref")):
        lines.append(f"- **{label}:** {text(context.get(key) or 'not supplied')}")
    lines.extend(["- " + link("Run and step logs", context["run_url"]),
                  "- " + link("Retained artifacts (availability/retention depends on GitHub)", context["run_url"].split("/attempts/")[0] + "#artifacts"), "",
                  "## This workflow's observations", "",
                  "These are workflow-step outcomes, **not authoritative Proof evidence or a full toolkit score**. Checks in other workflows are not assessed here.", "",
                  "| Check / activity | Outcome | Recorded outcome / conclusion | Next action |",
                  "| --- | --- | --- | --- |"])
    for row in rows:
        action = "Inspect the recorded scope; no repair indicated by this step." if row["display_group"] == "Passed" else row["next_action"]
        if row["display_group"] == "Unverified / not run":
            action = "No result recorded. Inspect preceding failures or prerequisites before authorizing this step."
        elif row["display_group"] == "Blocked":
            action = "Execution was interrupted. Inspect the run cancellation and prerequisites before an authorized rerun."
        if row["display_group"] == "Failed" and row.get("control"):
            skill = REPAIR_SKILLS.get(row["control"])
            skills = context.get("installed_skills", {})
            if skill not in skills:
                skill = REVIEW_ALTERNATIVES.get(skill)
            if skill in skills:
                action += f" Consider installed {skill} ({skills[skill]}); recommendation only, not executed."
        lines.append(f"| {text(row['name'])} ({link('logs', context['run_url'])}) | {row['display_group']} | {text(row['outcome'])} / {text(row['conclusion'])} | {text(action)} |")
    lines.extend(["", "Provider: this workflow's named steps; authoritative Proof provider status is not inferred."])
    lines.append("A failed step's detailed reason is in its log. Skipped or unobserved steps supply no result; cancelled steps were interrupted. This report does not guess a root cause.")
    guides = sorted({row["control"] for row in rows if row.get("control")})
    if guides:
        lines.append("Activation guides: " + ", ".join(link(identifier, GUIDE + '#' + identifier) for identifier in guides) + ".")
    if not rows:
        lines.append("No workflow outcomes were observed. This is not a pass.")
    if evaluation is not None:
        lines.extend(["", render_card(evaluation, skills=context.get("installed_skills", {}))])
    else:
        lines.extend(["", "No Proof scorecard was supplied. Selected-check failures, blockers, stale results and inactive checks in other workflows remain unassessed here.",
                      link("Inspect the separate Proof Scorecard runs", context["run_url"].split("/actions/runs/")[0] + "/actions/workflows/proof-scorecard.yml")])
    lines.extend(["", "## What happens next?", ""])
    failed = [row["name"] for row in rows if row["display_group"] == "Failed"]
    unavailable = [row["name"] for row in rows if row["display_group"] in {"Blocked", "Unverified / not run"}]
    if failed:
        lines.append("Resolve recorded failures: " + ", ".join(text(name) for name in failed) + ".")
    if unavailable:
        lines.append("Obtain results after resolving prerequisites: " + ", ".join(text(name) for name in unavailable) + ".")
    if rows and not failed and not unavailable:
        lines.append("All listed steps passed; this statement applies only to these observations.")
    if context["checkpoint"] == "PR review":
        lines.append("Review findings and check current required CI, approvals and conversations separately. This report neither checks all merge requirements nor authorizes a merge.")
    else:
        lines.append("Retain these results for the tested revision. Release, artifact verification, deployment approval and live health require their own evidence; main CI is not deployment verification.")
    lines.extend(["", "Cancellation, runner loss or checkout failure can prevent final reporting/artifact upload. Use GitHub's run conclusion and logs when artifacts are unavailable; absence is not a pass.",
                  link("All 33 checks", GUIDE),
                  "Checks remain optional; Core advisory; lifecycle/polyglot manual. No producer, repair skill, activation or enforcement is executed by this renderer."])
    return "\n".join(lines) + "\n"


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initial = commands.add_parser("capture")
    initial.add_argument("--target", type=Path, default=Path.cwd())
    initial.add_argument("--scope", required=True, choices=("PR head", "PR integration checkout"))
    initial.add_argument("--output", type=Path, required=True)
    final = commands.add_parser("render")
    final.add_argument("--context", type=Path, required=True)
    final.add_argument("--config", type=Path, required=True)
    final.add_argument("--scorecard", type=Path)
    final.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(capture(args.target, args.scope, os.environ), indent=2) + "\n", encoding="utf-8")
        return
    context, config = read_object(args.context), read_object(args.config)
    observations = json.loads(os.environ.get("CHECKPOINT_STEPS", "{}"))
    if not isinstance(observations, dict):
        raise ValueError("CHECKPOINT_STEPS must contain an object")
    rows = workflow_rows(config, observations)
    evaluation = read_object(args.scorecard) if args.scorecard else None
    rendered = render_workflow(context, rows, evaluation=evaluation)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Retain only whitelisted step facts; step outputs may contain sensitive data.
    document = {"kind": "checkpoint-presentation", "context": context, "workflow_observations": rows, "evaluation": evaluation}
    (args.output_dir / "report.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "report.md").write_text(rendered, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(rendered)
    print(rendered)


if __name__ == "__main__":
    main()
