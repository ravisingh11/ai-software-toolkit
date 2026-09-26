from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("repository_validator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class RepositoryValidatorTests(unittest.TestCase):
    def test_machine_path_scan_ignores_superpowers_scratch_but_scans_product_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scratch = root / ".superpowers" / "notes.md"
            scratch.parent.mkdir()
            machine_path = "/" + "Users/example"
            scratch.write_text(f"{machine_path}/scratch\n", encoding="utf-8")

            with mock.patch.object(MODULE, "ROOT", root):
                MODULE.validate_no_machine_paths()

            product = root / "docs" / "product.md"
            product.parent.mkdir()
            product.write_text(f"{machine_path}/product\n", encoding="utf-8")
            stderr = io.StringIO()

            with mock.patch.object(MODULE, "ROOT", root):
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit):
                        MODULE.validate_no_machine_paths()

            self.assertIn("docs/product.md", stderr.getvalue())
            self.assertNotIn(".superpowers/notes.md", stderr.getvalue())

    def test_machine_path_scan_ignores_generated_guardrail_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / ".artifacts" / "guardrails" / "scorecard.md"
            report.parent.mkdir(parents=True)
            machine_path = "/" + "Users/example/repository/evidence.json"
            report.write_text(f"Evidence: {machine_path}\n", encoding="utf-8")

            with mock.patch.object(MODULE, "ROOT", root):
                MODULE.validate_no_machine_paths()


if __name__ == "__main__":
    unittest.main()


class DocumentationCoverageTests(unittest.TestCase):
    def test_repository_documents_every_shipped_surface(self) -> None:
        self.assertEqual(MODULE.documentation_gaps(), [])

    def test_gaps_are_named_per_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workflows").mkdir()
            (root / "workflows" / "documented.yml").write_text("name: A\n", encoding="utf-8")
            (root / "workflows" / "orphan.yml").write_text("name: B\n", encoding="utf-8")
            (root / "workflows" / "README.md").write_text("`documented.yml` is installed.\n", encoding="utf-8")
            (root / "skills" / "listed").mkdir(parents=True)
            (root / "skills" / "listed" / "SKILL.md").write_text("---\nname: listed\n---\n", encoding="utf-8")
            (root / "skills" / "unlisted").mkdir()
            (root / "skills" / "unlisted" / "SKILL.md").write_text("---\nname: unlisted\n---\n", encoding="utf-8")
            (root / "skills" / "README.md").write_text("- `listed`\n", encoding="utf-8")
            (root / "policies").mkdir()
            (root / "policies" / "provider-config.yaml").write_text(
                '{"providers": {"seen": {"display_name": "Seen Provider"}, "ghost": {"display_name": "Ghost Provider"}}}',
                encoding="utf-8")
            (root / "docs" / "providers").mkdir(parents=True)
            (root / "docs" / "providers" / "README.md").write_text("Seen Provider is documented. tooling/known.py too.\n", encoding="utf-8")
            (root / "tooling").mkdir()
            (root / "tooling" / "known.py").write_text("", encoding="utf-8")
            (root / "tooling" / "secret.sh").write_text("", encoding="utf-8")
            gaps = MODULE.documentation_gaps(root)
            self.assertEqual(gaps, [
                "workflows/README.md does not mention workflows/orphan.yml",
                "skills/README.md does not mention the unlisted skill",
                "provider ghost (Ghost Provider) is not documented in docs/providers, control setup, or the workflows README",
                "tooling/secret.sh is not mentioned in any published documentation",
            ])
            stderr = io.StringIO()
            with mock.patch.object(MODULE, "ROOT", root), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    MODULE.validate_documentation_coverage()
            self.assertIn("orphan.yml", stderr.getvalue())
