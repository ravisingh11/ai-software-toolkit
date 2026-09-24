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

    @unittest.skipUnless(shutil.which("jq"), "workflow policy requires jq")
    def test_workflow_policy_rejects_missing_crashed_and_nonpassing_evidence(self):
        template = (SKILL / "references/github-actions.md").read_text()
        block = template.split("      - name: Apply result policy\n", 1)[1].split("```", 1)[0]
        script = block.split("        run: |\n", 1)[1]
        script = "\n".join(line[10:] for line in script.splitlines())
        results = self.root / "qa-results"
        results.mkdir()
        summary = results / "summary.json"
        valid = {"overall": "pass", "counts": {"pass": 1, "fail": 0, "blocked": 0, "flaky": 0, "inconclusive": 0}}
        cases = [(None, "success", False), ("bad JSON", "success", False),
                 (valid, "failure", False), (valid, "success", True)]
        for overall in ("blocked", "inconclusive", "fail", "unexpected"):
            cases.append(({**valid, "overall": overall}, "success", False))
        for field, value in (("pass", 0), ("fail", 1), ("blocked", 1), ("inconclusive", 1), ("pass", "1"), ("pass", -1), ("pass", 0.5)):
            cases.append(({**valid, "counts": {**valid["counts"], field: value}}, "success", False))
        for payload, outcome, expected in cases:
            with self.subTest(payload=payload, outcome=outcome):
                if payload is None:
                    summary.unlink(missing_ok=True)
                else:
                    summary.write_text(payload if isinstance(payload, str) else json.dumps(payload))
                result = subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=self.root,
                                        env={**os.environ, "QA_EXECUTION_OUTCOME": outcome},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, expected, result.stderr)

    @unittest.skipUnless(shutil.which("jq"), "workflow revision validation requires jq")
    def test_manual_dispatch_requires_current_exact_open_pr_head(self):
        template = (SKILL / "references/github-actions.md").read_text()
        block = template.split("      - name: Resolve and validate the PR revision\n", 1)[1].split("      - uses:", 1)[0]
        script = block.split("        run: |\n", 1)[1]
        script = "\n".join(line[10:] for line in script.splitlines())
        sha = "a" * 40
        fake_gh = 'gh() { printf "%s" "$PR_JSON"; };\n'
        for requested, state, valid in ((sha, "OPEN", True), ("main", "OPEN", False),
                                        ("b" * 40, "OPEN", False), (sha, "CLOSED", False)):
            output = self.root / "outputs"
            output.write_text("")
            env = {**os.environ, "PR_NUMBER": "42", "GITHUB_REPOSITORY": "owner/repo",
                   "REQUESTED_SHA": requested, "GITHUB_OUTPUT": str(output),
                   "PR_JSON": json.dumps({"headRefOid": sha, "baseRefOid": "c" * 40, "state": state})}
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", fake_gh + script],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, valid, result.stderr)
            if valid:
                self.assertIn("head_sha=" + sha, output.read_text())
            else:
                self.assertEqual(output.read_text(), "")

    def test_artifact_validation_creates_missing_directory_and_rejects_links(self):
        template = (SKILL / "references/github-actions.md").read_text()
        block = template.split("      - name: Validate artifact paths\n", 1)[1].split("      #", 1)[0]
        script = block.split("        run: |\n", 1)[1]
        script = "\n".join(line[10:] for line in script.splitlines())
        command = ["bash", "-euo", "pipefail", "-c", script]
        result = subprocess.run(command, cwd=self.root, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.root / "qa-results/report.md").symlink_to(self.skill)
        result = subprocess.run(command, cwd=self.root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.skill.read_text(), self.original)
