from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/qa-bootstrap"
APPLY = runpy.run_path(str(SKILL / "scripts/apply_skill_updates.py"))["apply"]
EMBED = runpy.run_path(str(SKILL / "scripts/embed_evidence.py"))["embed"]
START, END = "<!-- qa:learned:start -->", "<!-- qa:learned:end -->"


class QABootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill = self.root / "skills/qa-web/SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.original = f"Before\n{START}\n{END}\nAfter\n"
        self.skill.write_text(self.original)
        self.updates = self.root / "updates.json"

    def apply(self, updates):
        self.updates.write_text(json.dumps(updates))
        return APPLY(self.updates, self.root, "skills")

    def entry(self, **kwargs):
        return {"file": "skills/qa-web/SKILL.md", "content": "- Wait for the login dialog.", **kwargs}

    def test_learning_preserves_surrounding_content_and_is_idempotent(self):
        self.assertEqual(self.apply([self.entry()]), 1)
        self.assertEqual(self.skill.read_text(), self.original.replace(END, self.entry()["content"] + "\n" + END))
        self.assertEqual(self.apply([self.entry()]), 0)

    def test_learning_rejects_paths_payloads_and_marker_injection(self):
        invalid = [None, self.entry(file="../outside"), self.entry(file="skills/qa-web/SKILL.md\n"),
                   self.entry(file="README.md"), self.entry(content=""), self.entry(content=5),
                   self.entry(content="x" * 2001), self.entry(content=START)]
        self.assertEqual(self.apply(invalid), 0)
        self.assertEqual(self.skill.read_text(), self.original)
        for prefix in ("../skills", "/skills", ""):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                APPLY(self.updates, self.root, prefix)
        with self.assertRaises(ValueError):
            self.apply({"file": "README.md"})

    def test_learning_rejects_file_and_directory_symlinks_even_inside_repo(self):
        target = self.root / "README.md"
        target.write_text(self.original)
        self.skill.unlink()
        self.skill.symlink_to(target)
        self.assertEqual(self.apply([self.entry()]), 0)
        self.assertEqual(target.read_text(), self.original)
        self.skill.unlink()
        self.skill.parent.rmdir()
        self.skill.parent.symlink_to(self.root, target_is_directory=True)
        (self.root / "SKILL.md").write_text(self.original)
        self.assertEqual(self.apply([self.entry()]), 0)
        self.assertEqual((self.root / "SKILL.md").read_text(), self.original)

    def test_learning_rejects_missing_duplicate_and_reversed_blocks(self):
        for body in ("No block", END + START, START + END + END):
            self.skill.write_text(body)
            self.assertEqual(self.apply([self.entry()]), 0)
            self.assertEqual(self.skill.read_text(), body)
        self.skill.unlink()
        self.assertEqual(self.apply([self.entry()]), 0)

    def test_learning_bounds_updates_and_validates_source(self):
        self.assertEqual(APPLY(self.updates, self.root, "skills"), 0)
        updates = [self.entry(content=f"- Distinct entry {n}.") for n in range(21)]
        self.assertEqual(self.apply(updates), 20)
        self.assertNotIn("entry 20", self.skill.read_text())
        self.updates.write_text("invalid JSON")
        with self.assertRaises(ValueError):
            APPLY(self.updates, self.root, "skills")
        self.updates.unlink()
        self.updates.symlink_to(self.skill)
        with self.assertRaises(ValueError):
            APPLY(self.updates, self.root, "skills")

    def test_evidence_embeds_uploads_and_falls_back_to_safe_artifact_names(self):
        report = self.root / "report.md"
        report.write_text("Report\n<!-- evidence:login -->\n<!-- evidence:fallback -->\n<!-- evidence:unknown -->\n")
        (self.root / "uploads.json").write_text(json.dumps({"login": "![login](https://example.com/image.png)"}))
        (self.root / "evidence.json").write_text(json.dumps([
            {"id": "fallback", "file": "dir/a`b.png"}, {"id": []}, None]))
        EMBED(self.root)
        text = report.read_text()
        self.assertIn("![login](https://example.com/image.png)", text)
        self.assertIn("`a_b.png`", text)
        self.assertIn("`unknown`", text)
        self.assertNotIn("<!-- evidence:", text)

    def test_evidence_handles_absent_invalid_and_wrong_shape_metadata(self):
        EMBED(self.root)  # Missing report is harmless.
        for raw in (None, "invalid JSON", '"wrong type"', '{"item": 4}'):
            (self.root / "report.md").write_text("<!-- evidence:item -->")
            if raw is not None:
                (self.root / "evidence.json").write_text(raw)
                (self.root / "uploads.json").write_text(raw)
            EMBED(self.root)
            self.assertIn("job artifacts", (self.root / "report.md").read_text())

    def test_evidence_rejects_symlinks(self):
        report = self.root / "report.md"
        report.symlink_to(self.skill)
        with self.assertRaises(ValueError):
            EMBED(self.root)
        report.unlink()
        report.write_text("<!-- evidence:item -->")
        (self.root / "evidence.json").symlink_to(self.skill)
        with self.assertRaises(ValueError):
            EMBED(self.root)
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            EMBED(alias)
        self.assertEqual(self.skill.read_text(), self.original)

    def test_cli_entrypoints(self):
        self.updates.write_text(json.dumps([self.entry()]))
        result = subprocess.run([sys.executable, str(SKILL / "scripts/apply_skill_updates.py"),
                                 str(self.updates), str(self.root), "skills"],
                                capture_output=True, text=True, check=True)
        self.assertIn("applied 1", result.stdout)
        (self.root / "report.md").write_text("<!-- evidence:item -->")
        subprocess.run([sys.executable, str(SKILL / "scripts/embed_evidence.py"), str(self.root)], check=True)
        self.assertIn("job artifacts", (self.root / "report.md").read_text())

    def shell_step(self, name, workflow=0):
        template = (SKILL / "references/github-actions.md").read_text()
        block = template.split("```yaml\n")[workflow + 1].split("```", 1)[0]
        step = block.split(f"      - name: {name}\n", 1)[1]
        body = step.split("        run: |\n", 1)[1]
        lines = []
        for line in body.splitlines():
            if line and not line.startswith("          "):
                break
            lines.append(line[10:])
        return "\n".join(lines)

    def shell(self, script, **env):
        return subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=self.root,
                              env={**os.environ, **env}, capture_output=True, text=True)

    def passing_summary(self):
        return {"overall": "pass", "counts": {"pass": 1, "fail": 0, "blocked": 0,
                                               "flaky": 0, "inconclusive": 0}}

    @unittest.skipUnless(shutil.which("jq"), "workflow policy requires jq")
    def test_workflow_gate_rejects_missing_skipped_crashed_and_nonpassing_evidence(self):
        script = self.shell_step("Apply result policy")
        results = self.root / "qa-results"
        results.mkdir()
        (results / "report.md").write_text("## QA Report\nPASS: login worked")
        summary = results / "summary.json"
        valid = self.passing_summary()
        cases = [(None, "success", False), ("bad JSON", "success", False),
                 (valid, "failure", False), (valid, "success", True),
                 (valid, "skipped", False), (valid, "cancelled", False), (valid, "", False),
                 (json.dumps(valid) + "\n" + json.dumps(valid), "success", False)]
        for overall in ("blocked", "inconclusive", "fail", "unexpected"):
            cases.append(({**valid, "overall": overall}, "success", False))
        for field, value in (("pass", 0), ("fail", 1), ("blocked", 1), ("inconclusive", 1),
                             ("pass", "1"), ("pass", -1), ("pass", 0.5)):
            cases.append(({**valid, "counts": {**valid["counts"], field: value}}, "success", False))
        for payload, outcome, expected in cases:
            with self.subTest(payload=payload, outcome=outcome):
                if payload is None:
                    summary.unlink(missing_ok=True)
                else:
                    summary.write_text(payload if isinstance(payload, str) else json.dumps(payload))
                result = self.shell(script, QA_EXECUTION_OUTCOME=outcome)
                self.assertEqual(result.returncode == 0, expected, result.stderr)
        summary.write_text(json.dumps(valid))
        (results / "report.md").unlink()
        self.assertNotEqual(self.shell(script, QA_EXECUTION_OUTCOME="success").returncode, 0)

    @unittest.skipUnless(shutil.which("jq"), "workflow revision validation requires jq")
    def test_manual_dispatch_requires_current_exact_open_pr_head(self):
        script = self.shell_step("Resolve and validate the PR revision")
        sha = "a" * 40
        fake_gh = 'gh() { printf "%s" "$PR_JSON"; };\n'
        for requested, state, valid in ((sha, "OPEN", True), ("main", "OPEN", False),
                                        ("b" * 40, "OPEN", False), (sha, "CLOSED", False)):
            output = self.root / "outputs"
            output.write_text("")
            result = self.shell(fake_gh + script, PR_NUMBER="42", GITHUB_REPOSITORY="owner/repo",
                                REQUESTED_SHA=requested, GITHUB_OUTPUT=str(output),
                                PR_JSON=json.dumps({"headRefOid": sha, "baseRefOid": "c" * 40, "state": state}))
            self.assertEqual(result.returncode == 0, valid, result.stderr)
            if valid:
                self.assertIn("head_sha=" + sha, output.read_text())
            else:
                self.assertEqual(output.read_text(), "")

    def test_artifact_validation_creates_missing_directory_and_rejects_links_and_oversize(self):
        for workflow in (0, 1):
            script = self.shell_step("Validate artifact paths", workflow)
            results = self.root / "qa-results"
            if results.exists():
                shutil.rmtree(results)
            result = self.shell(script)
            self.assertEqual(result.returncode, 0, result.stderr)
            (results / "report.md").symlink_to(self.skill)
            self.assertNotEqual(self.shell(script).returncode, 0)
            self.assertEqual(self.skill.read_text(), self.original)
            (results / "report.md").unlink()
            (results / "summary.json").write_text("x" * 65537)
            self.assertNotEqual(self.shell(script).returncode, 0)
            (results / "summary.json").unlink()
            (results / "report.md").write_text("x" * 60001)
            self.assertNotEqual(self.shell(script).returncode, 0)

    def origin_fixture(self):
        repo = {"id": 7, "full_name": "owner/repo"}
        sha = "a" * 40
        run = {"id": 91, "run_attempt": 2, "status": "completed", "conclusion": "success",
               "event": "pull_request", "repository": repo, "head_repository": repo,
               "workflow_id": 9, "path": ".github/workflows/qa.yml", "name": "QA",
               "head_sha": sha, "pull_requests": [{"number": 42}]}
        pr = {"state": "open", "head": {"sha": sha, "repo": repo}, "base": {"repo": repo}}
        jobs = [{"jobs": [{"name": "QA execution", "status": "completed", "conclusion": "success",
                           "steps": [{"name": "Run QA", "conclusion": "success"}]},
                          {"name": "QA / report", "status": "completed", "conclusion": "success"}]}]
        return run, pr, jobs

    def validate_origin(self, run, pr, jobs):
        fake_gh = '''gh() {
          case "$*" in
            *actions/workflows/qa.yml*) printf '%s' '{"id":9}' ;;
            */pulls/42*) printf '%s' "$PR_JSON" ;;
            */jobs*) printf '%s' "$JOBS_JSON" ;;
            */actions/runs/91*) printf '%s' "$RUN_JSON" ;;
            *) return 1 ;;
          esac
        };\n'''
        output = self.root / "outputs"
        output.write_text("")
        result = self.shell(fake_gh + self.shell_step("Validate originating run and current PR", 1),
                            RUN_ID="91", RUN_ATTEMPT="2", GITHUB_REPOSITORY="owner/repo",
                            GITHUB_REPOSITORY_ID="7", GITHUB_OUTPUT=str(output),
                            RUN_JSON=json.dumps(run), PR_JSON=json.dumps(pr), JOBS_JSON=json.dumps(jobs))
        return result, output.read_text()

    @unittest.skipUnless(shutil.which("jq"), "trusted origin validation requires jq")
    def test_trusted_reporter_rejects_wrong_workflow_repository_attempt_and_stale_head(self):
        run, pr, jobs = self.origin_fixture()
        result, output = self.validate_origin(run, pr, jobs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("execution_outcome=success", output)
        changes = {"workflow_id": 10, "path": ".github/workflows/other.yml", "run_attempt": 1,
                   "event": "workflow_dispatch", "status": "in_progress", "name": "Other",
                   "head_repository": {"id": 8, "full_name": "fork/repo"},
                   "repository": {"id": 8, "full_name": "fork/repo"}, "pull_requests": []}
        for key, value in changes.items():
            with self.subTest(field=key):
                result, output = self.validate_origin({**run, key: value}, pr, jobs)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")
        pr["head"]["sha"] = "b" * 40
        self.assertNotEqual(self.validate_origin(run, pr, jobs)[0].returncode, 0)

    @unittest.skipUnless(shutil.which("jq"), "trusted outcome validation requires jq")
    def test_trusted_reporter_requires_run_gate_and_execution_success(self):
        for failed in ("run", "gate", "execution", "step"):
            run, pr, jobs = self.origin_fixture()
            if failed == "run":
                run["conclusion"] = "failure"
            elif failed == "gate":
                jobs[0]["jobs"][1]["conclusion"] = "failure"
            elif failed == "execution":
                jobs[0]["jobs"][0]["conclusion"] = "skipped"
            else:
                jobs[0]["jobs"][0]["steps"][0]["conclusion"] = "failure"
            result, output = self.validate_origin(run, pr, jobs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("execution_outcome=failure", output)

    @unittest.skipUnless(shutil.which("jq"), "artifact provenance validation requires jq")
    def test_trusted_reporter_accepts_only_one_bounded_artifact_from_exact_run(self):
        artifact = {"name": "qa-results-2", "expired": False, "size_in_bytes": 50,
                    "workflow_run": {"id": 91, "repository_id": 7, "head_repository_id": 7,
                                     "head_sha": "a" * 40}}
        cases = [([], True, False), ([artifact], True, True), ([artifact, artifact], False, False),
                 ([{**artifact, "size_in_bytes": 104857601}], False, False),
                 ([{**artifact, "workflow_run": {**artifact["workflow_run"], "id": 92}}], False, False)]
        for artifacts, succeeds, available in cases:
            output = self.root / "outputs"
            output.write_text("")
            result = self.shell('gh() { printf "%s" "$ARTIFACTS_JSON"; };\n' +
                                self.shell_step("Validate run artifact metadata", 1), RUN_ID="91",
                                RUN_ATTEMPT="2", TESTED_SHA="a" * 40, GITHUB_REPOSITORY_ID="7",
                                GITHUB_REPOSITORY="owner/repo", GITHUB_OUTPUT=str(output),
                                ARTIFACTS_JSON=json.dumps([{"artifacts": artifacts}]))
            self.assertEqual(result.returncode == 0, succeeds, result.stderr)
            self.assertEqual("available=true" in output.read_text(), available)

    @unittest.skipUnless(shutil.which("jq"), "report normalization requires jq")
    def test_failed_execution_or_evidence_replaces_optimistic_pass_report(self):
        results = self.root / "qa-results"
        results.mkdir()
        (results / "report.md").write_text("## QA Report\nPASS: everything worked")
        summary = results / "summary.json"
        valid = self.passing_summary()
        script = self.shell_step("Validate result before publishing", 1)
        for outcome, paths, payload, succeeds in (
                ("success", "success", valid, True), ("failure", "success", valid, False),
                ("success", "failure", valid, False), ("success", "success", None, False),
                ("success", "success", "invalid JSON", False),
                ("success", "success", {**valid, "overall": "blocked"}, False)):
            if payload is None:
                summary.unlink(missing_ok=True)
            else:
                summary.write_text(payload if isinstance(payload, str) else json.dumps(payload))
            output = self.root / "outputs"
            output.write_text("")
            result = self.shell(script, QA_EXECUTION_OUTCOME=outcome, ARTIFACT_PATHS_OUTCOME=paths,
                                GITHUB_OUTPUT=str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            normalized = (self.root / "validated-report.md").read_text()
            if succeeds:
                self.assertIn("PASS: everything worked", normalized)
            else:
                self.assertIn("FAILED / INCOMPLETE", normalized)
                self.assertNotIn("PASS", normalized)
            self.assertEqual("validated=true" in output.read_text(), succeeds)

    @unittest.skipUnless(shutil.which("jq"), "current PR check requires jq")
    def test_stale_report_never_writes_a_comment(self):
        fake_gh = 'gh() { printf "%s\\n" "$*" >> calls; printf "%s" "$PR_JSON"; };\n'
        result = self.shell(fake_gh + self.shell_step("Post or update the QA comment", 1),
                            PR_NUMBER="42", TESTED_SHA="a" * 40, GITHUB_REPOSITORY="owner/repo",
                            PR_JSON=json.dumps({"state": "open", "head": {"sha": "b" * 40}}))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "calls").read_text().splitlines(), ["api repos/owner/repo/pulls/42"])

    def test_workflow_trust_boundary_and_always_running_gate(self):
        template = (SKILL / "references/github-actions.md").read_text()
        execution, reporter = [part.split("```", 1)[0] for part in template.split("```yaml\n")[1:]]
        self.assertNotIn(": write", execution)
        self.assertNotIn("QA_EVIDENCE_TOKEN", execution)
        self.assertIn("name: QA / report\n    needs: qa\n    if: always()", execution)
        self.assertIn("workflow_run:", reporter)
        self.assertNotIn("  pull_request:", reporter)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", reporter)
        self.assertNotIn("ref: ${{ steps.origin.outputs.head_sha }}", reporter)
        self.assertLess(reporter.index("Validate result before publishing"), reporter.index("Post or update the QA comment"))
