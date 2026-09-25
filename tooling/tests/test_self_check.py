from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SelfCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.outside = Path(self.temporary_directory.name)
        self.repository = self.outside / "repository with spaces"
        (self.repository / "tooling").mkdir(parents=True)
        (self.repository / ".guardrails").mkdir()
        self.launcher = self.repository / "tooling/self-check.sh"
        shutil.copy2(ROOT / "tooling/self-check.sh", self.launcher)
        (self.repository / ".guardrails/scan.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['SCAN_CAPTURE']).write_text(json.dumps({\n"
            "    'cwd': os.getcwd(), 'args': sys.argv[1:],\n"
            "    'env': {k: v for k, v in os.environ.items() if k.startswith('GUARDRAILS_')}\n"
            "}))\n"
            "sys.exit(int(os.environ.get('SCAN_EXIT', '0')))\n"
        )
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Guardrails Test")
        self.git("config", "user.email", "guardrails-test@example.invalid")
        self.git("add", ".")
        self.git("-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                 "commit", "-m", "test: create clean repository")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.capture = self.outside / "scan.json"
        self.environment = os.environ.copy()
        self.environment["SCAN_CAPTURE"] = str(self.capture)

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments], cwd=self.repository, text=True, capture_output=True, check=True
        )

    def launch(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.launcher), *arguments], cwd=self.outside, env=self.environment,
            text=True, capture_output=True,
        )

    def expected_scanner_arguments(self) -> list[str]:
        return [
            "--base-ref", self.base,
            "--policy", ".guardrails/policy.yaml",
            "--profiles", ".guardrails/profiles.yaml",
            "--catalog", ".guardrails/control-catalog.yaml",
            "--providers", ".guardrails/providers.yaml",
        ]

    def test_runs_installed_scanner_from_root_with_real_commands_and_one_base(self) -> None:
        self.environment.update({
            "GUARDRAILS_BUILD_COMMAND": "false",
            "GUARDRAILS_SETUP_COMMAND": "unwanted install",
            "GUARDRAILS_WORKING_DIRECTORY": "elsewhere",
            "GUARDRAILS_COVERAGE_BASE_REF": "wrong-base",
        })
        completed = self.launch()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(captured["cwd"], str(self.repository.resolve()))
        self.assertEqual(captured["args"], self.expected_scanner_arguments())
        self.assertEqual(captured["env"]["GUARDRAILS_COVERAGE_BASE_REF"], self.base)
        expected = {
            "GUARDRAILS_BUILD_COMMAND": "tooling/build.sh",
            "GUARDRAILS_UNIT_TEST_COMMAND": "tooling/test.sh",
            "GUARDRAILS_CHANGED_COVERAGE_COMMAND": "tooling/changed_code_coverage.sh",
            "GUARDRAILS_FORMAT_LINT_COMMAND": "tooling/lint.sh",
            "GUARDRAILS_MIGRATION_VALIDATION_COMMAND":
                "python3 tooling/validators/validate_no_migrations.py",
            "GUARDRAILS_SETUP_COMMAND": "",
            "GUARDRAILS_WORKING_DIRECTORY": ".",
        }
        for key, value in expected.items():
            self.assertEqual(captured["env"][key], value)

    def test_explicit_base_is_resolved_and_scanner_failure_propagates(self) -> None:
        self.environment["SCAN_EXIT"] = "7"
        completed = self.launch("HEAD")
        self.assertEqual(completed.returncode, 7, completed.stderr)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(captured["args"], self.expected_scanner_arguments())
        self.assertEqual(captured["env"]["GUARDRAILS_COVERAGE_BASE_REF"], self.base)

    def test_invalid_arguments_and_base_never_start_scanner(self) -> None:
        for arguments in [("HEAD", "extra"), ("--unexpected",), ("missing-ref",), ("",)]:
            with self.subTest(arguments=arguments):
                completed = self.launch(*arguments)
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse(self.capture.exists())

    def test_dirty_tree_cannot_start_scanner(self) -> None:
        (self.repository / "uncommitted.txt").write_text("not revision-bound\n")
        completed = self.launch()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("clean", completed.stderr)
        self.assertFalse(self.capture.exists())

    def test_help_does_not_start_scanner(self) -> None:
        completed = self.launch("--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("origin/main", completed.stdout)
        self.assertFalse(self.capture.exists())
