from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling/doctor.py"


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "The setup diagnostic has not been implemented")
        self.module = load(SCRIPT)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve()
        with contextlib.redirect_stdout(io.StringIO()):
            load(ROOT / "tooling/install.py").install(self.target, dry_run=False)
        (self.target / "README.md").write_text("# Consumer\n")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.git("commit", "--allow-empty", "-qm", "second")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.target, text=True,
                              capture_output=True, check=True).stdout.strip()

    def report(self, **kwargs):
        with patch.dict(os.environ, {}, clear=True):
            return self.module.diagnose(self.target, **kwargs)

    def checks(self, report):
        return {item["id"]: item for item in report["checks"]}

    def test_reports_missing_commands_without_running_configured_commands(self):
        sentinel = self.target / "must-not-exist"
        before = self.git("status", "--porcelain")
        report = self.report(environment={"GUARDRAILS_BUILD_COMMAND": f"touch {sentinel}"})
        rows = self.checks(report)
        self.assertEqual(rows["local.command.build"]["status"], "configured")
        self.assertEqual(rows["local.command.unit-tests"]["status"], "action_needed")
        self.assertIn("GUARDRAILS_UNIT_TEST_COMMAND", rows["local.command.unit-tests"]["next_step"])
        self.assertFalse(sentinel.exists())
        self.assertEqual(before, self.git("status", "--porcelain"))
        self.assertNotIn("touch", json.dumps(report))
        self.assertNotIn("passed", [item["status"] for item in report["checks"]])

    def test_installed_cli_works_without_canonical_checkout_and_does_not_write(self):
        before = self.git("status", "--porcelain")
        result = subprocess.run([sys.executable, str(self.target / ".guardrails/doctor.py"),
                                 "--json"], cwd=self.target, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "setup-diagnostics")
        self.assertEqual(self.checks(report)["runtime"]["status"], "configured")
        self.assertEqual(before, self.git("status", "--porcelain"))
        self.assertFalse((self.target / ".artifacts").exists())

    def test_incomplete_runtime_and_invalid_policy_have_actionable_errors(self):
        (self.target / ".guardrails/scan.py").unlink()
        report = self.report()
        self.assertEqual(self.checks(report)["runtime"]["status"], "action_needed")
        self.assertIn("scan.py", self.checks(report)["runtime"]["message"])
        policy = self.target / ".guardrails/policy.yaml"
        policy.write_text("not-json SECRET-VALUE")
        report = self.report()
        self.assertEqual(self.checks(report)["configuration"]["status"], "action_needed")
        self.assertNotIn("SECRET-VALUE", json.dumps(report))

    def test_doctor_does_not_execute_target_runtime_when_inspecting_another_repo(self):
        (self.target / ".guardrails/evaluate.py").write_text("raise RuntimeError('must not execute')")
        report = self.report()
        self.assertEqual(self.checks(report)["configuration"]["status"], "configured")

    def test_missing_ground_truth_and_escaping_working_directory_are_reported(self):
        (self.target / "README.md").unlink()
        rows = self.checks(self.report(environment={"GUARDRAILS_WORKING_DIRECTORY": ".."}))
        self.assertEqual(rows["ground-truth"]["status"], "action_needed")
        self.assertEqual(rows["local.working-directory"]["status"], "action_needed")
        self.assertEqual(rows["git.clean"]["status"], "action_needed")

    def enable_github(self):
        path = self.target / ".guardrails/policy.yaml"
        policy = json.loads(path.read_text())
        policy["profiles"].append("github")
        path.write_text(json.dumps(policy))

    def github_probe(self, security=None, variables=None, secrets=None):
        original = self.module.probe

        def run(command, target):
            if command[0] != "gh":
                return original(command, target)
            self.assertIn("GET", command)
            self.assertIn("--hostname", command)
            endpoint = command[-1]
            if endpoint.endswith("/variables?per_page=100"):
                return 0, json.dumps(variables or [{"variables": []}])
            if endpoint.endswith("/actions/secrets?per_page=100"):
                return 0, json.dumps(secrets or [{"secrets": []}])
            self.assertEqual(endpoint, "repos/owner/repo")
            return 0, json.dumps({"security_and_analysis": security or {}})
        return run

    def test_github_configured_secret_is_not_proof_of_scanning_or_token_validity(self):
        self.enable_github()
        security = {"secret_scanning": {"status": "enabled"},
                    "secret_scanning_push_protection": {"status": "enabled"}}
        variables = [{"variables": [{"name": "GUARDRAILS_CODEQL_LANGUAGES", "value": "python"}]},
                     {"variables": [{"name": "GUARDRAILS_BUILD_COMMAND", "value": "SECRET-COMMAND"},
                                    {"name": "GUARDRAILS_DEPENDENCY_REVIEW_ENABLED", "value": "true"}]}]
        secrets = [{"secrets": [{"name": "SECURITY_SETTINGS_TOKEN"}]}]
        with patch.object(self.module, "probe", side_effect=self.github_probe(security, variables, secrets)):
            report = self.report(github="owner/repo")
        rows = self.checks(report)
        self.assertEqual(rows["github.secret-protection"]["status"], "configured")
        self.assertEqual(rows["github.secret.SECURITY_SETTINGS_TOKEN"]["status"], "configured")
        self.assertEqual(rows["github.variable.GUARDRAILS_BUILD_COMMAND"]["status"], "configured")
        self.assertEqual(rows["github.variable.GUARDRAILS_DEPENDENCY_REVIEW_ENABLED"]["status"], "configured")
        self.assertNotIn("SECRET-COMMAND", json.dumps(report))
        self.assertEqual(rows["local.command.build"]["status"], "action_needed")
        self.assertEqual(rows["github.producer-evidence"]["status"], "unverified")

    def test_github_unknown_permissions_are_not_disabled_and_disabled_is_actionable(self):
        self.enable_github()
        original = self.module.probe
        for response in ((1, "permission denied SECRET"), (0, "{}"), (0, "not json")):
            with self.subTest(response=response):
                with patch.object(self.module, "probe", side_effect=lambda cmd, target: response if cmd[0] == "gh" else original(cmd, target)):
                    report = self.report(github="owner/repo")
                self.assertEqual(self.checks(report)["github.secret-protection"]["status"], "unverified")
                self.assertNotIn("SECRET", json.dumps(report).replace("SECURITY_SETTINGS_TOKEN", ""))
        with patch.object(self.module, "probe", side_effect=self.github_probe({"secret_scanning": {"status": "disabled"}, "secret_scanning_push_protection": {"status": "enabled"}})):
            rows = self.checks(self.report(github="owner/repo"))
        self.assertEqual(rows["github.secret-protection"]["status"], "action_needed")
        self.assertEqual(rows["github.secret.SECURITY_SETTINGS_TOKEN"]["status"], "unverified")

    def test_local_only_diagnostic_never_calls_github_and_rejects_bad_repository(self):
        original = self.module.probe

        def local(command, target):
            self.assertNotEqual(command[0], "gh")
            return original(command, target)

        with patch.object(self.module, "probe", side_effect=local):
            self.report()
            for invalid in ("../repo", "owner/repo/extra", "https://github.com/owner/repo"):
                with self.assertRaises(ValueError):
                    self.report(github=invalid)

    def test_text_and_json_cli_exit_codes_distinguish_gaps_and_usage_errors(self):
        for arguments, expected in (([], 1), (["--target", str(self.target / "absent")], 2),
                                    (["--github", "bad-input"], 2)):
            completed = subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=self.target,
                                       text=True, capture_output=True)
            self.assertEqual(completed.returncode, expected, completed.stderr)
            if expected == 1:
                self.assertIn("Configuration is not passing evidence", completed.stdout)
                self.assertIn("Next:", completed.stdout)
        policy_path = self.target / ".guardrails/policy.yaml"
        policy = json.loads(policy_path.read_text())
        profiles = json.loads((self.target / ".guardrails/profiles.yaml").read_text())
        policy["overrides"]["change"] = {key: "not_activated" for key in profiles["profiles"]["core"]["defaults"]["change"]}
        policy_path.write_text(json.dumps(policy))
        self.git("add", ".")
        self.git("commit", "-qm", "disable producers")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--json"], cwd=self.target,
                                   text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["summary"]["action_needed"], 0)

    def test_unborn_head_non_repo_and_unsafe_json_path_are_diagnosed(self):
        nested = self.target / "other"
        nested.mkdir()
        self.assertEqual(self.checks(self.module.diagnose(nested))["git.repository"]["status"], "action_needed")
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        rows = self.checks(self.module.diagnose(nested))
        self.assertEqual(rows["git.head"]["status"], "action_needed")
        self.assertEqual(rows["git.base"]["status"], "action_needed")
        with self.assertRaises(ValueError):
            self.module.read_object(self.target, "../escape")
        (self.target / "bad.json").write_text("[]")
        with self.assertRaises(ValueError):
            self.module.read_object(self.target, "bad.json")

    def test_ground_truth_rejects_empty_malformed_and_outside_documents(self):
        path = self.target / ".guardrails/ground-truth-ai.yaml"
        cases = [{"version": 1, "documents": []},
                 {"version": 1, "documents": ["README.md"]},
                 {"version": 1, "documents": [{"path": "../outside"}]},
                 {"version": 1, "documents": [{"path": "/etc/passwd"}]},
                 {"version": 1, "documents": [{"path": "empty.md"}]}]
        (self.target / "empty.md").write_text(" \n")
        for value in cases:
            path.write_text(json.dumps(value))
            self.assertEqual(self.checks(self.report())["ground-truth"]["status"], "action_needed")
        path.write_text("invalid")
        self.assertEqual(self.checks(self.report())["ground-truth"]["status"], "action_needed")

    def test_tools_and_workflow_presence_are_not_running_evidence(self):
        for executable in (None, "/usr/bin/docker"):
            with patch.object(self.module.shutil, "which", return_value=executable):
                rows = self.checks(self.report())
            self.assertEqual(rows["local.tool.semgrep-ce"]["status"], "unverified" if executable else "action_needed")
        (self.target / ".github/workflows/build.yml").unlink()
        self.assertEqual(self.checks(self.report())["workflow.build"]["status"], "unverified")

    def test_probe_timeouts_and_missing_executables_do_not_leak_stderr(self):
        for error in (FileNotFoundError("private detail"), subprocess.TimeoutExpired("git", 20)):
            with patch.object(self.module.subprocess, "run", side_effect=error):
                self.assertEqual(self.module.probe(["git", "status"], self.target), (-1, ""))

    def test_github_malformed_pages_and_disabled_variable_are_not_configured(self):
        self.enable_github()
        for pages in ([], [{}], [{"variables": [None]}], [{"variables": [{"name": "GUARDRAILS_DEPENDENCY_REVIEW_ENABLED", "value": "false"}]}]):
            with patch.object(self.module, "probe", side_effect=self.github_probe(variables=pages)):
                rows = self.checks(self.report(github="owner/repo"))
            self.assertIn(rows["github.variable.GUARDRAILS_DEPENDENCY_REVIEW_ENABLED"]["status"], {"action_needed", "unverified"})

    def test_release_reports_artifact_configuration_not_change_commands(self):
        self.enable_github()
        with patch.object(self.module, "probe", side_effect=self.github_probe()):
            report = self.report(github="owner/repo", operation="release")
        self.assertEqual(report["operation"], "release")
        self.assertIn("github.variable.GUARDRAILS_ARTIFACT_PATH", self.checks(report))

    def test_runtime_only_refresh_installs_diagnostic_without_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer = load(ROOT / "tooling/install.py")
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(target, dry_run=False, no_actions=True)
                (target / ".guardrails/doctor.py").unlink()
                installer.install(target, dry_run=False, no_actions=True, refresh_existing=True)
            self.assertFalse((target / ".github/workflows").exists())
            completed = subprocess.run([sys.executable, str(target / ".guardrails/doctor.py"), "--json"],
                                       cwd=target, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(self.checks(json.loads(completed.stdout))["runtime"]["status"], "configured")

    def test_repository_git_hooks_and_filters_never_execute_during_diagnosis(self):
        sentinel = self.target / "git-command-executed"
        script = self.target / "monitor.sh"
        script.write_text(f"#!/bin/sh\ntouch '{sentinel}'\ncat\n")
        script.chmod(0o755)
        (self.target / ".gitattributes").write_text("*.txt filter=custom\n")
        (self.target / "data.txt").write_text("initial\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.git("config", "core.fsmonitor", str(script))
        self.git("config", "filter.custom.clean", str(script))
        (self.target / "data.txt").write_text("changed\n")
        rows = self.checks(self.report())
        self.assertFalse(sentinel.exists(), "Git invoked a repository-configured command")
        self.assertEqual(rows["git.clean"]["status"], "action_needed")

    def test_invalid_secret_metadata_is_action_needed_not_a_traceback(self):
        path = self.target / ".guardrails/providers.yaml"
        original = json.loads(path.read_text())
        for secrets in (None, "TOKEN", [None], [{"name": "TOKEN"}], [""], ["unsafe\nname"]):
            with self.subTest(secrets=secrets):
                providers = json.loads(json.dumps(original))
                providers["providers"]["repository-build"]["secrets"] = secrets
                path.write_text(json.dumps(providers))
                with patch.object(self.module, "probe", side_effect=self.github_probe()):
                    report = self.report(github="owner/repo")
                self.assertEqual(self.checks(report)["configuration"]["status"], "action_needed")

    def test_submodule_cleanliness_is_unverified_and_git_config_failure_is_actionable(self):
        (self.target / ".gitmodules").write_text("# Submodules are not recursively inspected\n")
        self.git("add", ".")
        self.git("commit", "-qm", "submodule declaration")
        self.assertEqual(self.checks(self.report())["git.clean"]["status"], "unverified")
        original = self.module.probe

        def failed_config(command, target):
            return (2, "") if "--get-regexp" in command else original(command, target)

        with patch.object(self.module, "probe", side_effect=failed_config):
            self.assertEqual(self.checks(self.report())["git.clean"]["status"], "action_needed")

    def test_config_query_execution_failure_never_falls_through_to_status(self):
        original = subprocess.run
        commands = []

        def timeout(command, **kwargs):
            commands.append(command)
            if "--get-regexp" in command:
                raise subprocess.TimeoutExpired(command, 20)
            return original(command, **kwargs)

        with patch.object(self.module.subprocess, "run", side_effect=timeout):
            rows = self.checks(self.report())
        self.assertEqual(rows["git.clean"]["status"], "action_needed")
        self.assertFalse(any("status" in command for command in commands))

    def test_filter_subsection_cannot_inject_a_command_through_git_config_overrides(self):
        sentinel = self.target / "injected-command-executed"
        script = self.target / "filter.sh"
        script.write_text(f"#!/bin/sh\ntouch '{sentinel}'\ncat\n")
        script.chmod(0o755)
        (self.target / ".gitattributes").write_text("*.txt filter=review\n")
        (self.target / "data.txt").write_text("initial\n")
        self.git("add", ".")
        self.git("commit", "-qm", "filter fixture")
        self.git("config", f"filter.review.clean={script};#.clean", "unused")
        (self.target / "data.txt").write_text("changed\n")
        rows = self.checks(self.report())
        self.assertFalse(sentinel.exists(), "A config key was interpreted as an executable value")
        self.assertEqual(rows["git.clean"]["status"], "action_needed")


if __name__ == "__main__":
    unittest.main()
