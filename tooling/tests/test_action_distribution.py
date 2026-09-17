from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEMGREP_IMAGE = "semgrep/semgrep@sha256:b94b53d02fd4a022f9eac4e2af1380f5c3c4c21400e79d3336bdff1d1db5e796"
GITLEAKS_IMAGE = "ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
CORE_WORKFLOWS = {
    "guardrails-scorecard.yml",
    "change-scope.yml",
    "pr-metadata.yml",
    "repository-validation.yml",
    "build.yml",
    "unit-tests.yml",
    "changed-code-coverage.yml",
    "format-and-lint.yml",
    "migration-validation.yml",
    "semgrep-ce.yml",
    "gitleaks.yml",
}
GITHUB_WORKFLOWS = {
    "codeql.yml",
    "dependency-review.yml",
    "github-secret-protection.yml",
    "dependabot-verification.yml",
    "artifact-provenance.yml",
}


class ActionDistributionTests(unittest.TestCase):
    def test_installed_runtime_and_configuration_match_canonical_sources(self) -> None:
        copies = {
            ".guardrails/profiles.yaml": "policies/profiles.yaml",
            ".guardrails/control-catalog.yaml": "policies/control-catalog.yaml",
            ".guardrails/providers.yaml": "policies/provider-config.yaml",
            ".guardrails/policy.schema.json": "guardrails/policy.schema.json",
            ".guardrails/evidence.schema.json": "guardrails/evidence.schema.json",
            ".guardrails/profiles.schema.json": "guardrails/profiles.schema.json",
            ".guardrails/providers.schema.json": "guardrails/providers.schema.json",
            ".guardrails/control-catalog.schema.json": "guardrails/control-catalog.schema.json",
            ".guardrails/evaluate.py": "guardrails/evaluate.py",
            ".guardrails/scorecard.py": "tooling/guardrail_scorecard.py",
            ".guardrails/configure.py": "tooling/configure_guardrails.py",
            ".guardrails/scan.py": "tooling/scan_repository.py",
            ".guardrails/doctor.py": "tooling/doctor.py",
            ".guardrails/github_evidence.py": "tooling/github_evidence.py",
            ".guardrails/produce.py": "tooling/produce_guardrail_evidence.py",
            ".guardrails/validate_ground_truth.py": "tooling/validators/validate_ground_truth.py",
            ".guardrails/semgrep-rules.yml": "security/semgrep/guardrails.yml",
            ".guardrails/validators/validate_repository.py": "guardrails/validate_repository.py",
            ".guardrails/validators/validate_documentation.py": "tooling/validators/validate_documentation.py",
            ".guardrails/validators/inspect_change_scope.py": "tooling/validators/inspect_change_scope.py",
            ".guardrails/validators/validate_pr_metadata.py": "tooling/validators/validate_pr_metadata.py",
        }
        for installed, source in copies.items():
            with self.subTest(installed=installed):
                self.assertEqual((ROOT / installed).read_bytes(), (ROOT / source).read_bytes())

    def test_scorecard_badge_runtime_and_self_workflow_match_canonical_sources(self) -> None:
        copies = {
            ".guardrails/render_scorecard_badge.py": "tooling/render_scorecard_badge.py",
            ".guardrails/reconcile_scorecard_badge.py": "tooling/reconcile_scorecard_badge.py",
            ".github/workflows/guardrails-scorecard-badge.yml": "workflows/guardrails-scorecard-badge.yml",
        }
        for installed, source in copies.items():
            with self.subTest(installed=installed):
                self.assertEqual((ROOT / installed).read_bytes(), (ROOT / source).read_bytes())

    def test_self_repository_uses_core_and_github_profiles_without_a_manifest(self) -> None:
        policy = json.loads((ROOT / ".guardrails/policy.yaml").read_text())
        baseline = json.loads((ROOT / "guardrails/baseline.yaml").read_text())
        catalog = json.loads((ROOT / ".guardrails/control-catalog.yaml").read_text())
        providers = json.loads((ROOT / ".guardrails/providers.yaml").read_text())
        self.assertEqual(policy["version"], 2)
        self.assertEqual(policy["profiles"], ["core", "github"])
        self.assertEqual(policy["overrides"]["change"]["dependency-remediation"], "not_activated")
        self.assertEqual(baseline["profiles"], ["core"])
        self.assertEqual(catalog["version"], 2)
        self.assertEqual(providers["version"], 2)
        self.assertFalse((ROOT / ".guardrails/producer-manifest.json").exists())

    def test_no_active_runtime_or_workflow_references_a_producer_manifest(self) -> None:
        paths = [
            *(path for path in ROOT.glob("tooling/*.py") if path.name != "install.py"),
            *ROOT.glob("guardrails/*.py"),
            *ROOT.glob("workflows/*.yml"),
            *ROOT.glob(".github/workflows/*.yml"),
            *ROOT.glob(".guardrails/*"),
        ]
        failures = [str(path.relative_to(ROOT)) for path in paths if path.is_file() and "producer-manifest" in path.read_text(errors="ignore")]
        self.assertEqual(failures, [])

    def test_core_workflows_are_distributed_to_self_repository(self) -> None:
        for filename in CORE_WORKFLOWS:
            with self.subTest(filename=filename):
                self.assertEqual(
                    (ROOT / ".github/workflows" / filename).read_bytes(),
                    (ROOT / "workflows" / filename).read_bytes(),
                )

    def test_configurable_command_producers_fail_when_command_is_unavailable(self) -> None:
        cases = {
            "format-and-lint.yml": "GUARDRAILS_FORMAT_LINT_COMMAND",
            "migration-validation.yml": "GUARDRAILS_MIGRATION_VALIDATION_COMMAND",
        }

        for filename, variable in cases.items():
            with self.subTest(filename=filename):
                workflow = (ROOT / "workflows" / filename).read_text()
                self.assertNotIn(f"if: ${{{{ vars.{variable} != '' }}}}", workflow)
                self.assertIn("name: Require configured command", workflow)
                self.assertIn(f'if [[ -z "${{{variable}}}" ]]; then', workflow)
                self.assertIn(f"::{variable} is not configured", workflow)
                self.assertIn("exit 1", workflow)

    def test_all_distributed_workflows_parse(self) -> None:
        ruby = shutil.which("ruby")
        if ruby is None:
            self.skipTest("Ruby stdlib YAML parser is unavailable")
        for filename in CORE_WORKFLOWS | GITHUB_WORKFLOWS:
            with self.subTest(filename=filename):
                completed = subprocess.run(
                    [ruby, "-e", "require 'yaml'; YAML.load_file(ARGV.fetch(0))", str(ROOT / "workflows" / filename)],
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_workflows_use_pinned_actions_pr_head_no_credentials_and_timeouts(self) -> None:
        for filename in CORE_WORKFLOWS | (GITHUB_WORKFLOWS - {"artifact-provenance.yml", "github-secret-protection.yml"}):
            with self.subTest(filename=filename):
                text = (ROOT / "workflows" / filename).read_text()
                self.assertIn("timeout-minutes:", text)
                refs = re.findall(r"uses:\s+[^@\s]+@([^\s]+)", text)
                self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs))
                if "actions/checkout@" in text and filename not in {"change-scope.yml", "pr-metadata.yml"}:
                    self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", text)
                    self.assertIn("persist-credentials: false", text)
                if filename == "change-scope.yml":
                    self.assertIn("pull_request_target:", text)
                    self.assertIn("ref: ${{ github.event.pull_request.base.sha || github.sha }}", text)
                    self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", text)
                    self.assertIn(
                        'git -C candidate fetch --no-tags origin "${BASE_SHA}"',
                        text,
                    )
                    self.assertNotIn(
                        'git -C candidate fetch --no-tags --depth=1 origin "${BASE_SHA}"',
                        text,
                    )
                    self.assertNotIn("python3 candidate/", text)
                if filename == "pr-metadata.yml":
                    self.assertIn("pull_request_target:", text)
                    self.assertIn("ref: ${{ github.event.pull_request.base.sha || github.sha }}", text)
                    self.assertNotIn("python3 .guardrails-candidate/", text)

    def test_core_producers_use_exact_images_and_safe_modes(self) -> None:
        semgrep = (ROOT / "workflows/semgrep-ce.yml").read_text()
        gitleaks = (ROOT / "workflows/gitleaks.yml").read_text()
        self.assertIn(SEMGREP_IMAGE, semgrep)
        self.assertIn("semgrep scan", semgrep)
        self.assertNotIn("semgrep --test", semgrep)
        self.assertIn("semgrep scan --metrics off --config .guardrails/semgrep-rules.yml --json", semgrep)
        self.assertIn("semgrep scan --metrics off --error", semgrep)
        self.assertIn(".guardrails/semgrep-rules.yml", semgrep)
        self.assertIn(".guardrails/semgrep-tests/fixtures", semgrep)
        self.assertIn("security/semgrep/tests/fixtures", semgrep)
        self.assertNotIn("--config auto", semgrep)
        self.assertNotIn("semgrep ci", semgrep)
        self.assertIn(GITLEAKS_IMAGE, gitleaks)
        self.assertIn("fetch-depth: 0", gitleaks)
        self.assertIn(f"{GITLEAKS_IMAGE}\n          git --redact --no-banner .", gitleaks)
        self.assertNotIn(f"{GITLEAKS_IMAGE}\n          gitleaks git", gitleaks)
        combined = "\n".join(
            path.read_text()
            for directory in (ROOT / "tooling", ROOT / "workflows", ROOT / ".github/workflows", ROOT / ".guardrails")
            for path in directory.glob("*")
            if path.is_file() and path.suffix in {".py", ".yml", ".yaml"}
        )
        self.assertNotIn("gitleaks/gitleaks-action", combined)
        self.assertNotIn("semgrep ci", combined)
        self.assertNotIn("--config auto", combined)

    def test_repository_command_workflows_skip_when_unconfigured(self) -> None:
        contracts = {
            "build.yml": "GUARDRAILS_BUILD_COMMAND",
            "unit-tests.yml": "GUARDRAILS_UNIT_TEST_COMMAND",
            "changed-code-coverage.yml": "GUARDRAILS_CHANGED_COVERAGE_COMMAND",
        }
        for filename, variable in contracts.items():
            with self.subTest(filename=filename):
                text = (ROOT / "workflows" / filename).read_text()
                self.assertIn(f"vars.{variable} != ''", text)
                self.assertIn("GUARDRAILS_SETUP_COMMAND", text)
                self.assertIn("GUARDRAILS_WORKING_DIRECTORY", text)

    def test_changed_coverage_exports_the_exact_comparison_base(self) -> None:
        workflow = (ROOT / "workflows/changed-code-coverage.yml").read_text()

        self.assertIn(
            "GUARDRAILS_COVERAGE_BASE_REF: ${{ github.event.pull_request.base.sha || 'HEAD~1' }}",
            workflow,
        )

    def test_github_setting_verifiers_are_truthful_and_token_scoped(self) -> None:
        for filename in ("github-secret-protection.yml", "dependabot-verification.yml"):
            with self.subTest(filename=filename):
                text = (ROOT / "workflows" / filename).read_text()
                self.assertIn("SECURITY_SETTINGS_TOKEN", text)
                self.assertIn("conclusion=skipped", text)
                self.assertIn("pull_request_target:", text)
                self.assertNotIn("actions/checkout@", text)
                self.assertIn("github.event.pull_request.head.sha || github.sha", text)
                self.assertIn("GITHUB_SERVER_URL", text)
                self.assertIn("GITHUB_RUN_ID", text)
                self.assertIn("github.event_name", text)
                self.assertIn("github.event.pull_request.base.sha || github.sha", text)
                self.assertIn("github.event.pull_request.base.ref", text)
                self.assertIn("details_url", text)
                self.assertIn("external_id", text)
                for field in (
                    "run_id", "event", "base_sha", "base_ref", "head_sha",
                    "repository", "status",
                ):
                    self.assertRegex(text, rf"{field}:\(?\$")
                self.assertIn('provider_id:"github-', text)
                self.assertRegex(text, r"actions/upload-artifact@[0-9a-f]{40}")
                self.assertIn("guardrails-evidence.json", text)
                self.assertLess(text.index("actions/upload-artifact@"), text.index('"repos/${GITHUB_REPOSITORY}/check-runs"'))
                self.assertIn("if ", text)
                self.assertIn("gh api", text)
                if filename == "github-secret-protection.yml":
                    self.assertIn('if repository="$(GH_TOKEN=', text)
                    self.assertIn('if alerts="$(GH_TOKEN=', text)

    def test_scorecard_executes_only_trusted_base_runtime_with_token(self) -> None:
        for path in (
            ROOT / "workflows/guardrails-scorecard.yml",
            ROOT / ".github/workflows/guardrails-scorecard.yml",
        ):
            with self.subTest(path=path):
                text = path.read_text()
                self.assertIn("pull_request_target:", text)
                self.assertIn("actions: read", text)
                self.assertIn("path: .guardrails-trusted", text)
                self.assertIn("ref: ${{ github.event.pull_request.base.sha || github.sha }}", text)
                self.assertIn("path: .guardrails-candidate", text)
                self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", text)
                self.assertIn("repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}", text)
                self.assertIn("sparse-checkout:", text)
                self.assertIn("python3 .guardrails-trusted/.guardrails/github_evidence.py", text)
                self.assertIn("python3 .guardrails-trusted/.guardrails/scorecard.py", text)
                self.assertNotIn("python3 .guardrails-candidate/", text)
                self.assertEqual(
                    text.count("--policy .guardrails-candidate/.guardrails/policy.yaml"),
                    1,
                )
                self.assertIn("python3 .guardrails-trusted/.guardrails/configure.py", text)
                self.assertIn("--policy .guardrails-trusted/.guardrails/policy.yaml", text)
                for filename in ("profiles.yaml", "control-catalog.yaml", "providers.yaml"):
                    self.assertNotIn(f".guardrails-candidate/.guardrails/{filename}", text)
                    self.assertIn(f".guardrails-trusted/.guardrails/{filename}", text)
                self.assertIn("--trusted-base-revision", text)
                self.assertIn("--trusted-workflow-ref", text)
                self.assertIn("candidate Guardrails input must be a regular non-symlink file", text)

    def test_scorecard_writes_paired_timestamped_json_markdown_and_job_summary(self) -> None:
        text = (ROOT / "workflows/guardrails-scorecard.yml").read_text()

        self.assertIn('GUARDRAILS_TIMESTAMP="$(date -u +%Y%m%d-%H%M%SZ)"', text)
        self.assertIn("evidence-${GUARDRAILS_TIMESTAMP}.json", text)
        self.assertIn("scorecard-${GUARDRAILS_TIMESTAMP}.json", text)
        self.assertIn("scorecard-${GUARDRAILS_TIMESTAMP}.md", text)
        self.assertIn("--json", text)
        self.assertIn('cat "${SCORECARD_MARKDOWN}" >> "${GITHUB_STEP_SUMMARY}"', text)

    def test_scorecard_refreshes_when_pull_request_review_state_changes(self) -> None:
        text = (ROOT / "workflows/guardrails-scorecard.yml").read_text()

        self.assertIn("pull_request_review:", text)
        self.assertIn("types: [submitted, dismissed]", text)
        self.assertIn("concurrency:", text)
        self.assertIn(
            "group: guardrail-scorecard-${{ github.repository }}-${{ github.event.pull_request.number || github.ref }}",
            text,
        )
        self.assertIn("cancel-in-progress: true", text)
        self.assertIn(
            'grep -q -- "--pull-request-number"',
            text,
        )

    def test_pr_metadata_publishes_an_exact_head_policy_aware_check(self) -> None:
        text = (ROOT / "workflows/pr-metadata.yml").read_text()

        self.assertIn("pull_request_target:", text)
        self.assertIn("concurrency:", text)
        self.assertIn(
            "group: pr-metadata-${{ github.repository }}-${{ github.event.pull_request.number }}",
            text,
        )
        self.assertIn("cancel-in-progress: true", text)
        self.assertNotIn("actions: write", text)
        self.assertIn("checks: write", text)
        self.assertIn(
            "HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}",
            text,
        )
        self.assertIn("guardrails-pr-metadata-${{ github.run_id }}", text)
        self.assertIn(
            'external_id="guardrails:pr-metadata:${GITHUB_RUN_ID}:${HEAD_SHA}"',
            text,
        )
        self.assertIn('name:"PR Metadata",head_sha:$sha', text)
        self.assertIn('gh api --method POST "repos/${GITHUB_REPOSITORY}/check-runs"', text)
        self.assertIn("*:not_activated) conclusion=skipped", text)
        self.assertIn("failed:advisory) conclusion=neutral", text)
        self.assertIn("failed:enforced) conclusion=failure", text)
        self.assertIn("id: proof-upload", text)
        self.assertIn(
            "PROOF_UPLOAD_OUTCOME: ${{ steps.proof-upload.outcome }}",
            text,
        )
        self.assertIn(
            'if [[ "${PROOF_UPLOAD_OUTCOME}" != "success" ]]; then',
            text,
        )
        self.assertIn("conclusion=failure", text)
        self.assertIn("if: always()", text)
        self.assertLess(
            text.index("actions/upload-artifact@"),
            text.index('"repos/${GITHUB_REPOSITORY}/check-runs"'),
        )

    def test_repository_validation_runs_portable_and_optional_standards_validator(self) -> None:
        text = (ROOT / "workflows/repository-validation.yml").read_text()
        self.assertIn("python3 .guardrails/validators/validate_repository.py", text)
        self.assertIn("hashFiles('tooling/validators/validate_repository.py')", text)
        self.assertIn("python3 tooling/validators/validate_repository.py", text)

    def test_artifact_provenance_is_release_scoped_not_a_pr_commit_check(self) -> None:
        text = (ROOT / "workflows/artifact-provenance.yml").read_text()
        self.assertNotIn("pull_request:", text)
        self.assertIn("release:", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("attestations: write", text)
        self.assertIn("id-token: write", text)
        self.assertIn("subject-path:", text)

    def test_default_ruleset_does_not_claim_unactivated_checks(self) -> None:
        ruleset = json.loads((ROOT / "rulesets/default-branch-protection.json").read_text())
        required = [rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks"]
        self.assertEqual(required, [])


if __name__ == "__main__":
    unittest.main()
