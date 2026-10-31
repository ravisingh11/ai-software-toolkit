from __future__ import annotations

import hashlib
import contextlib
import io
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
import checkpoints  # noqa: E402


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

    def test_alternate_commit_index_rejects_without_scanning_default_index(self):
        alternate = self.target / ".git/proposed-index"
        shutil.copyfile(self.target / ".git/index", alternate)
        (self.target / "app.py").write_text("unsafe_in_proposed_commit = True\n")
        environment = {**os.environ, "GIT_INDEX_FILE": str(alternate)}
        subprocess.run(["git", "-C", str(self.target), "add", "app.py"], env=environment, check=True)
        proposed = subprocess.check_output(["git", "-C", str(self.target), "show", ":app.py"], env=environment)
        self.assertNotEqual(proposed, checkpoints.git(self.target, "show", ":app.py", binary=True))
        before = {str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        with patch.dict(os.environ, {"GIT_INDEX_FILE": str(alternate)}), patch.object(staged, "scan") as producer:
            with self.assertRaisesRegex(ValueError, "GIT_INDEX_FILE"):
                staged.run(self.target, self.path)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = checkpoints.main(["run", "--target", str(self.target), "--receipt", str(self.path), "--json"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "blocked")
            self.assertIsNone(checkpoints.plan(self.target, "pre-commit")["subject"])
            producer.assert_not_called()
        self.assertFalse(self.path.parent.exists())
        self.assertEqual({str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}, before)

    def test_subdirectory_target_cannot_certify_only_part_of_pending_commit(self):
        nested = self.target / "component"
        nested.mkdir()
        shutil.copytree(self.target / ".proof", nested / ".proof")
        (nested / "app.py").write_text("safe = True\n")
        self.git("add", "component")
        before = {str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        with patch.object(staged, "scan") as producer:
            with self.assertRaisesRegex(ValueError, "repository root"):
                staged.run(nested, self.path)
            producer.assert_not_called()
        self.assertFalse(self.path.parent.exists())
        self.assertEqual({str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}, before)

    def test_explicit_run_entrypoint_reports_receipt_and_nonpassing_results(self):
        output = io.StringIO()
        with patch.object(staged, "scan", side_effect=self.fake_scan), contextlib.redirect_stdout(output):
            code = checkpoints.main(["run", "--target", str(self.target), "--receipt", str(self.path)])
        self.assertEqual(code, 0)
        self.assertIn("Receipt: " + str(self.path), output.getvalue())
        self.assertIn("No action is authorized", output.getvalue())
        output = io.StringIO()
        blocked = self.root / "blocked/receipt.json"
        with patch.object(staged.shutil, "which", return_value=None), contextlib.redirect_stdout(output):
            code = checkpoints.main(["run", "--target", str(self.target), "--receipt", str(blocked), "--json"])
        self.assertEqual(code, 1)
        value = json.loads(output.getvalue())
        self.assertEqual(value["status_counts"]["blocked"], 2)
        self.assertFalse(value["authorization_granted"])

    def test_unselected_adapters_do_not_execute_or_become_passed(self):
        with patch.object(staged, "plan", return_value={"checks": [{"id": "unit-tests", "selected": True}]}), patch.object(staged, "scan") as scanner:
            result = staged.run(self.target, self.path)
        scanner.assert_not_called()
        self.assertEqual(result["status_counts"]["not_run"], 1)
        self.assertFalse(result["all_reported_checks_passed"])
        self.assertIn("nothing was activated", result["results"][0]["reason"])

    def test_materialization_rejects_unavailable_oversized_and_truncated_git_objects(self):
        oid = "a" * 40
        entry = {"path": "app.py", "mode": "100644", "oid": oid}
        metadata = oid.encode() + b" blob 3\n"
        cases = [[oid.encode() + b" missing\n"],
                 [oid.encode() + b" blob " + str(staged.MAX_SNAPSHOT + 1).encode() + b"\n"],
                 [metadata, b"no header"], [metadata, metadata + b"x"],
                 [metadata, metadata + b"abc\nextra bytes"]]
        for number, responses in enumerate(cases):
            with self.subTest(number=number):
                destination = self.root / ("object-snapshot-" + str(number))
                destination.mkdir()
                with patch.object(staged, "git", side_effect=responses), self.assertRaises(ValueError):
                    staged.materialize(self.target, [entry], destination)

    def test_pinned_host_scanner_checks_version_scope_and_redaction(self):
        snapshot, output = self.root / "host-source", self.root / "host-output"
        snapshot.mkdir(); output.mkdir()
        tool = staged.TOOLS["secret-detection"]
        calls = []

        def execute(command, cwd, environment):
            calls.append((command, environment))
            if command[-1] == "version":
                return 0, tool["version"]
            (output / "findings.json").write_text("[]")
            return 0, ""

        with patch.dict(os.environ, {"GITHUB_TOKEN": "private-sentinel"}), patch.object(staged.shutil, "which", return_value="/pinned-gitleaks"), patch.object(staged, "run_command", side_effect=execute):
            result = staged.scan("secret-detection", tool, snapshot, output)
        self.assertEqual(result["status"], "passed")
        self.assertIn("dir", calls[1][0]); self.assertIn("--redact", calls[1][0])
        self.assertNotIn("GITHUB_TOKEN", calls[1][1])
        self.assertIsNone(result["recorded_execution"]["image"])
        with patch.object(staged.shutil, "which", return_value="/unpinned-gitleaks"), patch.object(staged, "run_command", return_value=(0, "0.0.1")) as command:
            result = staged.scan("secret-detection", tool, snapshot, output)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(command.call_count, 1)
        (output / "findings.json").unlink()
        with patch.object(staged.shutil, "which", return_value="/pinned-gitleaks"), patch.object(staged, "run_command", side_effect=[(0, tool["version"]), (0, "")]):
            result = staged.scan("secret-detection", tool, snapshot, output)
        self.assertEqual(result["status"], "blocked")
        semgrep = staged.TOOLS["custom-static-analysis"]
        with patch.object(staged.shutil, "which", return_value="/pinned-semgrep"), patch.object(staged, "run_command", return_value=(0, semgrep["version"])) as command:
            result = staged.scan("custom-static-analysis", semgrep, snapshot, output)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("rules are absent", result["reason"])
        self.assertEqual(command.call_count, 1)

    def test_command_timeout_and_unavailable_binary_remain_incomplete(self):
        for error in (OSError("unavailable"), subprocess.TimeoutExpired(["fixture-tool"], 180)):
            with self.subTest(error=type(error).__name__), patch.object(staged.subprocess, "run", side_effect=error):
                self.assertEqual(staged.run_command(["fixture-tool"], self.root, {}), (125, ""))

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

    def test_adapter_change_invalidates_original_passes_with_same_tool_pins(self):
        adapter = self.root / "adapter.py"
        adapter.write_bytes(Path(staged.__file__).read_bytes())
        calls = []
        with patch.object(staged, "__file__", str(adapter)):
            original = staged.provider_digest()

            def change_adapter(identifier, tool, snapshot, output):
                outcome = self.fake_scan(identifier, tool, snapshot, output)
                if not calls:
                    adapter.write_bytes(adapter.read_bytes() + b"\n# changed adapter implementation\n")
                calls.append(identifier)
                return outcome

            with patch.object(staged, "scan", side_effect=change_adapter):
                result = staged.run(self.target, self.path)
            self.assertNotEqual(staged.provider_digest(), original)
        self.assertFalse(result["applicable"])
        self.assertIn("provider_digest-mismatch", result["invalidation_reasons"])
        self.assertTrue(all(row["status"] == "passed" for row in result["results"]))
        self.assertEqual(assurance.read_document(self.path)["dependencies"]["provider_digest"], original)

    def test_intent_to_add_rejects_before_producers_or_output(self):
        (self.target / "pending.py").write_text("not staged yet\n")
        self.git("add", "-N", "pending.py")
        before = (self.target / ".git/index").read_bytes()
        with patch.object(staged, "scan") as producer:
            with self.assertRaisesRegex(ValueError, "Intent-to-add"):
                staged.run(self.target, self.path)
            producer.assert_not_called()
        self.assertEqual((self.target / ".git/index").read_bytes(), before)
        self.assertFalse(self.path.parent.exists())

    def test_absent_output_leaf_under_symlink_rejects_before_writes_or_producers(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.target / ".artifacts").symlink_to(outside, target_is_directory=True)
        with patch.object(staged, "scan") as producer:
            with self.assertRaises(ValueError):
                staged.run(self.target)
            producer.assert_not_called()
        self.assertEqual(list(outside.iterdir()), [])
        explicit = self.root / "linked"
        explicit.symlink_to(outside, target_is_directory=True)
        with patch.object(staged, "scan") as producer:
            with self.assertRaises(ValueError):
                staged.run(self.target, explicit / "absent/receipt.json")
            producer.assert_not_called()
        self.assertEqual(list(outside.iterdir()), [])

    def test_public_cli_rejects_symlinked_output_without_writing_through_it(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.target / "linked"
        link.symlink_to(outside, target_is_directory=True)
        before_index = (self.target / ".git/index").read_bytes()
        command = [sys.executable, str(ROOT / "tooling/ai_toolkit"), "checkpoint", "run", "--target", str(self.target),
                   "--receipt", str(link / "absent/receipt.json"), "--json"]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("symlink", json.loads(result.stdout)["error"])
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual((self.target / ".git/index").read_bytes(), before_index)

    def test_mutated_snapshot_blocks_following_producers_and_retains_raw_exit(self):
        def mutate(identifier, tool, snapshot, output):
            outcome = self.fake_scan(identifier, tool, snapshot, output)
            (snapshot / "app.py").chmod(0o644)
            (snapshot / "app.py").write_text("changed by producer\n")
            return outcome
        with patch.object(staged, "scan", side_effect=mutate) as producer:
            result = staged.run(self.target, self.path)
        self.assertFalse(result["all_reported_checks_passed"])
        self.assertTrue(all(row["status"] == "blocked" for row in result["results"]))
        self.assertEqual(producer.call_count, 1)
        receipt = assurance.read_document(self.path)
        evidence = assurance.read_document(self.path.parent / receipt["evidence_refs"][0]["path"])
        self.assertEqual(evidence["execution"]["reported_status"], "passed")
        self.assertFalse(evidence["execution"]["snapshot_unchanged"])

    def test_stdout_capture_is_bounded_for_noisy_child(self):
        code, output = staged.run_command([sys.executable, "-c", "print('x' * 1000000)"], self.root, {})
        self.assertEqual(code, 0)
        self.assertEqual(len(output), 65536)

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
        safe = 'import requests\nrequests.get("https://example.invalid", timeout=3, verify=True)\n'
        (self.target / "app.py").write_text(safe)
        self.git("add", "app.py")
        # Exercise the actual installed TLS rule, not an assumed timeout rule.
        bad = 'import requests\nrequests.get("https://example.invalid", timeout=3, verify=False)\nTOKEN = "' + "ghp_" + hashlib.sha256(b"synthetic-checkpoint-fixture").hexdigest()[:36] + '"\n'
        (self.target / "app.py").write_text(bad)
        docker = shutil.which("docker")
        with patch.object(staged.shutil, "which", side_effect=lambda name: docker if name == "docker" else None):
            passed = staged.run(self.target, self.path)
            self.assertTrue(passed["all_reported_checks_passed"], passed)
            self.git("add", "app.py")
            failed = staged.run(self.target, self.root / "failed/receipt.json")
        self.assertFalse(failed["all_reported_checks_passed"])
        self.assertEqual({row["check"]: row["status"] for row in failed["results"]},
                         {"custom-static-analysis": "failed", "secret-detection": "failed"}, failed)


if __name__ == "__main__":
    unittest.main()
