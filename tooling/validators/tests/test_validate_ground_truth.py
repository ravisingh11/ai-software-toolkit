from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "validate_ground_truth.py"


class GroundTruthValidatorTests(unittest.TestCase):
    def run_validator(
        self, root: Path, *arguments: str, measurements: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if key != "PROOF_MEASUREMENTS_FILE"}
        if measurements is not None:
            env["PROOF_MEASUREMENTS_FILE"] = str(measurements)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_measurements_count_declared_found_and_missing_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            policy = self.write_policy(root, [{"path": "AGENTS.md"}, {"path": "docs/missing.md"}])
            output = root / "measurements.json"

            result = self.run_validator(root, "--policy", str(policy), measurements=output)

            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"version": 1, "source": "pull-request-workflow",
                 "documents": {"declared": 2, "found": 1, "missing": 1}},
            )

    def test_unwritable_measurements_warn_without_changing_the_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            policy = self.write_policy(root, [{"path": "AGENTS.md"}])

            result = self.run_validator(root, "--policy", str(policy), measurements=root / "missing" / "m.json")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("measurements were not recorded", result.stdout)

    def test_invalid_policy_records_no_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = self.write_policy(root, [{"path": "/etc/passwd"}])
            output = root / "measurements.json"

            result = self.run_validator(root, "--policy", str(policy), measurements=output)

            self.assertEqual(result.returncode, 1)
            self.assertFalse(output.exists())

    def write_policy(self, root: Path, documents: list[object]) -> Path:
        policy = root / "policy.yaml"
        policy.write_text(
            json.dumps({"version": 1, "documents": documents}),
            encoding="utf-8",
        )
        return policy

    def test_valid_inventory_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            policy = self.write_policy(root, [{"path": "AGENTS.md"}])

            result = self.run_validator(root, "--policy", str(policy))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("passed (1 documents)", result.stdout)

    def test_valid_nested_repository_path_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "docs" / "standards" / "README.md"
            document.parent.mkdir(parents=True)
            document.write_text("# Standards\n", encoding="utf-8")
            policy = self.write_policy(
                root,
                [{"path": "docs/standards/README.md"}],
            )

            result = self.run_validator(root, "--policy", str(policy))

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("passed (1 documents)", result.stdout)

    def test_absolute_document_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "README.md"
            document.write_text("# Fixture\n", encoding="utf-8")
            policy = self.write_policy(root, [{"path": str(document)}])

            result = self.run_validator(root, "--policy", str(policy))

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("must be repository-relative", result.stdout)

    def test_parent_traversal_outside_repository_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "repository"
            root.mkdir()
            (workspace / "outside.md").write_text("# Outside\n", encoding="utf-8")
            policy = self.write_policy(root, [{"path": "../outside.md"}])

            result = self.run_validator(root, "--policy", str(policy))

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("must resolve within repository root", result.stdout)

    def test_symlink_outside_repository_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "repository"
            root.mkdir()
            outside = workspace / "outside.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            (root / "linked.md").symlink_to(outside)
            policy = self.write_policy(root, [{"path": "linked.md"}])

            result = self.run_validator(root, "--policy", str(policy))

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("must resolve within repository root", result.stdout)

    def test_missing_declared_document_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = self.write_policy(root, [{"path": "missing.md"}])

            result = self.run_validator(root, "--policy", str(policy))

            self.assertEqual(result.returncode, 1)
            self.assertIn("- missing.md", result.stdout)

    def test_malformed_inventory_entries_fail(self) -> None:
        malformed_entries = {
            "string entry": "README.md",
            "missing path": {},
            "empty path": {"path": ""},
            "non-string path": {"path": 1},
            "unexpected shape": {"path": "README.md", "owner": "platform"},
        }
        for label, entry in malformed_entries.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "README.md").write_text("# Fixture\n", encoding="utf-8")
                policy = self.write_policy(root, [entry])

                result = self.run_validator(root, "--policy", str(policy))

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("invalid document entry 1", result.stdout)

    def test_installed_starter_requires_readme(self) -> None:
        starter = (
            SCRIPT.parents[2] / "proof" / "defaults" / "ground-truth-ai.yaml"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result = self.run_validator(root, "--policy", str(starter))

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("- README.md", result.stdout)

    def test_malformed_json_compatible_yaml_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "policy.yaml"
            policy.write_text("version: 1\n", encoding="utf-8")

            result = self.run_validator(root, "--policy", str(policy))

            self.assertEqual(result.returncode, 1)
            self.assertIn("cannot read ground-truth policy", result.stdout)

    def test_missing_policy_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result = self.run_validator(root, "--policy", "missing-policy.yaml")

            self.assertEqual(result.returncode, 1)
            self.assertIn("cannot read ground-truth policy", result.stdout)

    def test_default_policy_uses_proof_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / ".proof" / "ground-truth-ai.yaml"
            policy.parent.mkdir()
            policy.write_text(
                json.dumps({"version": 1, "documents": []}),
                encoding="utf-8",
            )

            result = self.run_validator(root)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("passed (0 documents)", result.stdout)


if __name__ == "__main__":
    unittest.main()
