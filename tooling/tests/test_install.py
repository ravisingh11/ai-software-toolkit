from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "install.py"
SPEC = importlib.util.spec_from_file_location("guardrails_v2_install", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

CORE_WORKFLOWS = {
    "guardrails-scorecard.yml",
    "change-scope.yml",
    "repository-validation.yml",
    "build.yml",
    "unit-tests.yml",
    "changed-code-coverage.yml",
    "format-and-lint.yml",
    "migration-validation.yml",
    "pr-metadata.yml",
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
BADGE_FILES = {
    ".guardrails/render_scorecard_badge.py": "tooling/render_scorecard_badge.py",
    ".guardrails/reconcile_scorecard_badge.py": "tooling/reconcile_scorecard_badge.py",
    ".github/workflows/guardrails-scorecard-badge.yml": "workflows/guardrails-scorecard-badge.yml",
}
CANONICAL_DISTRIBUTION = {
    ".guardrails/policy.yaml": "guardrails/baseline.yaml",
    ".guardrails/profiles.yaml": "policies/profiles.yaml",
    ".guardrails/control-catalog.yaml": "policies/control-catalog.yaml",
    ".guardrails/providers.yaml": "policies/provider-config.yaml",
    ".guardrails/policy.schema.json": "guardrails/policy.schema.json",
    ".guardrails/evidence.schema.json": "guardrails/evidence.schema.json",
    ".guardrails/profiles.schema.json": "guardrails/profiles.schema.json",
    ".guardrails/providers.schema.json": "guardrails/providers.schema.json",
    ".guardrails/control-catalog.schema.json": "guardrails/control-catalog.schema.json",
    ".guardrails/documentation.yaml": "guardrails/defaults/documentation.yaml",
    ".guardrails/change-scope.yaml": "guardrails/defaults/change-scope.yaml",
    ".guardrails/pr-metadata.yaml": "guardrails/defaults/pr-metadata.yaml",
    ".guardrails/ground-truth-ai.yaml": "guardrails/defaults/ground-truth-ai.yaml",
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


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class InstallerTests(unittest.TestCase):
    def workflows(self, target: Path) -> set[str]:
        directory = target / ".github" / "workflows"
        return {path.name for path in directory.glob("*.yml")} if directory.exists() else set()

    def test_default_install_is_runnable_core_with_actions_and_no_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)

            MODULE.install(target, dry_run=False)

            policy = json.loads((target / ".guardrails/policy.yaml").read_text())
            self.assertEqual(policy["version"], 2)
            self.assertEqual(policy["profiles"], ["core"])
            self.assertEqual(self.workflows(target), CORE_WORKFLOWS)
            for installed in BADGE_FILES:
                self.assertFalse((target / installed).exists())
            self.assertFalse((target / ".guardrails/producer-manifest.json").exists())
            for installed, source in CANONICAL_DISTRIBUTION.items():
                with self.subTest(installed=installed):
                    self.assertEqual(
                        (target / installed).read_bytes(),
                        (MODULE.ROOT / source).read_bytes(),
                    )

    def test_scorecard_badge_opt_in_installs_exact_optional_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)

            MODULE.install(target, dry_run=False, scorecard_badge=True)

            self.assertEqual(
                self.workflows(target),
                CORE_WORKFLOWS | {"guardrails-scorecard-badge.yml"},
            )
            for installed, source in BADGE_FILES.items():
                with self.subTest(installed=installed):
                    self.assertEqual(
                        (target / installed).read_bytes(),
                        (MODULE.ROOT / source).read_bytes(),
                    )

    def test_existing_install_requires_refresh_to_add_scorecard_badge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False)

            with self.assertRaisesRegex(ValueError, "refresh-existing"):
                MODULE.install(target, dry_run=False, scorecard_badge=True)

            for installed in BADGE_FILES:
                self.assertFalse((target / installed).exists())

    def test_refresh_detects_and_repairs_installer_owned_scorecard_badge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, scorecard_badge=True)
            for installed in BADGE_FILES:
                (target / installed).write_text(
                    (
                        MODULE.INSTALLER_MARKER
                        if installed.endswith(".yml")
                        else "#!/usr/bin/env python3\n" + MODULE.RUNTIME_MARKER
                    )
                    + "\nmutated\n",
                    encoding="utf-8",
                )

            MODULE.install(target, dry_run=False, refresh_existing=True)

            for installed, source in BADGE_FILES.items():
                with self.subTest(installed=installed):
                    self.assertEqual(
                        (target / installed).read_bytes(),
                        (MODULE.ROOT / source).read_bytes(),
                    )

    def test_scorecard_badge_refuses_unowned_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False)
            workflow = target / ".github/workflows/guardrails-scorecard-badge.yml"
            workflow.write_text("name: Consumer workflow\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not installer-owned"):
                MODULE.install(
                    target,
                    dry_run=False,
                    refresh_existing=True,
                    scorecard_badge=True,
                )

            self.assertEqual(workflow.read_text(), "name: Consumer workflow\n")

    def test_scorecard_badge_removal_is_explicit_and_owned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, scorecard_badge=True)
            unrelated = target / ".github/workflows/consumer.yml"
            unrelated.write_text("name: Consumer\n", encoding="utf-8")
            core_workflow = target / ".github/workflows/build.yml"
            core_workflow.write_text("name: Consumer build\n", encoding="utf-8")

            dry_run = MODULE.install(
                target,
                dry_run=True,
                refresh_existing=True,
                remove_scorecard_badge=True,
            )
            resolved_target = target.resolve()
            self.assertEqual(
                {
                    item.destination.relative_to(resolved_target).as_posix()
                    for item in dry_run
                    if item.kind == "remove"
                },
                set(BADGE_FILES),
            )
            MODULE.install(
                target,
                dry_run=False,
                refresh_existing=True,
                remove_scorecard_badge=True,
            )

            for installed in BADGE_FILES:
                self.assertFalse((target / installed).exists())
            self.assertEqual(unrelated.read_text(), "name: Consumer\n")
            self.assertEqual(core_workflow.read_text(), "name: Consumer build\n")
            self.assertEqual(self.workflows(target), CORE_WORKFLOWS | {"consumer.yml"})

    def test_scorecard_badge_removal_refuses_unowned_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, scorecard_badge=True)
            runtime = target / ".guardrails/render_scorecard_badge.py"
            runtime.write_text("consumer owned\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not installer-owned"):
                MODULE.install(
                    target,
                    dry_run=False,
                    refresh_existing=True,
                    remove_scorecard_badge=True,
                )

            self.assertEqual(runtime.read_text(), "consumer owned\n")
            self.assertTrue(
                (target / ".github/workflows/guardrails-scorecard-badge.yml").exists()
            )

    def test_scorecard_badge_removal_refuses_dangling_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, scorecard_badge=True)
            runtime = target / ".guardrails/render_scorecard_badge.py"
            runtime.unlink()
            runtime.symlink_to(target / "missing-renderer.py")

            with self.assertRaisesRegex(ValueError, "not installer-owned|symlink"):
                MODULE.install(
                    target,
                    dry_run=False,
                    refresh_existing=True,
                    remove_scorecard_badge=True,
                )

            self.assertTrue(runtime.is_symlink())

    def test_scorecard_badge_options_reject_invalid_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaisesRegex(ValueError, "cannot be combined"):
                MODULE.install(
                    target,
                    dry_run=True,
                    scorecard_badge=True,
                    remove_scorecard_badge=True,
                )
            with self.assertRaisesRegex(ValueError, "requires GitHub Actions"):
                MODULE.install(
                    target,
                    dry_run=True,
                    no_actions=True,
                    scorecard_badge=True,
                )
            with self.assertRaisesRegex(ValueError, "requires --refresh-existing"):
                MODULE.install(
                    target,
                    dry_run=True,
                    remove_scorecard_badge=True,
                )

    def test_scorecard_badge_removal_dry_run_prints_remove_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, scorecard_badge=True)

            completed = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--target",
                    str(target),
                    "--refresh-existing",
                    "--remove-scorecard-badge",
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.count("- remove:"), 3)

    def test_fresh_core_collector_and_scorecard_ignore_default_disabled_vendors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False)
            policy = json.loads((target / ".guardrails/policy.yaml").read_text())
            profiles = json.loads((target / ".guardrails/profiles.yaml").read_text())
            catalog = json.loads((target / ".guardrails/control-catalog.yaml").read_text())
            providers = json.loads((target / ".guardrails/providers.yaml").read_text())
            collector = load_module(target / ".guardrails/github_evidence.py", "fresh_guardrails_collector")
            scorecard = load_module(target / ".guardrails/scorecard.py", "fresh_guardrails_scorecard")

            expected = collector.expected_checks(policy, profiles, catalog, providers, "change")
            self.assertEqual(
                set(expected),
                {
                    "Validate / repository",
                    "Validate / docs",
                    "Validate / ground truth",
                    "PR Change Scope",
                    "Build",
                    "Unit Tests",
                    "Changed Code Coverage",
                    "Format and Lint",
                    "Migration Validation",
                    "Semgrep CE",
                    "Gitleaks",
                },
            )
            evidence = {
                "version": 2,
                "subject": {"type": "git-commit", "revision": "abc123"},
                "results": {
                    control_id: {
                        contract["provider_id"]: {
                            "producer": contract["check_name"],
                            "status": "not_run",
                            "reason": "fresh consumer fixture",
                        }
                    }
                    for contract in expected.values()
                    for control_id in contract["control_ids"]
                },
            }
            card = scorecard.scorecard(
                policy, profiles, catalog, providers, evidence, "change", "abc123",
                subject_type="git-commit",
            )
            rendered = scorecard.render(card)

            self.assertTrue(all(control["supplemental"] == [] for control in card["controls"]))
            self.assertNotIn("supplemental:", rendered)
            for vendor in ("SonarQube", "Semgrep App", "Snyk", "FOSSA"):
                self.assertNotIn(vendor, rendered)

    def test_fresh_install_distributes_semgrep_self_tests_and_portable_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, no_actions=True)

            fixtures = target / ".guardrails/semgrep-tests/fixtures"
            self.assertTrue(fixtures.is_dir())
            self.assertEqual(
                {path.relative_to(fixtures) for path in fixtures.rglob("*") if path.is_file()},
                {
                    path.relative_to(MODULE.ROOT / "security/semgrep/tests/fixtures")
                    for path in (MODULE.ROOT / "security/semgrep/tests/fixtures").rglob("*")
                    if path.is_file()
                },
            )
            completed = subprocess.run(
                ["python3", ".guardrails/validators/validate_repository.py"],
                cwd=target,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_portable_validator_rejects_missing_pr_metadata_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, no_actions=True)
            (target / ".guardrails/validators/validate_pr_metadata.py").unlink()

            completed = subprocess.run(
                ["python3", ".guardrails/validators/validate_repository.py"],
                cwd=target,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "validators/validate_pr_metadata.py",
                completed.stdout + completed.stderr,
            )

    def test_installed_prepare_safe_change_skill_executes_v2_evaluator_example(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, no_actions=True)
            skill_root = target / ".agents/skills/prepare-safe-change"
            installed_skill = skill_root / "SKILL.md"
            installed_example = skill_root / "references/evidence-example.yaml"
            canonical_example = MODULE.ROOT / "skills/prepare-safe-change/references/evidence-example.yaml"
            self.assertTrue(canonical_example.is_file())
            self.assertTrue(installed_example.is_file())
            self.assertEqual(installed_example.read_bytes(), canonical_example.read_bytes())
            skill_text = installed_skill.read_text()
            self.assertIn("~~~sh\n", skill_text)
            script = skill_text.split("~~~sh\n", 1)[1].split("~~~", 1)[0]
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
            subprocess.run(["git", "add", "."], cwd=target, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=target, check=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=target, check=True,
                text=True, capture_output=True,
            ).stdout.strip()
            evidence = json.loads(installed_example.read_text(encoding="utf-8"))
            evidence["subject"]["revision"] = revision
            populated_evidence = target / "evidence.json"
            populated_evidence.write_text(json.dumps(evidence), encoding="utf-8")

            completed = subprocess.run(
                ["sh", "-c", script],
                cwd=target,
                env={
                    "PATH": "/usr/bin:/bin",
                    "EXACT_REVISION": revision,
                    "GUARDRAILS_EVIDENCE": str(populated_evidence),
                },
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn(f"ALLOW change git-commit@{revision}", completed.stdout)

            missing = subprocess.run(
                ["sh", "-c", script],
                cwd=target,
                env={"PATH": "/usr/bin:/bin", "EXACT_REVISION": revision},
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("GUARDRAILS_EVIDENCE", missing.stderr)

    def test_github_profile_is_additive_and_installs_only_the_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)

            MODULE.install(target, dry_run=False, profiles=["github"])

            policy = json.loads((target / ".guardrails/policy.yaml").read_text())
            self.assertEqual(policy["profiles"], ["core", "github"])
            self.assertEqual(self.workflows(target), CORE_WORKFLOWS | GITHUB_WORKFLOWS)
            for filename in CORE_WORKFLOWS | GITHUB_WORKFLOWS:
                with self.subTest(filename=filename):
                    self.assertEqual(
                        (target / ".github/workflows" / filename).read_bytes(),
                        (MODULE.ROOT / "workflows" / filename).read_bytes(),
                    )

    def test_no_actions_installs_local_runtime_and_no_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)

            MODULE.install(target, dry_run=False, no_actions=True)

            self.assertTrue((target / ".guardrails/produce.py").is_file())
            self.assertTrue((target / ".guardrails/semgrep-rules.yml").is_file())
            self.assertEqual(self.workflows(target), set())

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)

            plan = MODULE.install(target, dry_run=True)

            self.assertTrue(any(item.destination.name == "guardrails-scorecard.yml" for item in plan))
            self.assertFalse((target / ".guardrails").exists())
            self.assertFalse((target / ".github").exists())

    def test_rejects_v1_policy_manifest_and_runtime_without_modifying_them(self) -> None:
        fixtures = {
            ".guardrails/policy.yaml": '{"version": 1}\n',
            ".guardrails/producer-manifest.json": '{"version": 1}\n',
            ".agentic-guardrails/evaluate.py": "# v1 runtime\n",
        }
        for relative, content in fixtures.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                legacy = target / relative
                legacy.parent.mkdir(parents=True)
                legacy.write_text(content)

                with self.assertRaisesRegex(ValueError, "Guardrails v1.*clean reinstall"):
                    MODULE.install(target, dry_run=False)

                self.assertEqual(legacy.read_text(), content)
                self.assertFalse((target / ".guardrails/profiles.yaml").exists())

    def test_merge_existing_preserves_consumer_files_and_installs_missing_product_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            readme = target / "README.md"
            policy = target / ".guardrails/policy.yaml"
            policy.parent.mkdir(parents=True)
            readme.write_text("consumer\n")
            policy.write_text(json.dumps({"version": 2, "profiles": ["core"], "overrides": {"change": {}, "release": {}}}) + "\n")

            MODULE.install(target, dry_run=False, merge_existing=True)

            self.assertEqual(readme.read_text(), "consumer\n")
            self.assertEqual(json.loads(policy.read_text())["profiles"], ["core"])
            self.assertTrue((target / ".guardrails/produce.py").is_file())

    def test_merge_existing_github_profile_updates_policy_and_installs_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            policy = target / ".guardrails/policy.yaml"
            policy.parent.mkdir(parents=True)
            original = {
                "$schema": "./policy.schema.json",
                "version": 2,
                "name": "consumer-policy",
                "profiles": ["core"],
                "overrides": {"change": {"build": "enforced"}, "release": {}},
            }
            policy.write_text(json.dumps(original, indent=2) + "\n")

            MODULE.install(
                target,
                dry_run=False,
                profiles=["github"],
                merge_existing=True,
            )

            installed = json.loads(policy.read_text())
            self.assertEqual(installed, {**original, "profiles": ["core", "github"]})
            self.assertEqual(self.workflows(target), CORE_WORKFLOWS | GITHUB_WORKFLOWS)

    def test_rejects_symlink_destination_before_refresh_without_touching_external_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external_directory:
            target = Path(directory)
            external = Path(external_directory) / "produce.py"
            external.write_text("external\n")
            destination = target / ".guardrails/produce.py"
            destination.parent.mkdir(parents=True)
            destination.symlink_to(external)

            with self.assertRaisesRegex(ValueError, "symlink"):
                MODULE.install(target, dry_run=False, refresh_existing=True)

            self.assertEqual(external.read_text(), "external\n")
            self.assertFalse((target / ".guardrails/profiles.yaml").exists())

    def test_rejects_symlink_parent_before_merge_without_touching_external_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external_directory:
            target = Path(directory)
            external_root = Path(external_directory)
            external = external_root / "policy.yaml"
            external.write_text('{"version": 2, "sentinel": "external"}\n')
            (target / ".guardrails").symlink_to(external_root, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symlink"):
                MODULE.install(
                    target,
                    dry_run=False,
                    profiles=["github"],
                    merge_existing=True,
                )

            self.assertEqual(external.read_text(), '{"version": 2, "sentinel": "external"}\n')
            self.assertFalse((external_root / "profiles.yaml").exists())

    def test_refresh_updates_installer_owned_runtime_but_preserves_policy_and_unmarked_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False)
            policy = target / ".guardrails/policy.yaml"
            policy.write_text(json.dumps({"version": 2, "profiles": ["core"], "overrides": {"change": {"build": "enforced"}, "release": {}}}) + "\n")
            runtime = target / ".guardrails/produce.py"
            runtime.write_text("stale\n")
            workflow = target / ".github/workflows/build.yml"
            workflow.write_text("name: Consumer Build\n")

            MODULE.install(target, dry_run=False, refresh_existing=True)

            self.assertEqual(json.loads(policy.read_text())["overrides"]["change"]["build"], "enforced")
            self.assertEqual(runtime.read_bytes(), MODULE.PRODUCER.read_bytes())
            self.assertEqual(workflow.read_text(), "name: Consumer Build\n")

    def test_refresh_updates_builtins_and_preserves_custom_providers_and_selections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False)
            providers_path = target / ".guardrails/providers.yaml"
            providers = json.loads(providers_path.read_text())
            custom = dict(providers["providers"]["repository-build"])
            custom["display_name"] = "Consumer Build Adapter"
            providers["providers"]["consumer-build"] = custom
            providers["providers"]["repository-build"]["display_name"] = "Stale Built-in"
            providers["providers"]["repository-build"]["checks"]["build"]["trusted_paths"] = [
                "tools/build.py"
            ]
            providers["selections"]["build"] = {
                "authoritative": "consumer-build",
                "supplemental": ["repository-build"],
            }
            del providers["selections"]["runtime-soak"]
            providers_path.write_text(json.dumps(providers, indent=2) + "\n")

            MODULE.install(target, dry_run=False, refresh_existing=True)

            refreshed = json.loads(providers_path.read_text())
            canonical = json.loads(
                (MODULE.ROOT / "policies/provider-config.yaml").read_text()
            )
            expected_build = canonical["providers"]["repository-build"]
            expected_build["checks"]["build"]["trusted_paths"] = ["tools/build.py"]
            self.assertEqual(refreshed["providers"]["repository-build"], expected_build)
            self.assertEqual(
                refreshed["providers"]["consumer-build"]["display_name"],
                "Consumer Build Adapter",
            )
            self.assertEqual(
                refreshed["selections"]["build"],
                {
                    "authoritative": "consumer-build",
                    "supplemental": ["repository-build"],
                },
            )
            self.assertEqual(
                refreshed["selections"]["runtime-soak"],
                canonical["selections"]["runtime-soak"],
            )

    def test_refresh_rejects_invalid_merged_provider_document_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False)
            providers_path = target / ".guardrails/providers.yaml"
            providers = json.loads(providers_path.read_text())
            providers["providers"]["consumer-build"] = {
                "display_name": "Invalid Consumer Build"
            }
            providers_path.write_text(json.dumps(providers, indent=2) + "\n")
            original = providers_path.read_bytes()

            with self.assertRaisesRegex(ValueError, "consumer-build"):
                MODULE.install(target, dry_run=False, refresh_existing=True)

            self.assertEqual(providers_path.read_bytes(), original)

    def test_refresh_unions_explicit_core_with_installed_github_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, profiles=["github"])
            policy = target / ".guardrails/policy.yaml"
            workflow = target / ".github/workflows/github-secret-protection.yml"
            workflow.write_text("# Guardrails v2 installer-owned workflow.\nname: Mutated\n")

            MODULE.install(
                target,
                dry_run=False,
                profiles=["core"],
                refresh_existing=True,
            )

            self.assertEqual(
                workflow.read_bytes(),
                MODULE.GITHUB_WORKFLOWS["github-secret-protection.yml"].read_bytes(),
            )
            self.assertEqual(json.loads(policy.read_text())["profiles"], ["core", "github"])

    def test_refresh_repairs_known_directory_files_without_removing_consumer_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            MODULE.install(target, dry_run=False, no_actions=True)
            mutated_fixture = target / ".guardrails/semgrep-tests/fixtures/safe/requests.py"
            removed_fixture = target / ".guardrails/semgrep-tests/fixtures/unsafe/tls.js"
            consumer_fixture = target / ".guardrails/semgrep-tests/fixtures/consumer-case.txt"
            mutated_skill = target / ".agents/skills/prepare-safe-change/SKILL.md"
            removed_skill = target / ".agents/skills/prepare-safe-change/agents/openai.yaml"
            consumer_skill = target / ".agents/skills/prepare-safe-change/consumer-notes.md"
            mutated_fixture.write_text("mutated fixture\n")
            removed_fixture.unlink()
            consumer_fixture.write_text("consumer fixture\n")
            mutated_skill.write_text("mutated skill\n")
            removed_skill.unlink()
            consumer_skill.write_text("consumer skill\n")

            MODULE.install(target, dry_run=False, no_actions=True, refresh_existing=True)

            self.assertEqual(
                mutated_fixture.read_bytes(),
                (MODULE.ROOT / "security/semgrep/tests/fixtures/safe/requests.py").read_bytes(),
            )
            self.assertEqual(
                removed_fixture.read_bytes(),
                (MODULE.ROOT / "security/semgrep/tests/fixtures/unsafe/tls.js").read_bytes(),
            )
            self.assertEqual(consumer_fixture.read_text(), "consumer fixture\n")
            self.assertEqual(
                mutated_skill.read_bytes(),
                (MODULE.ROOT / "skills/prepare-safe-change/SKILL.md").read_bytes(),
            )
            self.assertEqual(
                removed_skill.read_bytes(),
                (MODULE.ROOT / "skills/prepare-safe-change/agents/openai.yaml").read_bytes(),
            )
            self.assertEqual(consumer_skill.read_text(), "consumer skill\n")

    def test_existing_local_hook_config_is_preserved_and_requires_manual_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            config = target / ".pre-commit-config.yaml"
            config.write_text("consumer hooks\n")

            with self.assertRaisesRegex(ValueError, "manual merge"):
                MODULE.install(target, dry_run=False, local_hooks=True)

            self.assertEqual(config.read_text(), "consumer hooks\n")
            self.assertFalse((target / ".guardrails").exists())

    def test_local_hooks_validate_then_install_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            real_run = subprocess.run

            def run(command, **kwargs):
                if command[:2] == ["git", "rev-parse"]:
                    return real_run(command, **kwargs)
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/pre-commit"), mock.patch.object(
                MODULE.subprocess, "run", side_effect=run
            ) as run:
                MODULE.install(target, dry_run=False, no_actions=True, local_hooks=True)

            config = (target / ".pre-commit-config.yaml").read_text()
            self.assertIn(MODULE.SEMGREP_IMAGE, config)
            self.assertIn("semgrep scan --error", config)
            self.assertIn("--exclude .guardrails/semgrep-tests/fixtures", config)
            self.assertIn("--exclude security/semgrep/tests/fixtures", config)
            self.assertIn(MODULE.GITLEAKS_IMAGE, config)
            self.assertIn(f"entry: {MODULE.GITLEAKS_IMAGE} git --redact --no-banner .", config)
            self.assertNotIn(f"entry: {MODULE.GITLEAKS_IMAGE} gitleaks git", config)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertTrue(any(command[1] == "validate-config" for command in commands))
            install = next(command for command in commands if command[1] == "install")
            self.assertNotIn("--overwrite", install)

    def test_local_hook_preconditions_fail_before_product_files_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with mock.patch.object(MODULE.shutil, "which", return_value=None):
                with self.assertRaisesRegex(ValueError, "pre-commit executable"):
                    MODULE.install(target, dry_run=False, local_hooks=True)
            self.assertFalse((target / ".guardrails").exists())

    def test_local_hooks_reject_nested_target_without_touching_parent_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=parent, check=True)
            nested = parent / "nested"
            nested.mkdir()
            parent_hook = parent / ".git/hooks/pre-commit"
            parent_hook.write_text("parent hook\n")
            real_run = subprocess.run

            def run(command, **kwargs):
                if command[:2] == ["git", "rev-parse"]:
                    return real_run(command, **kwargs)
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/pre-commit"), mock.patch.object(
                MODULE.subprocess, "run", side_effect=run
            ):
                with self.assertRaisesRegex(ValueError, "exact Git repository root"):
                    MODULE.install(nested, dry_run=False, no_actions=True, local_hooks=True)

            self.assertEqual(parent_hook.read_text(), "parent hook\n")
            self.assertFalse((nested / ".guardrails").exists())
            self.assertFalse((nested / ".pre-commit-config.yaml").exists())


if __name__ == "__main__":
    unittest.main()
