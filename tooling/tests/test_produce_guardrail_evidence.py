from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "produce_guardrail_evidence.py"
SPEC = importlib.util.spec_from_file_location("guardrails_v2_producer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

VALIDATOR_SCRIPT = SCRIPT.parent / "validators" / "validate_repository.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "guardrails_v2_contract_validator", VALIDATOR_SCRIPT
)
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)


class RepositoryCommandTests(unittest.TestCase):
    def test_format_and_migration_commands_use_distinct_contracts(self) -> None:
        cases = (
            (
                "format-and-lint",
                "GUARDRAILS_FORMAT_LINT_COMMAND",
                "Repository Format and Lint Command",
            ),
            (
                "migration-validation",
                "GUARDRAILS_MIGRATION_VALIDATION_COMMAND",
                "Repository Migration Validation Command",
            ),
        )
        for control_id, variable, producer in cases:
            with self.subTest(control_id=control_id), tempfile.TemporaryDirectory() as directory:
                missing = MODULE.repository_command_result(
                    control_id, {}, Path(directory), runner=mock.Mock()
                )
                self.assertEqual(missing["status"], "not_run")
                self.assertIn(variable, missing["reason"])

                runner = mock.Mock(return_value=(0, "validated"))
                passed = MODULE.repository_command_result(
                    control_id,
                    {variable: "./tooling/validate"},
                    Path(directory),
                    runner=runner,
                )
                self.assertEqual(passed["producer"], producer)
                self.assertEqual(passed["status"], "passed")
                self.assertIn(f"{control_id} command digest", passed["evidence"][0])

    def test_missing_command_is_not_run(self) -> None:
        result = MODULE.repository_command_result(
            "build", {}, Path("/repo"), runner=mock.Mock()
        )
        self.assertEqual(result["status"], "not_run")
        self.assertIn("GUARDRAILS_BUILD_COMMAND", result["reason"])

    def test_configured_command_reports_bounded_success_and_failure(self) -> None:
        for code, expected in ((0, "passed"), (7, "failed")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                runner = mock.Mock(return_value=(code, "x" * 5000))
                result = MODULE.repository_command_result(
                    "unit-tests",
                    {"GUARDRAILS_UNIT_TEST_COMMAND": "python3 -m unittest"},
                    Path(directory),
                    runner=runner,
                )
                self.assertEqual(result["status"], expected)
                self.assertLessEqual(len(result["evidence"][-1]), 1000)

    def test_command_and_setup_text_never_appear_in_evidence(self) -> None:
        raw_setup = "setup --password super-secret"
        raw_command = "python3 -m unittest --token private-token"
        runner = mock.Mock(side_effect=[(0, "setup ok"), (0, "tests ok")])

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.repository_command_result(
                "unit-tests",
                {
                    "GUARDRAILS_SETUP_COMMAND": raw_setup,
                    "GUARDRAILS_UNIT_TEST_COMMAND": raw_command,
                },
                Path(directory),
                runner=runner,
            )

        serialized = json.dumps(result)
        self.assertNotIn(raw_setup, serialized)
        self.assertNotIn(raw_command, serialized)
        self.assertIn("unit-tests command digest", serialized)

    def test_long_command_setup_version_and_fallback_records_fit_schema(self) -> None:
        long_value = "sensitive-" + "x" * 5000
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            rules = target / ".guardrails" / "semgrep-rules.yml"
            rules.parent.mkdir()
            rules.write_text('{"rules": []}\n')
            cases = (
                MODULE.repository_command_result(
                    "build",
                    {
                        "GUARDRAILS_SETUP_COMMAND": long_value,
                        "GUARDRAILS_BUILD_COMMAND": long_value,
                    },
                    target,
                    runner=mock.Mock(return_value=(9, long_value)),
                ),
                MODULE.repository_command_result(
                    "build",
                    {"GUARDRAILS_BUILD_COMMAND": long_value},
                    target,
                    runner=mock.Mock(return_value=(0, long_value)),
                ),
                MODULE.semgrep_result(
                    target,
                    runner=mock.Mock(return_value=(0, long_value)),
                    which=lambda name: "/usr/bin/semgrep" if name == "semgrep" else None,
                ),
                MODULE.gitleaks_result(
                    target,
                    runner=mock.Mock(side_effect=[(0, "false"), (8, long_value)]),
                    which=lambda name: "/usr/bin/docker" if name == "docker" else None,
                ),
            )
        catalog = {
            "build": {"evidence_subject": "git-commit"},
            "custom-static-analysis": {"evidence_subject": "git-commit"},
            "secret-detection": {"evidence_subject": "git-commit"},
        }
        providers = {
            "repository-build": {"capabilities": ["build"]},
            "semgrep-ce": {"capabilities": ["custom-static-analysis"]},
            "gitleaks": {"capabilities": ["secret-detection"]},
        }
        bindings = (
            ("build", "repository-build"),
            ("build", "repository-build"),
            ("custom-static-analysis", "semgrep-ce"),
            ("secret-detection", "gitleaks"),
        )

        for result, (control_id, provider_id) in zip(cases, bindings):
            with self.subTest(control_id=control_id):
                document = {
                    "version": 2,
                    "subject": {"type": "git-commit", "revision": "abc123"},
                    "results": {control_id: {provider_id: result}},
                }
                try:
                    VALIDATOR.validate_evidence_document(document, catalog, providers)
                except ValueError as error:
                    self.fail(f"emitted evidence did not fit the schema: {error}")
                for record in result.get("evidence", []):
                    self.assertLessEqual(len(record), 1000)
                if "reason" in result:
                    self.assertLessEqual(len(result["reason"]), 1000)
        self.assertTrue(cases[0]["evidence"][0].startswith("setup command digest:"))
        self.assertTrue(cases[1]["evidence"][0].startswith("build command digest:"))
        self.assertTrue(cases[2]["reason"].startswith("Host Semgrep version"))
        self.assertTrue(cases[3]["reason"].startswith("Use Docker"))

    def test_setup_cannot_satisfy_an_unconfigured_capability(self) -> None:
        runner = mock.Mock(return_value=(0, "setup ok"))
        result = MODULE.repository_command_result(
            "build", {"GUARDRAILS_SETUP_COMMAND": "setup"}, Path("/repo"), runner=runner
        )
        self.assertEqual(result["status"], "not_run")
        runner.assert_not_called()

    def test_success_is_not_bound_when_command_mutates_the_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
            tracked = target / "tracked.txt"
            tracked.write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=target, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=target, check=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=target, check=True,
                text=True, capture_output=True,
            ).stdout.strip()

            def mutating_runner(command: list[str], cwd: Path) -> tuple[int, str]:
                tracked.write_text("mutated\n", encoding="utf-8")
                return 0, "command passed"

            result = MODULE.repository_command_result(
                "build",
                {"GUARDRAILS_BUILD_COMMAND": "mutate"},
                target,
                runner=mutating_runner,
                revision=revision,
            )

            self.assertEqual(result["status"], "not_run")
            self.assertIn("changed while", result["reason"])

    def test_setup_cannot_change_tracked_state_before_the_producer_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
            tracked = target / "tracked.txt"
            tracked.write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=target, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=target, check=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=target, check=True,
                text=True, capture_output=True,
            ).stdout.strip()
            runner = mock.Mock()

            def mutate_during_setup(command: list[str], cwd: Path) -> tuple[int, str]:
                tracked.write_text("mutated\n", encoding="utf-8")
                return 0, "setup passed"

            runner.side_effect = mutate_during_setup
            result = MODULE.repository_command_result(
                "build",
                {
                    "GUARDRAILS_SETUP_COMMAND": "setup",
                    "GUARDRAILS_BUILD_COMMAND": "build",
                },
                target,
                runner=runner,
                revision=revision,
            )

            self.assertEqual(result["status"], "not_run")
            self.assertIn("setup", result["reason"].lower())
            self.assertEqual(runner.call_count, 1)


class ToolProducerTests(unittest.TestCase):
    def semgrep_target(self, directory: str) -> Path:
        target = Path(directory)
        rules = target / ".guardrails/semgrep-rules.yml"
        rules.parent.mkdir()
        rules.write_text('{"rules": []}\n')
        return target

    def test_semgrep_prefers_exact_digest_container_and_local_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.semgrep_target(directory)
            runner = mock.Mock(side_effect=[(0, "Docker version 28"), (0, "scan complete")])
            result = MODULE.semgrep_result(target, runner=runner, which=lambda name: f"/usr/bin/{name}")
            command = runner.call_args_list[-1].args[0]
            self.assertEqual(result["status"], "passed")
            self.assertIn(MODULE.SEMGREP_IMAGE, command)
            self.assertIn("scan", command)
            self.assertIn("--error", command)
            self.assertIn(".guardrails/semgrep-rules.yml", command)
            self.assertIn(".guardrails/semgrep-tests/fixtures", command)
            self.assertIn("security/semgrep/tests/fixtures", command)
            self.assertIn("examples/python-demo/.guardrails/semgrep-tests/fixtures", command)
            self.assertNotIn("ci", command)
            self.assertNotIn("auto", command)

    def test_semgrep_host_findings_fail_with_fixture_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self.semgrep_target(directory)
            runner = mock.Mock(side_effect=[(0, "1.175.0"), (1, "finding")])

            result = MODULE.semgrep_result(
                target,
                runner=runner,
                which=lambda name: "/usr/bin/semgrep" if name == "semgrep" else None,
            )

            command = runner.call_args_list[-1].args[0]
            self.assertEqual(result["status"], "failed")
            self.assertIn("--error", command)
            self.assertIn(".guardrails/semgrep-tests/fixtures", command)
            self.assertIn("security/semgrep/tests/fixtures", command)
            self.assertIn("examples/python-demo/.guardrails/semgrep-tests/fixtures", command)

    def test_gitleaks_uses_exact_digest_history_scan_and_redaction(self) -> None:
        runner = mock.Mock(side_effect=[
            (0, "false"), (0, "Docker version 28"), (0, "a" * 40),
            (0, "false\n" + "a" * 40), (0, "1 commits scanned. no leaks"),
        ])
        result = MODULE.gitleaks_result(Path("/repo"), runner=runner, which=lambda name: f"/usr/bin/{name}")
        command = runner.call_args_list[-1].args[0]
        self.assertEqual(result["status"], "passed")
        self.assertEqual(command[-5:], [MODULE.GITLEAKS_IMAGE, "git", "--redact", "--no-banner", "."])

    def test_gitleaks_docker_rejects_missing_shallow_and_mismatched_mounts(self) -> None:
        for mount_result in (
            (128, "fatal: not a git repository"), (0, ""),
            (0, "true\n" + "a" * 40), (0, "false\n" + "b" * 40),
        ):
            with self.subTest(mount_result=mount_result):
                runner = mock.Mock(side_effect=[
                    (0, "false"), (0, "28"), (0, "a" * 40), mount_result,
                ])
                result = MODULE.gitleaks_result(
                    Path("/repo"), runner=runner, which=lambda name: f"/usr/bin/{name}",
                )
                self.assertEqual(result["status"], "not_run")
                self.assertIn("mounted history", result["reason"])
                self.assertEqual(runner.call_count, 4)
                self.assertIn("--entrypoint", runner.call_args.args[0])

    def test_gitleaks_docker_rejects_missing_host_head(self) -> None:
        for host_result in ((128, "missing HEAD"), (0, "")):
            with self.subTest(host_result=host_result):
                runner = mock.Mock(side_effect=[(0, "false"), (0, "28"), host_result])
                result = MODULE.gitleaks_result(
                    Path("/repo"), runner=runner, which=lambda name: f"/usr/bin/{name}",
                )
                self.assertEqual(result["status"], "not_run")
                self.assertEqual(runner.call_count, 3)

    def test_gitleaks_docker_zero_commits_after_valid_mount_cannot_pass(self) -> None:
        runner = mock.Mock(side_effect=[
            (0, "false"), (0, "28"), (0, "a" * 40),
            (0, "false\n" + "a" * 40), (0, "INF 0 commits scanned. INF no leaks found"),
        ])
        result = MODULE.gitleaks_result(
            Path("/repo"), runner=runner, which=lambda name: f"/usr/bin/{name}",
        )
        self.assertEqual(result["status"], "failed")

    def test_gitleaks_zero_exit_without_scanned_history_cannot_pass(self) -> None:
        runner = mock.Mock(side_effect=[
            (0, "false"), (0, "gitleaks version 8.30.1"),
            (0, "ERR fatal: not a git repository\nINF 0 commits scanned.\nINF no leaks found"),
        ])
        result = MODULE.gitleaks_result(
            Path("/repo"), runner=runner,
            which=lambda name: "/usr/bin/gitleaks" if name == "gitleaks" else None,
        )
        self.assertEqual(result["status"], "failed")

    def test_gitleaks_host_binary_keeps_executable_in_argv(self) -> None:
        runner = mock.Mock(side_effect=[(0, "false"), (0, "gitleaks version 8.30.1"), (0, "no leaks")])

        result = MODULE.gitleaks_result(
            Path("/repo"),
            runner=runner,
            which=lambda name: "/usr/bin/gitleaks" if name == "gitleaks" else None,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            runner.call_args_list[-1].args[0],
            ["gitleaks", "git", "--redact", "--no-banner", "."],
        )

    def test_missing_docker_and_wrong_host_versions_are_not_run(self) -> None:
        cases = (("semgrep", MODULE.semgrep_result), ("gitleaks", MODULE.gitleaks_result))
        for binary, producer in cases:
            with self.subTest(binary=binary):
                with tempfile.TemporaryDirectory() as directory:
                    target = self.semgrep_target(directory) if binary == "semgrep" else Path(directory)
                    outputs = [(0, "false"), (0, f"{binary} 0.0.1")] if binary == "gitleaks" else [(0, f"{binary} 0.0.1")]
                    runner = mock.Mock(side_effect=outputs)
                    result = producer(
                        target,
                        runner=runner,
                        which=lambda name: f"/usr/bin/{name}" if name == binary else None,
                    )
                    self.assertEqual(result["status"], "not_run")
                    self.assertIn("version", result["reason"].lower())

    def test_gitleaks_shallow_history_cannot_pass(self) -> None:
        runner = mock.Mock(return_value=(0, "true"))
        result = MODULE.gitleaks_result(
            Path("/repo"), runner=runner, which=lambda name: f"/usr/bin/{name}"
        )
        self.assertEqual(result["status"], "not_run")
        self.assertIn("history", result["reason"].lower())

    def test_written_evidence_uses_nested_v2_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            MODULE.write_evidence(
                path,
                revision="abc123",
                control_id="build",
                provider_id="repository-build",
                result={"producer": "Build", "status": "not_run", "reason": "missing"},
            )
            document = json.loads(path.read_text())
            self.assertEqual(document["version"], 2)
            self.assertEqual(document["subject"], {"type": "git-commit", "revision": "abc123"})
            self.assertEqual(document["results"]["build"]["repository-build"]["status"], "not_run")

    def initialized_repository(self, directory: str) -> tuple[Path, str]:
        target = Path(directory)
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.email", "guardrails@example.invalid"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.name", "Guardrails Test"], cwd=target, check=True)
        (target / "tracked.txt").write_text("clean\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=target, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=target, check=True)
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=target, check=True, text=True, capture_output=True
        ).stdout.strip()
        return target, revision

    def invoke(
        self,
        target: Path,
        revision: str,
        output: Path,
        command: str = "true",
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["GUARDRAILS_BUILD_COMMAND"] = command
        return subprocess.run(
            [
                "python3", str(SCRIPT), "build", "--target", str(target),
                "--revision", revision, "--output", str(output),
            ],
            text=True,
            capture_output=True,
            env=environment,
        )

    def test_cli_rejects_fake_revision_without_writing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target, _ = self.initialized_repository(directory)
            output = target / "evidence.json"
            sentinel = target / "producer-ran"

            completed = self.invoke(target, "0" * 40, output, "touch producer-ran")

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(output.exists())
            self.assertFalse(sentinel.exists())
            self.assertIn("revision", completed.stderr.lower())

    def test_cli_rejects_dirty_worktree_without_writing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target, revision = self.initialized_repository(directory)
            output = Path(directory).parent / f"{Path(directory).name}-evidence.json"
            sentinel = target / "producer-ran"
            (target / "tracked.txt").write_text("dirty\n")

            completed = self.invoke(target, revision, output, "touch producer-ran")

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(output.exists())
            self.assertFalse(sentinel.exists())
            self.assertIn("clean", completed.stderr.lower())

    def test_cli_clean_head_binds_evidence_to_resolved_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target, revision = self.initialized_repository(directory)
            output = Path(directory).parent / f"{Path(directory).name}-clean-evidence.json"

            completed = self.invoke(target, "HEAD", output)

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(output.read_text())["subject"]["revision"], revision)
            output.unlink()


if __name__ == "__main__":
    unittest.main()
