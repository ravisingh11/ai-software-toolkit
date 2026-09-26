from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RepositoryValidationWorkflowTests(unittest.TestCase):
    def test_coverage_workflow_preserves_provider_identity(self) -> None:
        providers = json.loads(
            (ROOT / "policies/provider-config.yaml").read_text(encoding="utf-8")
        )
        contract = providers["providers"]["repository-changed-code-coverage"][
            "checks"
        ]["changed-code-coverage"]
        for relative_path in (
            "workflows/changed-code-coverage.yml",
            contract["workflow_path"],
            f"examples/python-demo/{contract['workflow_path']}",
        ):
            with self.subTest(workflow=relative_path):
                workflow = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(f"\nname: {contract['workflow']}\n", workflow)
                self.assertIn(f"    name: {contract['check_name']}\n", workflow)
                # GitHub exposes custom run-name as the Actions run's name.
                # The collector verifies that name against the provider contract.
                self.assertNotIn("\nrun-name:", workflow)

    def test_standards_source_validation_is_a_separate_non_authoritative_check(self) -> None:
        workflow = (ROOT / "workflows" / "repository-validation.yml").read_text(
            encoding="utf-8"
        )
        repository_job = workflow.split("  repository:\n", 1)[1].split(
            "  standards-source:\n", 1
        )[0]
        standards_job = workflow.split("  standards-source:\n", 1)[1].split(
            "  docs:\n", 1
        )[0]

        self.assertIn("python3 .guardrails/validators/validate_repository.py", repository_job)
        self.assertNotIn("tooling/validators/validate_repository.py", repository_job)
        self.assertIn("name: Validate / standards source", standards_job)
        self.assertIn("hashFiles('tooling/validators/validate_repository.py')", standards_job)
        self.assertIn("python3 tooling/validators/validate_repository.py", standards_job)
        self.assertIn("python3 tooling/validate-skills.py", standards_job)

    def test_pull_request_documentation_scan_uses_exact_event_revisions(self) -> None:
        workflow = (ROOT / "workflows" / "repository-validation.yml").read_text(
            encoding="utf-8"
        )
        docs_job = workflow.split("  docs:\n", 1)[1].split("  ground-truth:\n", 1)[0]

        self.assertIn("fetch-depth: 0", docs_job)
        self.assertIn(
            'validate_documentation.py --base-ref "${BASE_REF}" --head-ref "${HEAD_REF}"',
            docs_job,
        )
        self.assertIn(
            "BASE_REF: ${{ github.event.pull_request.base.sha || 'HEAD~1' }}",
            docs_job,
        )
        self.assertIn(
            "HEAD_REF: ${{ github.event.pull_request.head.sha || github.sha }}",
            docs_job,
        )
        self.assertIn("pull_request:\n", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)

    def test_scope_is_owned_by_the_dedicated_trusted_workflow(self) -> None:
        for relative_path in (
            "workflows/repository-validation.yml",
            ".github/workflows/repository-validation.yml",
        ):
            with self.subTest(workflow=relative_path):
                workflow = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertNotIn("Validate / scope", workflow)
                self.assertNotIn("inspect_change_scope.py", workflow)

        scope = (ROOT / "workflows/change-scope.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", scope)
        self.assertIn("name: PR Size / Files & LOC", scope)
        self.assertIn("name: Files & LOC report", scope)
        self.assertIn('name:"PR Change Scope"', scope)
        self.assertIn("--markdown-output", scope)
        self.assertIn("--repository-root candidate", scope)
        self.assertIn("--effective-mode change-scope", scope)
        self.assertIn("guardrails:change-scope:", scope)
        self.assertNotIn("python3 candidate/", scope)


if __name__ == "__main__":
    unittest.main()
