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


class TrackedDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.policy = {"version": 1, "mappings": [{"name": "api", "triggers": ["src/**"], "documents": ["docs/api.md"]}]}
        (self.root / "docs").mkdir()
        (self.root / "docs/api.md").write_text("# API\n")
        (self.root / "README.md").write_text("[API](docs/api.md)\n")

    def test_git_inventory_ignores_untracked_dependencies_but_checks_tracked_docs(self):
        git(self.root, "init", "-q")
        git(self.root, "add", "README.md", "docs")
        for name in ("node_modules", ".artifacts", "dist"):
            (self.root / name).mkdir()
            (self.root / name / "broken.md").write_text("[bad](missing.md)\n")
        self.assertEqual(MODULE.validate_markdown_links(self.root), [])
        self.assertEqual(MODULE.validate_document_targets(self.root, self.policy), [])
        (self.root / "docs/api.md").write_text("[broken](gone.md)\n")
        self.assertIn("missing link target", MODULE.validate_markdown_links(self.root)[0])
        self.assertEqual(len(MODULE.validate_changed_files(self.policy, ["src/api.py"])), 1)
        self.assertEqual(MODULE.validate_changed_files(self.policy, ["src/api.py", "docs/api.md"]), [])

    def test_untracked_document_cannot_satisfy_mapping_and_nested_root_is_scoped(self):
        git(self.root, "init", "-q")
        git(self.root, "add", "README.md")
        self.assertTrue(MODULE.validate_document_targets(self.root, self.policy))
        git(self.root, "add", "docs/api.md")
        self.assertEqual([p.name for p in MODULE.markdown_files(self.root / "docs")], ["api.md"])

    def test_snapshot_fallback_excludes_output_and_is_deterministic(self):
        for name in ("node_modules", "vendor", ".venv", "build", "generated", ".artifacts"):
            path = self.root / name
            path.mkdir()
            (path / "bad.md").write_text("[bad](absent.md)\n")
        self.assertEqual(MODULE.validate_markdown_links(self.root), [])
        self.assertEqual(MODULE.validate_document_targets(self.root, self.policy), [])
        self.assertEqual(MODULE.repository_files(self.root), sorted(MODULE.repository_files(self.root)))
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            MODULE.changed_between(self.root, "missing", "HEAD", None)

    def test_unavailable_git_inventory_and_symlink_escape_fail_closed(self):
        git(self.root, "init", "-q")
        with mock.patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 128, "", "")):
            with self.assertRaises(ValueError):
                MODULE.repository_files(self.root)
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "outside.md"
            secret.write_text("private")
            (self.root / "escape.md").symlink_to(secret)
            git(self.root, "add", "escape.md")
            with self.assertRaisesRegex(ValueError, "escapes"):
                MODULE.markdown_files(self.root)

    def test_missing_policy_or_comparison_baseline_is_not_a_pass(self):
        with self.assertRaises(OSError):
            MODULE.validate(self.root, self.root / "missing-policy.yaml")
        git(self.root, "init", "-q")
        with self.assertRaises(subprocess.CalledProcessError):
            MODULE.changed_between(self.root, "missing", "HEAD", None)

    def test_inventory_never_runs_repository_fsmonitor_or_filters(self):
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        sentinel = self.root / "git-helper-ran"
        script = self.root / "helper.sh"
        script.write_text(f"#!/bin/sh\ntouch '{sentinel}'\ncat\n")
        script.chmod(0o755)
        git(self.root, "config", "core.fsmonitor", str(script))
        git(self.root, "config", "filter.custom.clean", str(script))
        git(self.root, "config", "filter.custom.process", str(script))
        (self.root / ".gitattributes").write_text("*.md filter=custom\n")
        (self.root / "README.md").write_text("Changed documentation\n")
        self.assertTrue(MODULE.repository_files(self.root))
        self.assertFalse(sentinel.exists(), "Inventory executed repository-configured code")
