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

    def test_machine_path_scan_ignores_generated_proof_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / ".artifacts" / "proof" / "scorecard.md"
            report.parent.mkdir(parents=True)
            machine_path = "/" + "Users/example/repository/evidence.json"
            report.write_text(f"Evidence: {machine_path}\n", encoding="utf-8")

            with mock.patch.object(MODULE, "ROOT", root):
                MODULE.validate_no_machine_paths()


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

    def test_nested_scripts_yaml_archives_and_filename_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("workflows", "tooling/validators", "tooling/tests/fixtures", "docs/archive"):
                (root / folder).mkdir(parents=True, exist_ok=True)
            for filename in ("lint.yml", "provider.yaml"):
                (root / "workflows" / filename).write_text("name: example")
            (root / "workflows/README.md").write_text("`format-and-lint.yml` `provider.yaml.old`")
            (root / "tooling/validators/check.py").write_text("")
            (root / "tooling/tests/fixtures/ignored.py").write_text("")
            (root / "docs/archive/old.md").write_text("tooling/validators/check.py")
            (root / "README.md").write_text("`precheck.py` and `check.py.old`")
            self.assertEqual(MODULE.documentation_gaps(root), [
                "workflows/README.md does not mention workflows/lint.yml",
                "workflows/README.md does not mention workflows/provider.yaml",
                "tooling/validators/check.py is not mentioned in any published documentation",
            ])
            (root / "workflows/README.md").write_text("[lint](lint.yml), `workflows/provider.yaml`")
            (root / "README.md").write_text("Run `tooling/validators/check.py`.")
            self.assertEqual(MODULE.documentation_gaps(root), [])


    def test_extensionless_commands_require_documentation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tooling").mkdir()
            (root / "tooling/release").write_text("#!/bin/sh\necho release\n")
            executable = root / "tooling/utility"
            executable.write_bytes(b"executable fixture")
            executable.chmod(0o755)
            (root / "tooling/data.txt").write_text("data")
            self.assertEqual(len(MODULE.documentation_gaps(root)), 2)
            (root / "README.md").write_text("`tooling/release` and `tooling/utility`")
            self.assertEqual(MODULE.documentation_gaps(root), [])

    def test_provider_display_names_require_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "policies").mkdir()
            (root / "docs/providers").mkdir(parents=True)
            (root / "policies/provider-config.yaml").write_text('{"providers":{"oss":{"display_name":"OSS"}}}')
            guide = root / "docs/providers/README.md"
            for text in ("FOSSA", "OSS-extra", "extra-OSS"):
                guide.write_text(text)
                self.assertTrue(MODULE.documentation_gaps(root))
            for text in ("OSS is documented", "`oss`", "(OSS)"):
                guide.write_text(text)
                self.assertEqual(MODULE.documentation_gaps(root), [])

    def test_duplicate_script_names_require_their_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("a", "b"):
                (root / "tooling" / folder).mkdir(parents=True)
                (root / "tooling" / folder / "check.py").write_text("")
            readme = root / "README.md"
            readme.write_text("`tooling/a/check.py` and `check.py`")
            self.assertEqual(MODULE.documentation_gaps(root), [
                "tooling/b/check.py is not mentioned in any published documentation",
            ])
            readme.write_text("`tooling/a/check.py` and `tooling/b/check.py`")
            self.assertEqual(MODULE.documentation_gaps(root), [])
            readme.write_text("`tooling/a/check.py` `vendor/tooling/b/check.py`")
            self.assertTrue(any("tooling/b/check.py" in gap for gap in MODULE.documentation_gaps(root)))
            (root / "tooling/b/check.py").unlink()
            readme.write_text("`unrelated/check.py`")
            self.assertEqual(MODULE.documentation_gaps(root), [
                "tooling/a/check.py is not mentioned in any published documentation",
            ])
            for unrelated in (r"vendor\check.py", r"check.py\vendor"):
                readme.write_text(f"`{unrelated}`")
                self.assertEqual(MODULE.documentation_gaps(root), [
                    "tooling/a/check.py is not mentioned in any published documentation",
                ])
            readme.write_text("`check.py`")
            self.assertEqual(MODULE.documentation_gaps(root), [])


if __name__ == "__main__":
    unittest.main()
