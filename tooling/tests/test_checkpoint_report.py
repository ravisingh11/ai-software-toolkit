from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = "tooling" if (ROOT / "tooling/checkpoint_report.py").is_file() else "scripts"
SCRIPT = ROOT / DIRECTORY / "checkpoint_report.py"
SPEC = importlib.util.spec_from_file_location("checkpoint_report_under_test", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
EVALUATOR = ROOT / ("proof/evaluate.py" if DIRECTORY == "tooling" else ".proof/evaluate.py")
SPEC = importlib.util.spec_from_file_location("checkpoint_evaluator", EVALUATOR)
EVALUATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATE)


def card(status="passed", *, revision="tested", supplemental=False):
    directory = ROOT / ("policies" if DIRECTORY == "tooling" else ".proof")
    profiles = json.loads((directory / "profiles.yaml").read_text())
    catalog = json.loads((directory / "control-catalog.yaml").read_text())
    providers = json.loads((directory / ("provider-config.yaml" if DIRECTORY == "tooling" else "providers.yaml")).read_text())
    policy = {"version": 2, "name": "checkpoint-test", "profiles": ["core"],
              "overrides": {"change": {row["id"]: "not_activated" for row in catalog["controls"] if row["stage"] in {"change", "change-and-release"}}, "release": {}}}
    policy["overrides"]["change"]["build"] = "advisory"
    authority = providers["selections"]["build"]["authoritative"]
    results = {}
    if status is not None:
        results[authority] = {"producer": "recorded producer", "status": status}
        if status in {"passed", "failed"}:
            results[authority]["evidence"] = ["https://github.com/owner/repo/actions/runs/123"]
        else:
            results[authority]["reason"] = "credential-missing: prerequisite unavailable"
    if supplemental:
        providers["providers"]["supplemental-build"] = {
            "display_name": "Supplemental Build", "activation": "external", "capabilities": ["build"],
            "checks": {"build": {"check_name": "Supplemental Build", "workflow": "Build", "app_slug": "supplemental-build"}},
            "template": None, "template_available": False, "secrets": [], "enabled_by_default": False,
        }
        providers["selections"]["build"]["supplemental"] = ["supplemental-build"]
        results["supplemental-build"] = {"producer": "helper", "status": "passed", "evidence": ["helper result"]}
    evidence = {"version": 2, "subject": {"type": "git-commit", "revision": revision}, "results": {"build": results} if results else {}}
    return EVALUATE.evaluate(policy, profiles, catalog, providers, evidence, "change", "tested", "git-commit", all_catalog_controls=True)


class CheckpointReportTests(unittest.TestCase):
    def context(self, event="pull_request", action="synchronize"):
        environment = {
            "GITHUB_EVENT_NAME": event, "INVOCATION_ACTION": action,
            "GITHUB_REF": "refs/heads/main" if event == "push" else "refs/pull/7/merge",
            "GITHUB_SHA": "event-sha", "INVOCATION_PR_HEAD": "head-sha" if event == "pull_request" else "",
            "INVOCATION_PR_BASE": "base-sha" if event == "pull_request" else "",
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2", "SECRET_TOKEN": "must-not-appear",
        }
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / ".ignored").write_text("ignored bytes")
            before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            with patch.object(MODULE.subprocess, "check_output", return_value="actual-checkout\n") as git:
                result = MODULE.capture(target, "PR integration checkout", environment)
            git.assert_called_once_with(["git", "-C", str(target), "rev-parse", "HEAD"], text=True)
            self.assertEqual(before, {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()})
        self.assertNotIn("must-not-appear", json.dumps(result))
        return result

    def test_pr_actual_checkout_is_not_event_or_head_revision(self):
        context = self.context()
        self.assertEqual(context["invocation"], "pull_request:synchronize")
        self.assertEqual(context["tested_revision"], "actual-checkout")
        self.assertEqual(context["event_revision"], "event-sha")
        self.assertEqual(context["pr_head"], "head-sha")
        self.assertEqual(context["comparison_base"], "base-sha")
        self.assertEqual(context["scope"], "PR integration checkout")
        self.assertTrue(context["run_url"].endswith("/123/attempts/2"))

    def test_main_is_a_new_observation_with_no_invented_base(self):
        report = MODULE.render_workflow(self.context("push", ""), [])
        self.assertIn("Post-merge/main validation", report)
        self.assertIn("**Comparison base:** not supplied", report)
        self.assertIn("main CI is not deployment verification", report)
        self.assertIn("No workflow outcomes were observed. This is not a pass", report)

    def test_outcomes_are_separate_and_inputs_are_unchanged(self):
        for status, expected in (("passed", "Passed"), ("failed", "Failed"), ("blocked", "Blocked"), ("not_run", "Unverified / not run"), (None, "Unverified / not run")):
            with self.subTest(status=status):
                document = card(status)
                before = copy.deepcopy(document)
                rendered = MODULE.render_card(document)
                self.assertIn(f"### {expected} (1)", rendered)
                self.assertIn("Inactive (32)", rendered)
                self.assertIn("All 33 checks", rendered)
                self.assertIn("advisory: 1/1 passed" if status == "passed" else "advisory: 0/1 passed", rendered)
                self.assertEqual(document, before)

    def test_stale_evidence_is_visible_without_relabeling_original_result(self):
        document = card(revision="previous-revision")
        before = copy.deepcopy(document)
        self.assertEqual(document["decision"], "block")
        rendered = MODULE.render_card(document)
        self.assertIn("Stale evidence (1)", rendered)
        self.assertIn("Original status: missing", rendered)
        self.assertIn("previous-revision", rendered)
        self.assertIn(r"expected\_subject", rendered)
        self.assertEqual(document, before)

    def test_mismatch_on_companion_does_not_taint_other_subject(self):
        document = card()
        document["findings"].append({"kind": "subject_mismatch", "observed_subject": {"type": "pull-request", "revision": "old-metadata"}})
        rendered = MODULE.render_card(document)
        self.assertIn("Passed (1)", rendered)
        self.assertIn("Stale evidence (0)", rendered)

    def test_previously_passing_card_cannot_establish_a_new_checkpoint(self):
        document = card()
        original = copy.deepcopy(document)
        context = self.context("push", "")
        rendered = MODULE.render_workflow(context, [], evaluation=document)
        self.assertIn("Stale evidence (1)", rendered)
        self.assertIn("Original status: passed", rendered)
        self.assertIn("advisory: 1/1 passed", rendered)
        self.assertIn("Results for other commits are historical", rendered)
        self.assertEqual(document, original)
        self.assertEqual(document["decision"], "allow")

    def test_supplemental_success_is_never_an_authoritative_pass(self):
        document = card(None, supplemental=True)
        rendered = MODULE.render_card(document)
        self.assertIn("Passed (0)", rendered)
        self.assertIn("Unverified / not run (1)", rendered)
        self.assertIn("supplemental success is insufficient", rendered)
        self.assertEqual(document["summary"]["advisory"], {"passed": 0, "total": 1})

    def test_other_subject_is_not_misreported_as_deselected(self):
        document = card()
        row = next(row for row in document["controls"] if row["id"] == "pr-metadata")
        row["inactive_reason"] = "other_subject"
        self.assertIn("Evaluated on another subject; inspect that evaluation", MODULE.render_card(document))

    def test_failed_result_has_authority_reason_guide_and_real_evidence_link(self):
        document = card("failed")
        next(row for row in document["controls"] if row["id"] == "build")["authoritative_result"]["reason"] = "Compiler rejected the change"
        rendered = MODULE.render_card(document)
        self.assertIn("repository-build", rendered)
        self.assertIn("Compiler rejected the change", rendered)
        self.assertIn("docs/activation.md#build", rendered)
        self.assertIn("[Open evidence](https://github.com/owner/repo/actions/runs/123)", rendered)

    def test_collector_receipt_links_are_preserved_without_inventing_urls(self):
        document = card("failed")
        row = next(row for row in document["controls"] if row["id"] == "build")
        row["authoritative_result"]["evidence"] = ["check: failed; https://github.com/owner/repo/actions/runs/123", "receipt with no URL"]
        rendered = MODULE.render_card(document)
        self.assertIn("[Open recorded evidence](https://github.com/owner/repo/actions/runs/123)", rendered)
        self.assertIn("receipt with no URL", rendered)

    def test_skills_are_recommended_only_if_installed_and_never_claimed_executed(self):
        document = card("failed")
        self.assertNotIn("Consider installed", MODULE.render_card(document))
        rendered = MODULE.render_card(document, skills={"code-review": ".agents/skills/code-review/SKILL.md"})
        self.assertIn("Consider installed code-review", rendered)
        self.assertIn("recommendation only, not executed", rendered)

    def test_installed_skill_discovery_excludes_symlink_outside_repository(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            target = Path(temporary)
            path = target / ".agents/skills/code-review/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text("skill")
            other = target / ".agents/skills/unrequested"
            other.symlink_to(external, target_is_directory=True)
            (Path(external) / "SKILL.md").write_text("external")
            self.assertEqual(MODULE.installed_skills(target), {"code-review": ".agents/skills/code-review/SKILL.md"})

    def test_failure_masked_by_continue_on_error_is_still_failed(self):
        config = {"steps": [{"id": "test", "name": "Tests", "next_action": "Inspect test log"}]}
        steps = {"test": {"outcome": "failure", "conclusion": "success", "outputs": {"credential": "must-not-appear"}}}
        rows = MODULE.workflow_rows(config, steps)
        self.assertEqual(rows[0]["display_group"], "Failed")
        self.assertEqual(rows[0]["outcome"], "failure")
        self.assertEqual(rows[0]["conclusion"], "success")
        self.assertNotIn("must-not-appear", json.dumps(rows))

    def test_cancelled_skipped_and_missing_never_become_passed(self):
        config = {"steps": [{"id": name, "name": name, "next_action": "Inspect missing work"} for name in ("cancelled", "skipped", "missing")]}
        rows = MODULE.workflow_rows(config, {"cancelled": {"outcome": "cancelled"}, "skipped": {"outcome": "skipped"}})
        self.assertEqual([row["display_group"] for row in rows], ["Blocked", "Unverified / not run", "Unverified / not run"])
        rendered = MODULE.render_workflow(self.context(), rows)
        self.assertIn("runner loss or checkout failure", rendered)
        self.assertIn("current required CI, approvals and conversations separately", rendered)
        self.assertIn("No Proof scorecard was supplied", rendered)
        self.assertNotIn("All listed steps passed", rendered)
        self.assertIn("No result recorded. Inspect preceding failures", rendered)
        self.assertIn("actions/runs/123#artifacts", rendered)

    def test_cancellation_after_successful_steps_is_not_a_successful_run(self):
        rows = MODULE.workflow_rows({"steps": [{"id": "test", "name": "Tests", "next_action": "Inspect tests"}]}, {"test": {"outcome": "success", "conclusion": "success"}})
        rendered = MODULE.render_workflow(self.context(), rows, job_status="cancelled")
        self.assertIn("Job status when reporting: **cancelled**", rendered)
        self.assertIn("Passing individual steps do not establish a successful run", rendered)
        self.assertEqual(rows[0]["outcome"], "success")

    def test_untrusted_markdown_and_unsafe_links_are_not_rendered_as_markup(self):
        document = card("failed")
        row = next(row for row in document["controls"] if row["id"] == "build")
        row["name"] = '<script>alert(1)</script>|`bad`'
        row["authoritative_result"]["evidence"] = ["javascript:alert(1)", "https://example.com/a(b)"]
        rendered = MODULE.render_card(document)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&#124;", rendered)
        self.assertIn("https://example.com/a%28b%29", rendered)
        self.assertNotIn("](javascript:", rendered)

    def test_plain_receipts_cannot_insert_markdown_images_or_links(self):
        document = card("failed")
        row = next(row for row in document["controls"] if row["id"] == "build")
        row["authoritative_result"]["reason"] = "![forged](https://example.test/badge.svg)"
        row["authoritative_result"]["evidence"] = ["[forged result](javascript:alert(1))"]
        rendered = MODULE.render_card(document)
        self.assertIn(r"\!\[forged\]", rendered)
        self.assertNotIn("![forged]", rendered)
        self.assertNotIn("[forged result](javascript:", rendered)

    def test_malformed_evidence_url_retains_the_report_and_receipt(self):
        document = card("failed")
        row = next(row for row in document["controls"] if row["id"] == "build")
        row["authoritative_result"]["evidence"] = ["https://[invalid", "check: failed; https://[invalid"]
        original = copy.deepcopy(document)
        rendered = MODULE.render_card(document)
        self.assertIn("Failed (1)", rendered)
        self.assertIn("link unavailable", rendered)
        self.assertIn(r"https://\[invalid", rendered)
        self.assertEqual(document, original)

    def test_cli_retains_failure_report_and_raw_evaluation_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            context = self.context()
            document = card("failed")
            context["tested_revision"] = "tested"
            for name, payload in (("context", context), ("card", document), ("config", {"steps": [{"id": "test", "name": "Unit tests", "control": "unit-tests", "next_action": "Inspect tests"}]})):
                (directory / (name + ".json")).write_text(json.dumps(payload))
            (directory / ".ignored").write_text("unchanged")
            environment = {**os.environ, "CHECKPOINT_STEPS": json.dumps({"test": {"outcome": "failure", "conclusion": "failure", "outputs": {"secret": "must-not-appear"}}}), "GITHUB_STEP_SUMMARY": str(directory / "summary.md")}
            subprocess.run([sys.executable, str(SCRIPT), "render", "--context", str(directory / "context.json"), "--config", str(directory / "config.json"), "--scorecard", str(directory / "card.json"), "--output-dir", str(directory / "output")], env=environment, check=True, capture_output=True)
            retained = json.loads((directory / "output/report.json").read_text())
            self.assertEqual(retained["evaluation"], document)
            self.assertEqual(json.loads((directory / "card.json").read_text()), document)
            self.assertEqual((directory / ".ignored").read_text(), "unchanged")
            self.assertNotIn("must-not-appear", json.dumps(retained))
            self.assertEqual((directory / "summary.md").read_text(), (directory / "output/report.md").read_text())
            self.assertIn("Failed (1)", (directory / "output/report.md").read_text())

    def test_workflow_wiring_preserves_failure_and_always_attempts_reporting(self):
        name = "distribution-acceptance.yml" if DIRECTORY == "tooling" else "acceptance.yml"
        workflow = (ROOT / ".github/workflows" / name).read_text()
        self.assertIn("always() && steps.checkpoint_context.outcome == 'success'", workflow)
        self.assertIn("CHECKPOINT_STEPS: ${{ toJSON(steps) }}", workflow)
        self.assertIn("CHECKPOINT_JOB_STATUS: ${{ job.status }}", workflow)
        report_step = workflow.split("- name: Summarize SDLC checkpoint", 1)[1].split("- name: Retain SDLC checkpoint report", 1)[0]
        self.assertIn("continue-on-error: true", report_step)
        self.assertNotIn("continue-on-error: true", workflow.split("- name: Summarize SDLC checkpoint", 1)[0])

    def test_renderer_rejects_overwriting_input_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            evidence = directory / "report.json"
            original = json.dumps(card("failed"))
            evidence.write_text(original)
            (directory / "context.json").write_text(json.dumps(self.context()))
            (directory / "config.json").write_text('{"steps": []}')
            result = subprocess.run([sys.executable, str(SCRIPT), "render", "--context", str(directory / "context.json"), "--config", str(directory / "config.json"), "--scorecard", str(evidence), "--output-dir", str(directory)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not overwrite", result.stderr)
            self.assertEqual(evidence.read_text(), original)
            self.assertFalse((directory / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
