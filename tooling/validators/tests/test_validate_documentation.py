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
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "validate_documentation.py"
SPEC = importlib.util.spec_from_file_location("documentation_validator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

ROOT = Path(__file__).resolve().parents[3]


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def diverged_commits(root: Path) -> tuple[str, str]:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Proof Test")
    git(root, "config", "user.email", "proof@example.invalid")
    (root / "README.md").write_text("initial\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-q", "-m", "initial")
    git(root, "branch", "feature")

    (root / "base-only.py").write_text("base change\n", encoding="utf-8")
    git(root, "add", "base-only.py")
    git(root, "commit", "-q", "-m", "base only")
    base = git(root, "rev-parse", "HEAD")

    git(root, "checkout", "-q", "feature")
    (root / "head-only.py").write_text("head change\n", encoding="utf-8")
    git(root, "add", "head-only.py")
    git(root, "commit", "-q", "-m", "head only")
    return base, git(root, "rev-parse", "HEAD")


class DocumentationValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = MODULE.load_policy(ROOT / ".proof" / "documentation.yaml")

    def test_default_policy_uses_proof_configuration(self) -> None:
        self.assertEqual(
            MODULE.DEFAULT_POLICY,
            MODULE.ROOT / ".proof" / "documentation.yaml",
        )

    def test_current_documentation_links_and_targets_are_valid(self) -> None:
        self.assertEqual(
            MODULE.validate(ROOT, ROOT / ".proof" / "documentation.yaml"),
            [],
        )

    def test_contract_change_requires_mapped_documentation(self) -> None:
        failures = MODULE.validate_changed_files(
            self.policy,
            ["proof/evaluate.py"],
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("control-contract", failures[0])

    def test_contract_change_passes_with_mapped_documentation(self) -> None:
        failures = MODULE.validate_changed_files(
            self.policy,
            ["proof/evaluate.py", "docs/proof/README.md"],
        )
        self.assertEqual(failures, [])

    def test_app_only_change_requires_mapped_documentation(self) -> None:
        policy = {
            "version": 1,
            "mappings": [
                {
                    "name": "application-code",
                    "triggers": ["app.py"],
                    "documents": ["README.md"],
                }
            ],
        }

        failures = MODULE.validate_changed_files(policy, ["app.py"])

        self.assertEqual(len(failures), 1)
        self.assertIn("application-code", failures[0])

    def test_missing_local_markdown_link_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "[missing](docs/missing.md)\n",
                encoding="utf-8",
            )
            failures = MODULE.validate_markdown_links(root)
            self.assertEqual(len(failures), 1)
            self.assertIn("missing link target", failures[0])

    def test_counts_report_files_links_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            (root / "README.md").write_text(
                "[guide](docs/guide.md) [gone](docs/gone.md) [web](https://example.com) [top](#top)\n",
                encoding="utf-8",
            )
            policy = root / "documentation.yaml"
            policy.write_text(
                '{"version": 1, "mappings": [{"name": "app", "triggers": ["src/**"], "documents": ["docs/*.md"]}]}',
                encoding="utf-8",
            )
            counts: dict[str, int] = {}

            failures = MODULE.validate(root, policy, ["src/app.py"], counts)

            self.assertEqual(len(failures), 2)
            self.assertEqual(
                counts,
                {"markdown_files": 2, "links_checked": 2, "broken_links": 1, "mapping_failures": 1},
            )

    def test_main_records_counts_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            argv = ["validate_documentation.py", "--changed-file", "README.md"]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.dict(os.environ, {"PROOF_MEASUREMENTS_FILE": str(output)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(MODULE.main(), 0)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["source"], "pull-request-workflow")
            self.assertEqual(set(document["documentation"]),
                             {"markdown_files", "links_checked", "broken_links", "mapping_failures"})
            self.assertEqual(document["documentation"]["broken_links"], 0)
            unwritable = str(Path(directory) / "missing" / "measurements.json")
            stderr = io.StringIO()
            with mock.patch.dict(os.environ, {"PROOF_MEASUREMENTS_FILE": unwritable}), \
                    contextlib.redirect_stderr(stderr):
                MODULE.record_measurements({"markdown_files": 1})
            self.assertIn("were not recorded", stderr.getvalue())
            with mock.patch.dict(os.environ, {}, clear=True):
                MODULE.record_measurements({"markdown_files": 1})

    def test_changed_files_exclude_base_only_changes_after_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, head = diverged_commits(root)

            changed_files = MODULE.changed_between(root, base, head, None)

            self.assertEqual(changed_files, ["head-only.py"])


if __name__ == "__main__":
    unittest.main()
