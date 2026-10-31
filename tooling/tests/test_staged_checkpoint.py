from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))
import staged_checkpoint as staged  # noqa: E402
import assurance  # noqa: E402


class StagedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "repo"
        self.target.mkdir()
        shutil.copytree(ROOT / ".proof", self.target / ".proof", ignore=shutil.ignore_patterns("__pycache__"))
        self.git("init", "-q")
        (self.target / "app.py").write_text("safe = True\n")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        (self.target / ".gitignore").write_text("private-ignored\n")
        (self.target / "private-ignored").write_text("preserve ignored bytes")
        self.git("add", ".gitignore")
        self.path = self.root / "observations/receipt.json"

    def git(self, *args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", "-c", "maintenance.auto=false", "-c", "gc.auto=0", "-C", str(self.target), *args], text=True).strip()

    def fake_scan(self, identifier, tool, snapshot, output):
        self.assertEqual((snapshot / "app.py").read_text(), "safe = True\n")
        self.assertFalse((snapshot / "private-ignored").exists())
        return {"check": identifier, "provider": tool["provider"], "status": "passed",
                "recorded_execution": {"tool_version": tool["version"], "scope": "staged-filesystem", "exit_code": 0}}

    def test_partial_staging_and_preservation(self):
        before_index = (self.target / ".git/index").read_bytes()
        (self.target / "app.py").write_text("unstaged = True\n")
        with patch.object(staged, "scan", side_effect=self.fake_scan):
            result = staged.run(self.target, self.path)
        self.assertTrue(result["all_reported_checks_passed"])
        self.assertEqual(result["subject"]["type"], "git-index")
        self.assertEqual((self.target / ".git/index").read_bytes(), before_index)
        self.assertEqual((self.target / "app.py").read_text(), "unstaged = True\n")
        self.assertEqual((self.target / "private-ignored").read_text(), "preserve ignored bytes")
        receipt = assurance.read_document(self.path)
        self.assertEqual(receipt["dependencies"]["provider_digest"], staged.provider_digest())
        self.assertFalse(result["authenticated_producer"])

    def test_index_changes_during_scan_invalidate_without_relabeling_pass(self):
        calls = []

        def mutate(identifier, tool, snapshot, output):
            outcome = self.fake_scan(identifier, tool, snapshot, output)
            if not calls:
                (self.target / "app.py").write_text("new_staged = True\n")
                self.git("add", "app.py")
            calls.append(identifier)
            return outcome

        with patch.object(staged, "scan", side_effect=mutate):
            result = staged.run(self.target, self.path)
        self.assertFalse(result["applicable"])
        self.assertFalse(result["all_reported_checks_passed"])
        self.assertTrue(all(row["status"] == "passed" for row in result["results"]))
        self.assertIn("index_tree-mismatch", result["invalidation_reasons"])

    def test_missing_scanners_remain_blocked(self):
        with patch.object(staged.shutil, "which", return_value=None):
            result = staged.run(self.target, self.path)
        self.assertFalse(result["all_reported_checks_passed"])
        self.assertTrue(all(row["status"] == "blocked" for row in result["results"]))

    def test_modified_unstaged_policy_and_receipt_overwrite_reject_before_execution(self):
        (self.target / ".proof/policy.yaml").write_text('{"not":"staged"}')
        with patch.object(staged, "scan") as producer:
            with self.assertRaises(ValueError):
                staged.run(self.target, self.path)
            producer.assert_not_called()
        self.git("checkout", "--", ".proof/policy.yaml")
        self.path.parent.mkdir()
        self.path.write_text("preserve previous observation")
        with patch.object(staged, "scan") as producer:
            with self.assertRaises(ValueError):
                staged.run(self.target, self.path)
            producer.assert_not_called()
        self.assertEqual(self.path.read_text(), "preserve previous observation")

    def test_docker_flags_no_pull_network_or_credentials_and_report_failure(self):
        snapshot = self.root / "snapshot"
        (snapshot / ".proof").mkdir(parents=True)
        (snapshot / ".proof/semgrep-rules.yml").write_text("rules: []")
        output = self.root / "reports"
        output.mkdir()
        captured = []

        def execute(command, cwd, environment):
            captured.append((command, environment))
            (output / "findings.json").write_text('{"results":[{"synthetic":true}],"errors":[]}')
            return 1, "redacted output"

        with patch.dict(os.environ, {"SNYK_TOKEN": "private-sentinel"}), patch.object(staged.shutil, "which", side_effect=lambda name: "/docker" if name == "docker" else None), patch.object(staged, "run_command", side_effect=execute):
            outcome = staged.scan("custom-static-analysis", staged.TOOLS["custom-static-analysis"], snapshot, output)
        self.assertEqual(outcome["status"], "failed")
        command, environment = captured[0]
        self.assertIn("never", command)
        self.assertIn("none", command)
        self.assertIn(str(snapshot) + ":/src:ro", command)
        self.assertNotIn("SNYK_TOKEN", environment)
        self.assertNotIn("private-sentinel", json.dumps(environment))
        self.assertFalse(outcome["recorded_execution"]["raw_findings_retained"])

    def test_malformed_or_incomplete_reports_never_pass(self):
        snapshot, output = self.root / "snapshot", self.root / "reports"
        snapshot.mkdir()
        output.mkdir()
        tool = staged.TOOLS["secret-detection"]
        for body, code in [("bad json", 0), ("[]", 1), ('[{"finding":true}]', 0), ("[]", 125)]:
            with self.subTest(body=body, code=code):
                def execute(command, cwd, environment):
                    (output / "findings.json").write_text(body)
                    return code, ""
                with patch.object(staged.shutil, "which", side_effect=lambda name: "/docker" if name == "docker" else None), patch.object(staged, "run_command", side_effect=execute):
                    self.assertEqual(staged.scan("secret-detection", tool, snapshot, output)["status"], "blocked")

    @unittest.skipUnless(os.environ.get("PROOF_CHECKPOINT_SCANNER_INTEGRATION") == "1", "Pinned scanner integration runs only in explicitly provisioned hosted acceptance")
    def test_pinned_scanners_safe_staged_and_unsafe_unstaged_then_selected_failure(self):
        safe = 'import requests\nrequests.get("https://example.invalid", timeout=3)\n'
        (self.target / "app.py").write_text(safe)
        self.git("add", "app.py")
        bad = 'import requests\nrequests.get("https://example.invalid")\nTOKEN = "' + "ghp_" + hashlib.sha256(b"synthetic-checkpoint-fixture").hexdigest()[:36] + '"\n'
        (self.target / "app.py").write_text(bad)
        docker = shutil.which("docker")
        with patch.object(staged.shutil, "which", side_effect=lambda name: docker if name == "docker" else None):
            passed = staged.run(self.target, self.path)
            self.assertTrue(passed["all_reported_checks_passed"], passed)
            self.git("add", "app.py")
            failed = staged.run(self.target, self.root / "failed/receipt.json")
        self.assertFalse(failed["all_reported_checks_passed"])
        self.assertEqual({row["status"] for row in failed["results"]}, {"failed"})


if __name__ == "__main__":
    unittest.main()
