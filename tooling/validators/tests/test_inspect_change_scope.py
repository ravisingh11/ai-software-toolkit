from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "inspect_change_scope.py"
SPEC = importlib.util.spec_from_file_location("change_scope", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


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
    git(root, "config", "user.name", "Guardrails Test")
    git(root, "config", "user.email", "guardrails@example.invalid")
    (root / "README.md").write_text("initial\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-q", "-m", "initial")
    git(root, "branch", "feature")

    (root / "base-only.py").write_text("base\n" * 50, encoding="utf-8")
    git(root, "add", "base-only.py")
    git(root, "commit", "-q", "-m", "base only")
    base = git(root, "rev-parse", "HEAD")

    git(root, "checkout", "-q", "feature")
    (root / "head-only.py").write_text("head\n", encoding="utf-8")
    git(root, "add", "head-only.py")
    git(root, "commit", "-q", "-m", "head only")
    return base, git(root, "rev-parse", "HEAD")


def policy() -> dict:
    return {
        "version": 1,
        "limits": {
            "max_files": 2,
            "max_added_lines": 20,
            "max_changed_lines": 30,
            "max_added_lines_per_file": 15,
        },
        "exclude": ["**/*.md"],
    }


class ChangeScopeTests(unittest.TestCase):
    def test_default_policy_uses_guardrails_configuration(self) -> None:
        self.assertEqual(
            MODULE.DEFAULT_POLICY,
            MODULE.ROOT / ".guardrails" / "change-scope.yaml",
        )

    def test_cli_inspects_an_explicit_repository_root_with_trusted_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, head = diverged_commits(root)
            report_path = root / "scope-summary.md"
            policy_path = root.parent / f"{root.name}-policy.json"
            policy_path.write_text(json.dumps(policy()), encoding="utf-8")
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--repository-root",
                        str(root),
                        "--policy",
                        str(policy_path),
                        "--base-ref",
                        base,
                        "--head-ref",
                        head,
                        "--markdown-output",
                        str(report_path),
                        "--mode",
                        "enforced",
                        "--json",
                    ],
                    cwd=SCRIPT.parent,
                    text=True,
                    capture_output=True,
                )
                report = report_path.read_text()
            finally:
                policy_path.unlink(missing_ok=True)

        self.assertIn("**Enforced mode.**", report)
        self.assertIn("| Changed files | 1 | 2 | Within limit |", report)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["subject"]["revision"], head)
        self.assertEqual(result["metrics"]["files"], 1)

    def test_passes_change_within_advisory_thresholds(self) -> None:
        result = MODULE.inspect(
            "git-tree",
            "tree-id",
            [{"path": "src/app.py", "added": 10, "deleted": 2}],
            policy(),
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["metrics"]["changed_lines"], 12)

    def test_reports_each_exceeded_threshold_without_blocking_execution(self) -> None:
        result = MODULE.inspect(
            "git-tree",
            "tree-id",
            [
                {"path": "src/app.py", "added": 16, "deleted": 10},
                {"path": "src/api.py", "added": 10, "deleted": 5},
                {"path": "src/web.py", "added": 2, "deleted": 1},
            ],
            policy(),
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            {finding["metric"] for finding in result["findings"]},
            {
                "files",
                "added_lines",
                "changed_lines",
                "max_added_lines_per_file",
            },
        )

    def test_excludes_documentation_from_source_scope(self) -> None:
        result = MODULE.inspect(
            "git-tree",
            "tree-id",
            [
                {"path": "README.md", "added": 1000, "deleted": 0},
                {"path": "src/app.py", "added": 1, "deleted": 0},
            ],
            policy(),
        )
        self.assertEqual(result["metrics"]["files"], 1)
        self.assertEqual(result["metrics"]["added_lines"], 1)

    def test_reports_total_meaningful_and_excluded_change_volume(self) -> None:
        scope_policy = policy()
        scope_policy["exclude"] = ["**/*.md", "**/*.lock", "**/generated/**"]

        result = MODULE.inspect(
            "git-tree",
            "tree-id",
            [
                {"path": "README.md", "added": 100, "deleted": 20},
                {"path": "src/app.py", "added": 10, "deleted": 2},
                {"path": "requirements.lock", "added": 200, "deleted": 100},
                {"path": "src/generated/schema.bin", "added": None, "deleted": None},
            ],
            scope_policy,
        )

        self.assertEqual(
            result["metrics"],
            {
                "files": 1,
                "added_lines": 10,
                "changed_lines": 12,
                "max_added_lines_per_file": 10,
                "binary_files": 0,
                "total_files": 4,
                "total_added_lines": 310,
                "total_changed_lines": 432,
                "excluded_files": 3,
                "excluded_added_lines": 300,
                "excluded_changed_lines": 420,
                "excluded_binary_files": 1,
            },
        )

    def test_excluded_volume_does_not_trigger_meaningful_thresholds(self) -> None:
        result = MODULE.inspect(
            "git-tree",
            "tree-id",
            [
                {"path": "README.md", "added": 1000, "deleted": 1000},
                {"path": "src/app.py", "added": 1, "deleted": 1},
            ],
            policy(),
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["metrics"]["changed_lines"], 2)
        self.assertEqual(result["metrics"]["total_changed_lines"], 2002)

    def test_human_output_distinguishes_total_and_meaningful_scope(self) -> None:
        result = MODULE.inspect(
            "git-tree",
            "tree-id",
            [
                {"path": "README.md", "added": 1000, "deleted": 0},
                {"path": "src/app.py", "added": 16, "deleted": 10},
            ],
            policy(),
        )

        output = MODULE.render(result)

        self.assertIn("Meaningful: 1 file, 26 changed lines", output)
        self.assertIn("Total: 2 files, 1026 changed lines", output)
        self.assertIn("Excluded: 1 file, 1000 changed lines", output)
        self.assertIn("Largest meaningful addition: 16 lines", output)

    def test_markdown_reports_limits_and_counted_excluded_totals(self) -> None:
        result = MODULE.inspect("git-tree", "tree-id", [
            {"path": "src/app.py", "added": 15, "deleted": 2},
            {"path": "README.md", "added": 1000, "deleted": 5},
            {"path": "logo.png", "added": None, "deleted": None},
        ], policy())
        report = MODULE.render_markdown(result, "advisory")
        self.assertIn("**Result: Within limits.**", report)
        self.assertIn("**Warn only (advisory).**", report)
        self.assertIn("does not block merging", report)
        self.assertIn("| Changed files | 2 | 2 | Within limit |", report)
        self.assertIn("| Added lines | 15 | 20 | Within limit |", report)
        self.assertIn("| Changed lines (added + deleted) | 17 | 30 | Within limit |", report)
        self.assertIn("| Most added lines in one file | 15 | 15 | Within limit |", report)
        self.assertIn("| Counted | 2 | 15 | 2 | 17 |", report)
        self.assertIn("| Excluded by policy | 1 | 1000 | 5 | 1005 |", report)
        self.assertIn("| Total PR | 3 | 1015 | 7 | 1022 |", report)
        self.assertIn("Binary files: 1 counted, 0 excluded", report)
        self.assertIn("stable name **PR Change Scope**", report)

    def test_markdown_distinguishes_warning_and_enforced_failure(self) -> None:
        result = MODULE.inspect("git-tree", "tree-id", [
            {"path": "src/app.py", "added": 40, "deleted": 2},
        ], policy())
        for mode in ("advisory", "enforced", "not_activated"):
            with self.subTest(mode=mode):
                report = MODULE.render_markdown(result, mode)
                self.assertIn("**Result: Limits exceeded.**", report)
                self.assertIn("| Added lines | 40 | 20 | Over limit |", report)
                if mode == "advisory":
                    self.assertIn("neutral check", report)
                elif mode == "enforced":
                    self.assertIn("Exceeding a limit fails the check", report)
                    self.assertIn("depends on the repository ruleset", report)
                    self.assertNotIn("Warn only", report)
                else:
                    self.assertIn("**Not activated.**", report)

    def test_counts_binary_files_without_inventing_line_counts(self) -> None:
        result = MODULE.inspect(
            "git-tree",
            "tree-id",
            [{"path": "assets/logo.png", "added": None, "deleted": None}],
            policy(),
        )
        self.assertEqual(result["metrics"]["binary_files"], 1)
        self.assertEqual(result["metrics"]["changed_lines"], 0)

    def test_between_excludes_base_only_changes_after_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, head = diverged_commits(root)

            result = MODULE.between(root, policy(), base, head, None)

            self.assertEqual(result["metrics"]["files"], 1)
            self.assertEqual(result["metrics"]["added_lines"], 1)
            self.assertEqual(result["metrics"]["changed_lines"], 1)


if __name__ == "__main__":
    unittest.main()
