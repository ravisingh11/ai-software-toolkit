from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

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
    git(root, "config", "user.name", "Guardrails Test")
    git(root, "config", "user.email", "guardrails@example.invalid")
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
        cls.policy = MODULE.load_policy(ROOT / ".guardrails" / "documentation.yaml")

    def test_default_policy_uses_guardrails_configuration(self) -> None:
        self.assertEqual(
            MODULE.DEFAULT_POLICY,
            MODULE.ROOT / ".guardrails" / "documentation.yaml",
        )

    def test_current_documentation_links_and_targets_are_valid(self) -> None:
        self.assertEqual(
            MODULE.validate(ROOT, ROOT / ".guardrails" / "documentation.yaml"),
            [],
        )

    def test_contract_change_requires_mapped_documentation(self) -> None:
        failures = MODULE.validate_changed_files(
            self.policy,
            ["guardrails/evaluate.py"],
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("control-contract", failures[0])

    def test_contract_change_passes_with_mapped_documentation(self) -> None:
        failures = MODULE.validate_changed_files(
            self.policy,
            ["guardrails/evaluate.py", "docs/guardrails/README.md"],
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

    def test_changed_files_exclude_base_only_changes_after_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, head = diverged_commits(root)

            changed_files = MODULE.changed_between(root, base, head, None)

            self.assertEqual(changed_files, ["head-only.py"])


if __name__ == "__main__":
    unittest.main()
