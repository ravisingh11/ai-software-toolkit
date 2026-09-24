from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = "def total_cents(prices):\n    return sum(prices)\n"
BEHAVIOR_TEST = """import unittest
from app import total_cents


class BasketTests(unittest.TestCase):
    def test_total_cents(self):
        self.assertEqual(total_cents([125, 250, 75]), 450)
        self.assertEqual(total_cents([]), 0)
"""


class ConsumerLifecycleTests(unittest.TestCase):
    """Exercise the installed public CLIs, not imported evaluator helpers."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workspace = Path(temporary.name).resolve()
        self.repo = workspace / "consumer"
        self.repo.mkdir()
        binaries = workspace / "bin"
        binaries.mkdir()
        # Real executables only. Disabled tools must never reach host Docker,
        # Semgrep, Gitleaks, credentials, or the network during this test.
        for name in ("git", "bash"):
            executable = shutil.which(name)
            self.assertIsNotNone(executable, f"{name} is required")
            (binaries / name).symlink_to(executable)
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("GUARDRAILS_", "GIT_"))
            and key not in {"BASH_ENV", "ENV"}
        }
        self.environment.update({
            "PATH": str(binaries),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHON_COLORS": "0",
            "PYTHONPYCACHEPREFIX": str(workspace / "bytecode"),
        })
        python = shlex.quote(sys.executable)
        self.environment.update({
            "GUARDRAILS_BUILD_COMMAND": f"{python} -m py_compile app.py",
            "GUARDRAILS_UNIT_TEST_COMMAND": f"{python} -m unittest -v test_app",
        })
        self.run_command("git", "init", "-q")
        self.run_command("git", "config", "user.name", "Consumer Lifecycle Test")
        self.run_command("git", "config", "user.email", "consumer@example.invalid")
        self.run_command("git", "config", "core.hooksPath", str(workspace / "no-hooks"))
        self.write(".gitignore", ".artifacts/\n__pycache__/\n*.pyc\n")
        self.write("app.py", APP)
        self.write("test_app.py", BEHAVIOR_TEST)
        self.write("README.md", "# Basket\n\nSum integer prices in cents.\n")
        self.write("docs/behavior.md", "# Behavior\n\nAn empty basket totals zero cents.\n")
        self.commit("test: create consumer application")
        self.install()
        self.write(".guardrails/ground-truth-ai.yaml", json.dumps({
            "version": 1,
            "documents": [{"path": "README.md"}, {"path": "docs/behavior.md"}],
        }, indent=2) + "\n")
        self.configure(
            "--set", "build=advisory",
            "--set", "unit-tests=advisory",
            "--set", "repository-ground-truth=enforced",
            "--set", "repository-validation=not_activated",
            "--set", "documentation-validation=not_activated",
            "--set", "change-scope=not_activated",
            "--set", "pr-metadata=not_activated",
            "--set", "format-and-lint=not_activated",
            "--set", "migration-validation=not_activated",
            "--set", "changed-code-coverage=not_activated",
            "--set", "custom-static-analysis=not_activated",
            "--set", "secret-detection=not_activated",
            "--select-provider", "deep-sast=snyk-code",
        )
        self.commit("test: install and configure Core")

    def write(self, relative: str, content: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def run_command(self, *arguments: str, expected: int = 0,
                    environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            arguments, cwd=self.repo,
            env=self.environment if environment is None else environment,
            text=True, capture_output=True, timeout=60,
        )
        self.assertEqual(completed.returncode, expected,
                         f"{arguments}\n{completed.stdout}\n{completed.stderr}")
        return completed

    def install(self, *arguments: str) -> None:
        self.run_command(sys.executable, str(ROOT / "tooling/install.py"),
                         "--target", str(self.repo), "--profile", "core", *arguments)

    def configure(self, *arguments: str) -> None:
        self.run_command(sys.executable, ".guardrails/configure.py", *arguments)

    def commit(self, message: str) -> None:
        # Commits are confined to the disposable consumer, never this worktree.
        self.run_command("git", "add", ".")
        self.run_command("git", "-c", "commit.gpgsign=false", "commit", "-qm", message)
        self.assert_clean()

    def assert_clean(self) -> None:
        self.assertEqual(self.run_command(
            "git", "status", "--porcelain", "--untracked-files=all"
        ).stdout, "")

    def scan(self, status: str, decision: str, *,
             environment: dict[str, str] | None = None) -> tuple[dict, dict]:
        completed = self.run_command(
            sys.executable, ".guardrails/scan.py", "--json",
            expected=0 if decision == "allow" else 1, environment=environment,
        )
        card = json.loads(completed.stdout)
        self.assertEqual((card["status"], card["decision"]), (status, decision), completed.stdout)
        revision = self.run_command("git", "rev-parse", "HEAD").stdout.strip()
        subject = {"type": "git-commit", "revision": revision}
        self.assertEqual(card["subject"], subject)
        evidence_path = Path(card["artifacts"]["evidence"])
        report_path = Path(card["artifacts"]["report"])
        artifact_directory = self.repo / ".artifacts/guardrails"
        self.assertEqual(evidence_path.parent, artifact_directory)
        self.assertEqual(report_path.parent, artifact_directory)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["subject"], subject)
        self.assertEqual(evidence, json.loads(
            (artifact_directory / "evidence.json").read_text(encoding="utf-8")
        ))
        report = report_path.read_text(encoding="utf-8")
        self.assertIn(f"Status: **{status}**", report)
        self.assertIn(f"Decision: **{decision.upper()}**", report)
        self.assertEqual({row["id"] for row in card["controls"]},
                         {"build", "unit-tests", "repository-ground-truth"})
        self.assert_clean()
        return card, evidence

    def assert_command_result(self, card: dict, evidence: dict, control: str,
                              status: str, mode: str, readiness: str) -> dict:
        record = evidence["results"][control][f"repository-{control}"]
        self.assertEqual(record["status"], status)
        row = next(row for row in card["controls"] if row["id"] == control)
        self.assertEqual(row["evidence_status"], "no_result" if status == "not_run" else status)
        self.assertEqual(row["effective_mode"], mode)
        self.assertEqual(row["readiness"], readiness)
        if status != "not_run":
            variable = "GUARDRAILS_BUILD_COMMAND" if control == "build" else "GUARDRAILS_UNIT_TEST_COMMAND"
            digest = hashlib.sha256(self.environment[variable].encode()).hexdigest()
            self.assertIn(f"{control} command digest: sha256:{digest}", record["evidence"])
        return record

    def test_real_failure_is_advisory_then_enforced_and_repair_passes(self) -> None:
        card, evidence = self.scan("GREEN", "allow")
        self.assert_command_result(card, evidence, "build", "passed", "advisory", "GREEN")
        passed = self.assert_command_result(card, evidence, "unit-tests", "passed", "advisory", "GREEN")
        self.assertIn("test_total_cents", "\n".join(passed["evidence"]))
        self.assertIn("OK", "\n".join(passed["evidence"]))

        self.write("app.py", APP.replace("sum(prices)", "sum(prices) + 1"))
        self.commit("test: introduce basket regression")
        card, evidence = self.scan("ORANGE", "allow")
        failed = self.assert_command_result(card, evidence, "unit-tests", "failed", "advisory", "ORANGE")
        self.assertIn("AssertionError: 451 != 450", "\n".join(failed["evidence"]))
        self.assert_command_result(card, evidence, "build", "passed", "advisory", "GREEN")

        self.configure("--set", "unit-tests=enforced")
        self.commit("test: enforce unit tests")
        card, evidence = self.scan("RED", "block")
        enforced = self.assert_command_result(card, evidence, "unit-tests", "failed", "enforced", "RED")
        self.assertEqual(enforced["evidence"][0], failed["evidence"][0])
        self.assertIn("AssertionError: 451 != 450", "\n".join(enforced["evidence"]))

        self.install("--refresh-existing")
        self.assert_clean()
        refreshed_card, refreshed_evidence = self.scan("RED", "block")
        self.assertEqual(self.outcome(refreshed_card), self.outcome(card))
        self.assert_command_result(
            refreshed_card, refreshed_evidence, "unit-tests", "failed", "enforced", "RED"
        )

        self.write("app.py", APP)
        self.commit("test: repair basket regression")
        card, evidence = self.scan("GREEN", "allow")
        self.assert_command_result(card, evidence, "unit-tests", "passed", "enforced", "GREEN")

    def test_absent_command_is_not_run_not_a_pass(self) -> None:
        environment = dict(self.environment)
        del environment["GUARDRAILS_UNIT_TEST_COMMAND"]
        card, evidence = self.scan("ORANGE", "allow", environment=environment)
        missing = self.assert_command_result(card, evidence, "unit-tests", "not_run", "advisory", "ORANGE")
        self.assertIn("GUARDRAILS_UNIT_TEST_COMMAND is not configured", missing["reason"])
        self.assertNotIn("evidence", missing)
        self.assert_command_result(card, evidence, "build", "passed", "advisory", "GREEN")
        self.configure("--set", "unit-tests=enforced")
        self.commit("test: require missing command")
        card, evidence = self.scan("RED", "block", environment=environment)
        self.assert_command_result(card, evidence, "unit-tests", "not_run", "enforced", "RED")

    def test_reinstall_and_refresh_preserve_configuration_outcome_and_cleanliness(self) -> None:
        self.configure("--set", "unit-tests=enforced")
        self.commit("test: preserve consumer enforcement")
        before_card, _ = self.scan("GREEN", "allow")
        preserved = {
            relative: (self.repo / relative).read_bytes()
            for relative in (
                ".guardrails/policy.yaml", ".guardrails/providers.yaml",
                ".guardrails/ground-truth-ai.yaml", "docs/behavior.md", "README.md",
            )
        }
        providers = json.loads(preserved[".guardrails/providers.yaml"])
        self.assertEqual(providers["selections"]["deep-sast"]["authoritative"], "snyk-code")
        for option in ("--merge-existing", "--merge-existing",
                       "--refresh-existing", "--refresh-existing"):
            with self.subTest(option=option):
                self.install(option)
                for relative, content in preserved.items():
                    self.assertEqual((self.repo / relative).read_bytes(), content, relative)
                self.assert_clean()
                card, evidence = self.scan("GREEN", "allow")
                self.assertEqual(
                    self.outcome(card), self.outcome(before_card),
                )
                ground_truth = evidence["results"]["repository-ground-truth"]["repository-validator"]
                self.assertEqual(ground_truth["status"], "passed")
                self.assertIn("2 documents", "\n".join(ground_truth["evidence"]))

    @staticmethod
    def outcome(card: dict) -> dict:
        # Producer output includes unittest wall-clock duration; compare the
        # complete decision and per-control outcomes, not incidental timing.
        return {
            **{key: card[key] for key in (
                "status", "decision", "subject", "enforced", "advisory", "readiness",
            )},
            "controls": [{key: row[key] for key in (
                "id", "effective_mode", "authoritative_provider", "evidence_status", "readiness",
            )} for row in card["controls"]],
        }


if __name__ == "__main__":
    unittest.main()
