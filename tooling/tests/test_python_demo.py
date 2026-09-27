from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from types import ModuleType
from pathlib import Path
from typing import Any

from tooling import install as installer


ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples/python-demo"

DEMO_OWNED_CONFIG = {
    Path(".proof/documentation.yaml"),
    Path(".proof/ground-truth-ai.yaml"),
    Path(".proof/policy.yaml"),
}


def run(
    command: list[str],
    cwd: Path,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
    )


def assert_equal_trees(test: unittest.TestCase, installed: Path, source: Path) -> None:
    installed_files = {
        path.relative_to(installed): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    source_files = {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    test.assertEqual(installed_files, source_files)


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PythonDemoTests(unittest.TestCase):
    def archived_demo(self, directory: str) -> Path:
        temporary_root = Path(directory)
        staging = temporary_root / "staging" / "python-demo"
        shutil.copytree(
            DEMO,
            staging,
            ignore=shutil.ignore_patterns(".artifacts", "__pycache__", "*.pyc"),
        )
        archive = shutil.make_archive(
            str(temporary_root / "python-demo"),
            "gztar",
            root_dir=staging.parent,
            base_dir=staging.name,
        )
        consumer_root = temporary_root / "consumer"
        shutil.unpack_archive(archive, consumer_root)
        return consumer_root / "python-demo"

    def documented_commands(self) -> list[list[str]]:
        readme = (DEMO / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Run the example", 1)[1].split("## ", 1)[0]
        command_block = re.search(r"```sh\n(?P<commands>.*?)```", section, re.DOTALL)
        if command_block is None:
            self.fail("README run section is missing its shell command block")
        commands = [
            shlex.split(line)
            for line in command_block.group("commands").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(commands), 3)
        return commands

    def test_archived_demo_executes_all_documented_commands_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo = self.archived_demo(directory)
            self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
            self.assertEqual(
                run(["git", "config", "user.name", "Demo Test"], demo).returncode,
                0,
            )
            self.assertEqual(
                run(
                    ["git", "config", "user.email", "demo@example.invalid"], demo
                ).returncode,
                0,
            )
            self.assertEqual(run(["git", "add", "."], demo).returncode, 0)
            committed = run(["git", "commit", "-qm", "test: archive demo"], demo)
            self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)

            completed_commands = []
            for command in self.documented_commands():
                with self.subTest(command=command):
                    completed = run(command, demo)
                    completed_commands.append(completed)
                    self.assertEqual(
                        completed.returncode,
                        0,
                        completed.stdout + completed.stderr,
                    )

            default_scan = completed_commands[-1]
            self.assertNotIn("Artifact SBOM", default_scan.stdout)
            self.assertNotIn("not_activated", default_scan.stdout)

            environment = os.environ.copy()
            environment.update(
                {
                    "PROOF_BUILD_COMMAND": "python3 -m compileall -q app.py test_app.py tools .proof",
                    "PROOF_UNIT_TEST_COMMAND": "python3 -m unittest discover -s . -p 'test_*.py'",
                    "PROOF_WORKING_DIRECTORY": ".",
                }
            )
            full_catalog = run(
                ["python3", ".proof/scan.py", "--all-catalog-controls"],
                demo,
                environment=environment,
            )
            self.assertEqual(
                full_catalog.returncode,
                0,
                full_catalog.stdout + full_catalog.stderr,
            )
            self.assertIn("GRAY Artifact SBOM", full_catalog.stdout)
            self.assertIn("not_activated", full_catalog.stdout)

    def test_generated_demo_distribution_matches_canonical_sources(self) -> None:
        for item in installer.runtime_sources(DEMO):
            installed = item.destination.relative_to(DEMO)
            if installed in DEMO_OWNED_CONFIG:
                continue
            with self.subTest(installed=str(installed)):
                self.assertEqual(
                    (DEMO / installed).read_bytes(),
                    item.source.read_bytes(),
                )

        workflows = installer.CORE_WORKFLOWS | installer.GITHUB_WORKFLOWS
        for filename, source in sorted(workflows.items()):
            with self.subTest(workflow=filename):
                self.assertEqual(
                    (DEMO / ".github/workflows" / filename).read_bytes(),
                    source.read_bytes(),
                )

        assert_equal_trees(
            self,
            DEMO / ".proof/semgrep-tests/fixtures",
            ROOT / "security/semgrep/tests/fixtures",
        )
        assert_equal_trees(
            self,
            DEMO / ".agents/skills/prepare-safe-change",
            ROOT / "skills/prepare-safe-change",
        )

    def test_demo_validator_rejects_retired_guidance_in_every_active_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo = self.archived_demo(directory)
            self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
            self.assertEqual(run(["git", "add", "."], demo).returncode, 0)

            ground_truth = json.loads(
                (demo / ".proof/ground-truth-ai.yaml").read_text(encoding="utf-8")
            )
            ground_truth["documents"].append({"path": "POLICY.txt"})
            (demo / ".proof/ground-truth-ai.yaml").write_text(
                json.dumps(ground_truth, indent=2) + "\n",
                encoding="utf-8",
            )
            (demo / "POLICY.txt").write_text(
                "Temporary ground truth.\n", encoding="utf-8"
            )
            self.assertEqual(
                run(
                    ["git", "add", ".proof/ground-truth-ai.yaml", "POLICY.txt"],
                    demo,
                ).returncode,
                0,
            )
            ground_truth_documents = {
                item["path"] for item in ground_truth["documents"]
            }
            tracked_markdown = set(
                run(["git", "ls-files", "*.md"], demo).stdout.splitlines()
            )
            active_documents = sorted(tracked_markdown | ground_truth_documents)
            for relative in active_documents:
                path = demo / relative
                path.write_text(
                    path.read_text(encoding="utf-8")
                    + "\nRetired path: `.agentic-guardrails/evidence.json`.\n",
                    encoding="utf-8",
                )

            completed = run(
                ["python3", "tools/validate_demo.py", "--documentation"],
                demo,
            )

            self.assertNotEqual(completed.returncode, 0)
            for relative in active_documents:
                with self.subTest(relative=relative):
                    self.assertIn(relative, completed.stdout)

    def test_demo_validator_rejects_retired_guardrails_layout_and_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo = self.archived_demo(directory)
            self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
            (demo / ".guardrails").mkdir()
            (demo / ".guardrails/policy.yaml").write_text("{}\n", encoding="utf-8")
            readme = demo / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "\nRun `.guardrails/scan.py`.\n", encoding="utf-8")
            self.assertEqual(run(["git", "add", "."], demo).returncode, 0)

            completed = run(["python3", "tools/validate_demo.py", "--documentation"], demo)

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("retired Guardrails runtime directory exists: .guardrails", completed.stdout)
            self.assertIn("retired Guardrails guidance found in README.md: .guardrails/", completed.stdout)

    def test_demo_validator_rejects_retired_guidance_in_tracked_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo = self.archived_demo(directory)
            self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
            self.assertEqual(run(["git", "add", "."], demo).returncode, 0)
            relative = ".proof/evidence.schema.json"
            path = demo / relative
            document = json.loads(path.read_text(encoding="utf-8"))
            document["description"] = "Retired path: .agentic-guardrails/evidence.json"
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

            completed = run(
                ["python3", "tools/validate_demo.py", "--documentation"],
                demo,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(relative, completed.stdout)

    def test_demo_validator_reports_malformed_nested_configs_without_traceback(self) -> None:
        cases: tuple[tuple[str, str, Any, str], ...] = (
            (
                ".proof/profiles.yaml",
                "profiles",
                [],
                "runtime profiles must contain a profiles object",
            ),
            (
                ".proof/control-catalog.yaml",
                "controls",
                None,
                "control catalog controls must be a list",
            ),
            (
                ".proof/providers.yaml",
                "selections",
                None,
                "provider selections must be an object",
            ),
        )
        for relative, field, malformed, expected in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                demo = self.archived_demo(directory)
                self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
                self.assertEqual(run(["git", "add", "."], demo).returncode, 0)
                path = demo / relative
                document = json.loads(path.read_text(encoding="utf-8"))
                document[field] = malformed
                path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

                completed = run(
                    ["python3", "tools/validate_demo.py", "--documentation"],
                    demo,
                )

                output = completed.stdout + completed.stderr
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(f"ERROR: {expected}", output)
                self.assertNotIn("Traceback", output)

    def test_demo_documentation_validation_rejects_broken_internal_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo = self.archived_demo(directory)
            self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
            readme = demo / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n[Missing document](docs/does-not-exist.md)\n",
                encoding="utf-8",
            )

            completed = run(
                ["python3", "tools/validate_demo.py", "--documentation"],
                demo,
            )

            output = completed.stdout + completed.stderr
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ERROR: README.md has missing link target", output)
            self.assertNotIn("Traceback", output)

    def test_demo_documentation_validation_rejects_malformed_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo = self.archived_demo(directory)
            self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
            policy_path = demo / ".proof/documentation.yaml"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["mappings"] = [{"name": "invalid"}]
            policy_path.write_text(
                json.dumps(policy, indent=2) + "\n",
                encoding="utf-8",
            )

            completed = run(
                ["python3", "tools/validate_demo.py", "--documentation"],
                demo,
            )

            output = completed.stdout + completed.stderr
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "ERROR: mappings[0] requires name, triggers, and documents",
                output,
            )
            self.assertNotIn("Traceback", output)

    def test_demo_documentation_validation_rejects_ground_truth_paths_outside_repository(self) -> None:
        cases = ("absolute", "parent", "symlink")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                demo = self.archived_demo(directory)
                self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
                outside = Path(directory) / "outside.md"
                outside.write_text("Outside the repository.\n", encoding="utf-8")
                if case == "absolute":
                    document_path = str(outside)
                elif case == "parent":
                    document_path = "../../outside.md"
                else:
                    (demo / "ESCAPE.md").symlink_to(outside)
                    document_path = "ESCAPE.md"

                policy_path = demo / ".proof/ground-truth-ai.yaml"
                policy = json.loads(policy_path.read_text(encoding="utf-8"))
                policy["documents"].append({"path": document_path})
                policy_path.write_text(
                    json.dumps(policy, indent=2) + "\n",
                    encoding="utf-8",
                )

                completed = run(
                    ["python3", "tools/validate_demo.py", "--documentation"],
                    demo,
                )

                output = completed.stdout + completed.stderr
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("ERROR: ground-truth path must be repository-relative", output)
                self.assertNotIn("Traceback", output)

    def test_demo_documentation_validation_reports_missing_readme_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo = self.archived_demo(directory)
            self.assertEqual(run(["git", "init", "-q"], demo).returncode, 0)
            (demo / "README.md").unlink()

            completed = run(
                ["python3", "tools/validate_demo.py", "--documentation"],
                demo,
            )

            output = completed.stdout + completed.stderr
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ERROR: missing required file: README.md", output)
            self.assertNotIn("Traceback", output)

    def test_demo_scorecard_color_semantics_match_evaluator(self) -> None:
        scorecard = load_module(
            DEMO / ".proof/scorecard.py",
            "python_demo_scorecard",
        )
        profiles = json.loads((DEMO / ".proof/profiles.yaml").read_text())
        catalog = json.loads((DEMO / ".proof/control-catalog.yaml").read_text())
        providers = json.loads((DEMO / ".proof/providers.yaml").read_text())
        policy = {
            "version": 2,
            "name": "demo-color-contract",
            "profiles": ["github"],
            "overrides": {
                "change": {
                    "deep-sast": "advisory",
                    "dependency-change-review": "not_activated",
                    "platform-secret-protection": "not_activated",
                    "dependency-remediation": "not_activated",
                },
                "release": {},
            },
        }
        missing = {
            "version": 2,
            "subject": {"type": "git-commit", "revision": "abc123"},
            "results": {},
        }

        advisory = scorecard.scorecard(
            policy,
            profiles,
            catalog,
            providers,
            missing,
            "change",
            "abc123",
            subject_type="git-commit",
        )
        policy["overrides"]["change"]["deep-sast"] = "enforced"
        enforced = scorecard.scorecard(
            policy,
            profiles,
            catalog,
            providers,
            missing,
            "change",
            "abc123",
            subject_type="git-commit",
        )
        mismatch = scorecard.scorecard(
            policy,
            profiles,
            catalog,
            providers,
            {
                **missing,
                "subject": {"type": "git-commit", "revision": "stale123"},
            },
            "change",
            "abc123",
            subject_type="git-commit",
        )

        self.assertEqual(
            (advisory["status"], advisory["decision"]), ("ORANGE", "allow")
        )
        self.assertEqual(
            (enforced["status"], enforced["decision"]), ("RED", "block")
        )
        self.assertEqual(
            (mismatch["status"], mismatch["decision"]), ("RED", "block")
        )


if __name__ == "__main__":
    unittest.main()
