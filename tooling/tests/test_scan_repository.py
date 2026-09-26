from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scan_repository.py"
SPEC = importlib.util.spec_from_file_location("guardrails_v2_scan", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def base_evidence(revision: str = "abc123", subject_type: str = "git-commit") -> dict:
    return {"version": 2, "subject": {"type": subject_type, "revision": revision}, "results": {}}


def result(status: str = "passed", producer: str = "producer") -> dict:
    value = {"producer": producer, "status": status}
    if status in {"passed", "failed"}:
        value["evidence"] = ["run: 42"]
    else:
        value["reason"] = "no result"
    return value


def scope_result() -> dict:
    return {
        "status": "passed",
        "metrics": {
            "files": 1, "added_lines": 10, "changed_lines": 12,
            "max_added_lines_per_file": 10, "binary_files": 0,
            "total_files": 2, "total_added_lines": 15, "total_changed_lines": 20,
            "excluded_files": 1, "excluded_added_lines": 5,
            "excluded_changed_lines": 8, "excluded_binary_files": 0,
        },
        "thresholds": {"max_files": 12, "max_added_lines": 300,
                       "max_changed_lines": 500, "max_added_lines_per_file": 150},
    }


class RuntimeResolutionTests(unittest.TestCase):
    def test_installed_runtime_wins_over_consumer_application_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installed = target / ".guardrails" / "evaluate.py"
            application = target / "guardrails" / "evaluate.py"
            installed.parent.mkdir()
            application.parent.mkdir()
            installed.write_text("SOURCE = 'installed'\n", encoding="utf-8")
            application.write_text("SOURCE = 'application'\n", encoding="utf-8")

            resolved = MODULE.runtime_path(
                target,
                scanner_path=target / ".guardrails/scan.py",
                installed_relative=Path(".guardrails/evaluate.py"),
                source_relative=Path("guardrails/evaluate.py"),
            )

            self.assertEqual(resolved, installed)

    def test_installed_runtime_fails_closed_when_sibling_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            application = target / "guardrails" / "evaluate.py"
            application.parent.mkdir()
            application.write_text("SOURCE = 'application'\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "installed runtime is missing"):
                MODULE.runtime_path(
                    target,
                    scanner_path=target / ".guardrails/scan.py",
                    installed_relative=Path(".guardrails/evaluate.py"),
                    source_relative=Path("guardrails/evaluate.py"),
                )

    def test_source_scanner_resolves_only_the_canonical_source_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            scanner = target / "tooling" / "scan_repository.py"
            source = target / "guardrails" / "evaluate.py"
            scanner.parent.mkdir()
            source.parent.mkdir()
            scanner.write_text("# scanner\n", encoding="utf-8")
            source.write_text("SOURCE = 'canonical'\n", encoding="utf-8")

            resolved = MODULE.runtime_path(
                target,
                scanner_path=scanner,
                installed_relative=Path(".guardrails/evaluate.py"),
                source_relative=Path("guardrails/evaluate.py"),
            )

            self.assertEqual(resolved, source)


class NestedEvidenceMergeTests(unittest.TestCase):
    def write(self, directory: Path, name: str, document: dict) -> None:
        (directory / name).write_text(json.dumps(document), encoding="utf-8")

    def test_merges_multiple_providers_for_one_control_without_collapsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fragments = Path(directory)
            first = base_evidence()
            first["results"] = {"deep-sast": {"github-codeql": result()}}
            second = base_evidence()
            second["results"] = {"deep-sast": {"snyk-code": result("failed")}}
            self.write(fragments, "a.json", first)
            self.write(fragments, "b.json", second)
            merged = base_evidence()

            MODULE.merge_external_evidence(merged, fragments)

            self.assertEqual(set(merged["results"]["deep-sast"]), {"github-codeql", "snyk-code"})

    def test_rejects_conflicting_results_for_same_control_and_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fragments = Path(directory)
            for name, status in (("a.json", "passed"), ("b.json", "failed")):
                document = base_evidence()
                document["results"] = {"build": {"repository-build": result(status)}}
                self.write(fragments, name, document)

            with self.assertRaisesRegex(ValueError, "conflicting evidence"):
                MODULE.merge_external_evidence(base_evidence(), fragments)

    def test_stale_revision_or_subject_type_fragments_are_rejected_from_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fragments = Path(directory)
            for name, document in (
                ("revision.json", base_evidence("old")),
                ("subject.json", base_evidence(subject_type="artifact")),
            ):
                document["results"] = {"build": {"repository-build": result()}}
                self.write(fragments, name, document)
            merged = base_evidence()

            rejected = MODULE.merge_external_evidence(merged, fragments)

            self.assertEqual(rejected, ["revision.json", "subject.json"])
            self.assertEqual(merged["results"], {})


class LocalEvidenceTests(unittest.TestCase):
    def producer(self) -> mock.Mock:
        producer = mock.Mock()
        producer.repository_command_result.side_effect = [
            result("not_run", "build"),
            result("not_run", "tests"),
            result("not_run", "coverage"),
            result("not_run", "format"),
            result("not_run", "migrations"),
        ]
        producer.COMMAND_PRODUCERS = {
            "build": ("BUILD", "repository-build", "Build"),
            "unit-tests": ("TEST", "repository-unit-tests", "Tests"),
            "changed-code-coverage": (
                "COVERAGE",
                "repository-changed-code-coverage",
                "Coverage",
            ),
            "format-and-lint": (
                "FORMAT",
                "repository-format-and-lint",
                "Format",
            ),
            "migration-validation": (
                "MIGRATIONS",
                "repository-migration-validation",
                "Migrations",
            ),
        }
        producer.semgrep_result.return_value = result("passed", "semgrep")
        producer.gitleaks_result.return_value = result("passed", "gitleaks")
        return producer

    def commit(self, target: Path, message: str) -> str:
        subprocess.run(["git", "add", "."], cwd=target, check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=target, check=True)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def initialize_documentation_repository(self, target: Path) -> str:
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
        validators = target / "tooling" / "validators"
        validators.mkdir(parents=True)
        (validators / "validate_repository.py").write_text(
            "print('repository ok')\n",
            encoding="utf-8",
        )
        (validators / "validate_documentation.py").write_text(
            (SCRIPT.parent / "validators" / "validate_documentation.py").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        guardrails = target / ".guardrails"
        guardrails.mkdir()
        (guardrails / "documentation.yaml").write_text(
            json.dumps(
                {
                    "version": 1,
                    "mappings": [
                        {
                            "name": "application-code",
                            "triggers": ["app.py"],
                            "documents": ["README.md"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (target / "README.md").write_text("# Fixture\n", encoding="utf-8")
        return self.commit(target, "base")

    def initialize_repository(self, target: Path) -> str:
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
        validators = target / "tooling" / "validators"
        validators.mkdir(parents=True)
        for filename in ("validate_repository.py", "validate_documentation.py", "inspect_change_scope.py"):
            (validators / filename).write_text("raise SystemExit('local validator must not run')\n", encoding="utf-8")
        guardrails = target / ".guardrails"
        guardrails.mkdir()
        (guardrails / "validate_ground_truth.py").write_text("raise SystemExit('ground truth must not run')\n", encoding="utf-8")
        (guardrails / "ground-truth-ai.yaml").write_text("{}\n", encoding="utf-8")
        (target / "README.md").write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=target, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=target, check=True)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=target, check=True, text=True, capture_output=True
        ).stdout.strip()

    def test_available_validators_use_canonical_core_provider_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            validators = target / "tooling" / "validators"
            validators.mkdir(parents=True)
            for filename in ("validate_repository.py", "validate_documentation.py", "inspect_change_scope.py"):
                (validators / filename).write_text("# fixture\n", encoding="utf-8")
            ground_truth = target / ".guardrails"
            ground_truth.mkdir()
            (ground_truth / "validate_ground_truth.py").write_text("# fixture\n", encoding="utf-8")
            (ground_truth / "ground-truth-ai.yaml").write_text("{}\n", encoding="utf-8")
            scope_payload = json.dumps(scope_result())
            producer = mock.Mock()
            producer.repository_command_result.side_effect = [
                result("not_run", "build"),
                result("not_run", "tests"),
                result("not_run", "coverage"),
                result("not_run", "format"),
                result("not_run", "migrations"),
            ]
            producer.COMMAND_PRODUCERS = self.producer().COMMAND_PRODUCERS
            producer.semgrep_result.return_value = result("passed", "semgrep")
            producer.gitleaks_result.return_value = result("passed", "gitleaks")

            with mock.patch.object(MODULE, "local_binding", return_value=("abc123", None)), mock.patch.object(MODULE, "exact_local_revision", return_value=("base123", None)), mock.patch.object(MODULE, "run", side_effect=[(0, "repository ok"), (0, "docs ok"), (0, "ground truth ok"), (0, scope_payload)]):
                with mock.patch.object(MODULE, "load", return_value=scope_result()), mock.patch.object(MODULE, "producer_module", return_value=producer):
                    evidence = MODULE.local_evidence(target, "abc123", "HEAD~1")

            for control_id in ("repository-validation", "documentation-validation", "repository-ground-truth"):
                self.assertEqual(set(evidence["results"][control_id]), {"repository-validator"})
            self.assertEqual(
                set(evidence["results"]["change-scope"]),
                {"repository-change-scope"},
            )
            self.assertEqual(
                evidence["results"]["change-scope"]["repository-change-scope"]["change_scope"],
                {"version": 1, "metrics": scope_result()["metrics"], "thresholds": scope_result()["thresholds"]},
            )
            self.assertEqual(set(evidence["results"]["build"]), {"repository-build"})
            self.assertEqual(set(evidence["results"]["unit-tests"]), {"repository-unit-tests"})
            self.assertEqual(set(evidence["results"]["changed-code-coverage"]), {"repository-changed-code-coverage"})
            self.assertEqual(set(evidence["results"]["format-and-lint"]), {"repository-format-and-lint"})
            self.assertEqual(set(evidence["results"]["migration-validation"]), {"repository-migration-validation"})
            self.assertEqual(set(evidence["results"]["custom-static-analysis"]), {"semgrep-ce"})
            self.assertEqual(set(evidence["results"]["secret-detection"]), {"gitleaks"})

    def test_oversized_optional_scope_threshold_preserves_local_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            validators = target / "tooling" / "validators"
            validators.mkdir(parents=True)
            (validators / "inspect_change_scope.py").write_text("# fixture\n")
            scope = scope_result()
            scope["thresholds"]["max_files"] = 2**53
            with (
                mock.patch.object(MODULE, "local_binding", return_value=("abc123", None)),
                mock.patch.object(MODULE, "exact_local_revision", return_value=("base123", None)),
                mock.patch.object(MODULE, "run", return_value=(0, "scope complete")),
                mock.patch.object(MODULE, "load", return_value=scope),
                mock.patch.object(MODULE, "producer_module", return_value=self.producer()),
            ):
                evidence = MODULE.local_evidence(target, "abc123", "HEAD~1")
            record = evidence["results"]["change-scope"]["repository-change-scope"]
            self.assertEqual(record["status"], "passed")
            self.assertEqual(record["evidence"], [json.dumps(scope["metrics"], sort_keys=True)])
            self.assertNotIn("change_scope", record)

    def test_app_only_change_without_mapped_documentation_fails_local_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.initialize_documentation_repository(target)
            (target / "app.py").write_text("print('changed')\n", encoding="utf-8")
            head = self.commit(target, "application change")

            with mock.patch.object(MODULE, "producer_module", return_value=self.producer()):
                evidence = MODULE.local_evidence(target, head, "HEAD~1")

            documentation = evidence["results"]["documentation-validation"]["repository-validator"]
            self.assertEqual(documentation["status"], "failed")
            self.assertIn("application-code", documentation["evidence"][1])

    def test_local_scan_supplies_resolved_base_and_head_to_documentation_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = self.initialize_documentation_repository(target)
            (target / "app.py").write_text("print('changed')\n", encoding="utf-8")
            (target / "README.md").write_text("# Fixture\n\nChanged.\n", encoding="utf-8")
            head = self.commit(target, "documented application change")

            with mock.patch.object(MODULE, "producer_module", return_value=self.producer()):
                evidence = MODULE.local_evidence(target, head, "HEAD~1")

            documentation = evidence["results"]["documentation-validation"]["repository-validator"]
            self.assertEqual(documentation["status"], "passed")
            self.assertIn(f"--base-ref {base}", documentation["evidence"][0])
            self.assertIn(f"--head-ref {head}", documentation["evidence"][0])

    def test_selected_authority_placeholders_are_not_run_and_unselected_controls_are_absent(self) -> None:
        evidence = base_evidence()
        selected = {"build": {"mode": "advisory", "authoritative": "repository-build", "supplemental": []}}
        providers = {"repository-build": {"display_name": "Repository Build"}}

        MODULE.add_authoritative_placeholders(evidence, selected, providers)

        self.assertEqual(evidence["results"]["build"]["repository-build"]["status"], "not_run")
        self.assertEqual(set(evidence["results"]), {"build"})

    def test_configuration_presence_is_never_passing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            config = target / ".github" / "dependabot.yml"
            config.parent.mkdir()
            config.write_text("version: 2\n", encoding="utf-8")

            evidence = MODULE.configuration_presence_evidence(config, target, "GitHub Dependabot")

            self.assertEqual(evidence["status"], "not_run")
            self.assertIn("configuration", evidence["reason"].lower())

    def test_tool_producer_does_not_run_after_revision_binding_is_lost(self) -> None:
        producer = mock.Mock()
        producer.exact_clean_head.side_effect = ValueError("worktree is dirty")
        producer.producer_result.side_effect = (
            lambda name, status, reason: {"producer": name, "status": status, "reason": reason}
        )
        callback = mock.Mock()

        result = MODULE.revision_bound_tool_result(
            producer,
            Path("/repo"),
            "abc123",
            "Semgrep Community Edition",
            callback,
        )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("dirty", result["reason"])
        callback.assert_not_called()

    def test_tool_producer_result_is_discarded_if_it_changes_the_revision(self) -> None:
        producer = mock.Mock()
        producer.exact_clean_head.side_effect = ["abc123", ValueError("worktree is dirty")]
        producer.producer_result.side_effect = (
            lambda name, status, reason: {"producer": name, "status": status, "reason": reason}
        )

        evidence_result = MODULE.revision_bound_tool_result(
            producer,
            Path("/repo"),
            "abc123",
            "Gitleaks CLI",
            mock.Mock(return_value=result("passed", "gitleaks")),
        )

        self.assertEqual(evidence_result["status"], "not_run")
        self.assertIn("dirty", evidence_result["reason"])

    def test_fake_requested_revision_makes_all_local_provider_results_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.initialize_repository(target)

            evidence = MODULE.local_evidence(target, "f" * 40, "HEAD~1")

            statuses = [
                provider_result["status"]
                for control_results in evidence["results"].values()
                for provider_result in control_results.values()
            ]
            self.assertEqual(set(statuses), {"not_run"})
            self.assertIn("exact", next(iter(evidence["results"]["repository-validation"].values()))["reason"])

    def test_dirty_worktree_makes_all_local_provider_results_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            revision = self.initialize_repository(target)
            (target / "README.md").write_text("dirty\n", encoding="utf-8")

            evidence = MODULE.local_evidence(target, revision, "HEAD~1")

            statuses = [
                provider_result["status"]
                for control_results in evidence["results"].values()
                for provider_result in control_results.values()
            ]
            self.assertEqual(set(statuses), {"not_run"})
            self.assertIn("clean worktree", next(iter(evidence["results"]["repository-validation"].values()))["reason"])


class ArtifactPathTests(unittest.TestCase):
    def test_default_markdown_and_json_artifacts_share_one_utc_timestamp(self) -> None:
        timestamp = datetime(2026, 8, 28, 12, 3, 4, tzinfo=timezone.utc)

        evidence, latest, report = MODULE.default_artifact_paths(Path("/repo"), timestamp)

        self.assertEqual(evidence, Path("/repo/.artifacts/guardrails/evidence-20260828-120304Z.json"))
        self.assertEqual(latest, Path("/repo/.artifacts/guardrails/evidence.json"))
        self.assertEqual(report, Path("/repo/.artifacts/guardrails/scorecard-20260828-120304Z.md"))

    def test_json_output_card_identifies_primary_timestamped_artifacts(self) -> None:
        card = {"version": 2, "status": "ORANGE"}
        evidence = Path("/repo/.artifacts/guardrails/evidence-20260828-120304Z.json")
        report = Path("/repo/.artifacts/guardrails/scorecard-20260828-120304Z.md")

        MODULE.add_artifact_locations(card, evidence, report)

        self.assertEqual(card["artifacts"], {"evidence": str(evidence), "report": str(report)})


class ScanSubjectContractTests(unittest.TestCase):
    def documents(self, profiles: list[str], release_overrides: dict[str, str]) -> list[dict]:
        policy = json.loads((MODULE.ROOT / "guardrails" / "baseline.yaml").read_text(encoding="utf-8"))
        policy["profiles"] = profiles
        policy["overrides"]["release"] = release_overrides
        return [
            policy,
            json.loads((MODULE.ROOT / "policies" / "profiles.yaml").read_text(encoding="utf-8")),
            json.loads((MODULE.ROOT / "policies" / "control-catalog.yaml").read_text(encoding="utf-8")),
            json.loads((MODULE.ROOT / "policies" / "provider-config.yaml").read_text(encoding="utf-8")),
        ]

    def scorecard_result(self, subject_type: str, revision: str) -> mock.Mock:
        return mock.Mock(
            returncode=0,
            stdout=json.dumps({
                "version": 2,
                "decision": "allow",
                "status": "ORANGE",
                "policy": "fixture",
                "operation": "release",
                "subject": {"type": subject_type, "revision": revision},
                "controls": [],
            }),
            stderr="",
        )

    def test_release_scan_rejects_policy_with_mixed_git_commit_and_artifact_subjects(self) -> None:
        documents = self.documents(
            ["core", "github"],
            {"artifact-provenance": "enforced"},
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            evidence_path = target / "evidence.json"
            report_path = target / "report.md"
            argv = [
                str(SCRIPT), "--target", str(target), "--operation", "release",
                "--revision", "abc123", "--evidence", str(evidence_path),
                "--report", str(report_path),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                MODULE, "load", side_effect=documents
            ), mock.patch.object(
                MODULE, "local_evidence", return_value=base_evidence()
            ) as local_evidence, mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=self.scorecard_result("git-commit", "abc123"),
            ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                returncode = MODULE.main()

        self.assertEqual(returncode, 2)
        self.assertIn("mixed evidence subjects", stderr.getvalue())
        self.assertIn("artifact", stderr.getvalue())
        self.assertIn("git-commit", stderr.getvalue())
        local_evidence.assert_not_called()

    def test_mixed_release_scan_uses_explicit_artifact_subject_contract(self) -> None:
        documents = self.documents(
            ["core", "github"],
            {"artifact-provenance": "enforced"},
        )
        revision = "sha256:abc123"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            evidence_path = target / "evidence.json"
            report_path = target / "report.md"
            argv = [
                str(SCRIPT), "--target", str(target), "--operation", "release",
                "--subject-type", "artifact", "--revision", revision,
                "--evidence", str(evidence_path), "--report", str(report_path),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                MODULE, "load", side_effect=documents
            ), mock.patch.object(
                MODULE, "local_evidence", return_value=base_evidence(revision)
            ) as local_evidence, mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=self.scorecard_result("artifact", revision),
            ) as scorecard, mock.patch("sys.stdout", new_callable=io.StringIO):
                returncode = MODULE.main()

            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(returncode, 0)
        self.assertEqual(evidence["subject"], {"type": "artifact", "revision": revision})
        self.assertEqual(set(evidence["results"]), {"artifact-provenance"})
        local_evidence.assert_not_called()
        command = scorecard.call_args.args[0]
        self.assertEqual(command[command.index("--subject-type") + 1], "artifact")

    def test_release_scan_rejects_subject_selector_not_activated_by_policy(self) -> None:
        documents = self.documents(["core", "github"], {})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            argv = [
                str(SCRIPT), "--target", str(target), "--operation", "release",
                "--subject-type", "environment", "--revision", "production",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                MODULE, "load", side_effect=documents
            ), mock.patch.object(
                MODULE, "local_evidence", return_value=base_evidence()
            ) as local_evidence, mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                returncode = MODULE.main()

        self.assertEqual(returncode, 2)
        self.assertIn("environment", stderr.getvalue())
        self.assertIn("not activated", stderr.getvalue())
        local_evidence.assert_not_called()

    def test_demo_core_and_github_release_policy_scans_selected_git_commit_end_to_end(self) -> None:
        demo = MODULE.ROOT / "examples" / "python-demo"
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=demo,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--target",
                    str(demo),
                    "--operation",
                    "release",
                    "--subject-type",
                    "git-commit",
                    "--revision",
                    revision,
                    "--evidence",
                    str(artifacts / "evidence.json"),
                    "--evidence-dir",
                    str(artifacts / "external-evidence"),
                    "--report",
                    str(artifacts / "report.md"),
                    "--json",
                ],
                cwd=MODULE.ROOT,
                text=True,
                capture_output=True,
            )

            card = json.loads(completed.stdout)
            evidence = json.loads((artifacts / "evidence.json").read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(card["subject"], {"type": "git-commit", "revision": revision})
        self.assertIn("build", {control["id"] for control in card["controls"]})
        self.assertNotIn("artifact-provenance", {control["id"] for control in card["controls"]})
        self.assertEqual(evidence["subject"], {"type": "git-commit", "revision": revision})

    def test_artifact_only_release_scan_uses_artifact_subject_for_evidence_and_scorecard(self) -> None:
        documents = self.documents(["github"], {})
        revision = "sha256:abc123"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            evidence_path = target / "evidence.json"
            report_path = target / "report.md"
            argv = [
                str(SCRIPT), "--target", str(target), "--operation", "release",
                "--revision", revision, "--evidence", str(evidence_path),
                "--report", str(report_path),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                MODULE, "load", side_effect=documents
            ), mock.patch.object(
                MODULE, "local_evidence", return_value=base_evidence(revision)
            ) as local_evidence, mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=self.scorecard_result("artifact", revision),
            ) as scorecard:
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    returncode = MODULE.main()

            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(returncode, 0)
        self.assertEqual(evidence["subject"], {"type": "artifact", "revision": revision})
        local_evidence.assert_not_called()
        command = scorecard.call_args.args[0]
        self.assertEqual(command[command.index("--subject-type") + 1], "artifact")


if __name__ == "__main__":
    unittest.main()
