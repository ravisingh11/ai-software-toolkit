"""Consumer acceptance for fresh defaults and legacy compatibility (hosted CI)."""
from __future__ import annotations

import json
import shutil
from unittest.mock import patch

from test_ai_toolkit_cli import CliFixture, run_cli
from ai_toolkit import cli, config, skills

STARTER_WORKFLOWS = {
    "proof-scorecard.yml", "repository-validation.yml", "change-scope.yml", "pr-metadata.yml",
    "build.yml", "unit-tests.yml", "changed-code-coverage.yml", "format-and-lint.yml",
    "migration-validation.yml", "semgrep-ce.yml", "gitleaks.yml",
}


class StarterInstallationTests(CliFixture):
    def workflows(self):
        return {p.name for p in (self.target / ".github/workflows").glob("*.yml")}

    def test_fresh_default_installs_exact_starter_and_advisory_core(self):
        code, out, err = self.init("--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.workflows(), STARTER_WORKFLOWS)
        configuration = config.read_configuration(self.target)
        lock = config.read_lock(self.target)
        self.assertEqual(configuration["toolkit"]["components"], ["proof", "skills"])
        self.assertEqual(configuration["toolkit"]["install_set"], "starter")
        self.assertEqual(lock["toolkit"]["install_set"], "starter")
        names = {p.name for p in (self.target / ".agents/skills").iterdir()}
        self.assertEqual(names, set(skills.STARTER_SKILLS) | {skills.SHARED_BUNDLE})
        policy = json.loads((self.target / ".proof/policy.yaml").read_text())
        profile = json.loads((self.target / ".proof/profiles.yaml").read_text())["profiles"]["core"]
        self.assertEqual(policy["profiles"], ["core"])
        self.assertEqual(len(profile["defaults"]["change"]), 12)
        self.assertEqual(set(profile["defaults"]["change"].values()), {"advisory"})
        self.assertEqual(len(json.loads((self.target / ".proof/control-catalog.yaml").read_text())["controls"]), 33)
        self.assertFalse((self.target / ".claude").exists())
        self.assertEqual(json.loads(out)["preview"]["install_set"], "starter")

    def test_proof_only_and_runtime_only_create_no_agent_directories(self):
        for install_set, no_actions in (("starter", False), ("full", True)):
            with self.subTest(install_set=install_set):
                target = self.root / install_set
                target.mkdir()
                arguments = ["init", "--target", str(target), "--components", "proof", "--install-set", install_set, "--yes"]
                if no_actions:
                    arguments.append("--no-actions")
                code, _, err = run_cli(*arguments)
                self.assertEqual(code, 0, err)
                self.assertTrue((target / ".proof/scan.py").is_file())
                self.assertFalse((target / ".agents").exists())
                self.assertFalse((target / ".claude").exists())
                self.assertEqual((target / ".github").exists(), not no_actions)

    def test_claude_only_populates_only_requested_client(self):
        code, _, err = run_cli("init", "--target", str(self.target), "--clients", "claude-code", "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.workflows(), STARTER_WORKFLOWS)
        self.assertFalse((self.target / ".agents").exists())
        self.assertTrue((self.target / ".claude/skills/prepare-safe-change/SKILL.md").is_file())
        code, _, err = run_cli("update", "--target", str(self.target), "--force")
        self.assertEqual(code, 0, err)
        self.assertFalse((self.target / ".agents").exists())

    def test_existing_unrelated_client_directory_is_still_a_fresh_toolkit_install(self):
        custom = self.target / ".claude/skills/code-review"
        custom.mkdir(parents=True)
        (custom / "SKILL.md").write_text("# Consumer skill\n")
        code, _, err = run_cli("init", "--target", str(self.target), "--clients", "claude-code", "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(config.read_lock(self.target)["toolkit"]["install_set"], "starter")
        self.assertFalse((self.target / ".agents").exists())
        self.assertEqual((custom / "SKILL.md").read_text(), "# Consumer skill\n")
        code, out, err = run_cli("update", "--target", str(self.target), "--force", "--json")
        self.assertEqual(code, 0, err)
        self.assertIn(".claude/skills/code-review/SKILL.md", json.loads(out)["classification"]["modified"])
        self.assertEqual((custom / "SKILL.md").read_text(), "# Consumer skill\n")

    def test_full_is_explicit_and_github_profile_remains_separate(self):
        self.assertEqual(self.init("--install-set", "full", "--components", "proof")[0], 0)
        self.assertEqual(self.workflows(), set(cli._installer().CORE_WORKFLOWS))
        self.assertFalse((self.target / ".agents").exists())
        self.assertFalse((self.target / ".github/workflows/codeql.yml").exists())
        self.assertFalse((self.target / ".github/workflows/proof-scorecard-badge.yml").exists())

    def test_reinit_update_and_rollback_keep_starter_and_custom_files(self):
        self.assertEqual(self.init("--skills", "code-review")[0], 0)
        custom = self.target / ".github/workflows/consumer.yml"
        custom.write_text("name: Consumer\n")
        policy = self.target / ".proof/policy.yaml"
        original_policy = policy.read_bytes()
        (self.target / ".proof/scan.py").unlink()
        self.assertEqual(self.init("--components", "proof")[0], 0)
        self.assertEqual(self.workflows(), STARTER_WORKFLOWS | {"consumer.yml"})
        with patch.object(cli, "revision", return_value="vNext"):
            code, _, err = run_cli("update", "--target", str(self.target), "--force")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.workflows(), STARTER_WORKFLOWS | {"consumer.yml"})
        self.assertEqual(policy.read_bytes(), original_policy)
        self.assertEqual(config.read_lock(self.target)["toolkit"]["install_set"], "starter")
        self.assertEqual(run_cli("update", "--target", str(self.target), "--rollback")[0], 0)
        self.assertEqual(config.read_lock(self.target)["toolkit"]["install_set"], "starter")
        self.assertEqual(custom.read_text(), "name: Consumer\n")

    def test_optional_workflow_adoption_survives_update(self):
        self.assertEqual(self.init()[0], 0)
        destination = self.target / ".github/workflows/trivy.yml"
        shutil.copy2(cli.ROOT / "workflows/trivy.yml", destination)
        self.assertEqual(run_cli("update", "--target", str(self.target), "--force")[0], 0)
        self.assertTrue(destination.is_file())
        self.assertFalse((self.target / ".github/workflows/lifecycle-verification.yml").exists())
        self.assertEqual(self.init("--install-set", "full")[0], 2)
        self.assertTrue(destination.is_file())

    def test_legacy_locked_unlocked_customized_and_partial_keep_full(self):
        for locked, partial in ((True, False), (False, False), (True, True), (False, True)):
            with self.subTest(locked=locked, partial=partial):
                target = self.root / f"legacy-{locked}-{partial}"
                target.mkdir()
                installer = cli._installer()
                installer.install(target, dry_run=False)
                configuration = config.default_configuration("vOld", components=["proof"], clients=["codex"])
                config.write_configuration(target, configuration)
                paths = cli.managed_files(target, configuration)
                if locked:
                    config.write_lock(target, config.build_lock("vOld", components=["proof"], managed=config.hash_managed(target, paths)))
                policy = target / ".proof/policy.yaml"
                policy_bytes = policy.read_bytes()
                custom = target / ".github/workflows/build.yml"
                custom.write_text("name: Consumer build\n")
                if partial:
                    (target / ".proof/scan.py").unlink()
                code, _, err = run_cli("update", "--target", str(target), "--force")
                self.assertEqual(code, 0, err)
                self.assertEqual(custom.read_text(), "name: Consumer build\n")
                self.assertEqual(policy.read_bytes(), policy_bytes)
                self.assertTrue((target / ".proof/scan.py").is_file())
                self.assertTrue((target / ".github/workflows/trivy.yml").is_file())
                self.assertTrue((target / ".github/workflows/lifecycle-verification.yml").is_file())
                self.assertNotIn("install_set", config.read_configuration(target)["toolkit"])
                self.assertNotIn("install_set", config.read_lock(target)["toolkit"])

    def test_records_round_trip_and_disagreement_is_read_only(self):
        self.assertEqual(self.init()[0], 0)
        lock = config.read_lock(self.target)
        lock["toolkit"]["install_set"] = "full"
        config.write_lock(self.target, lock)
        snapshot = {p.relative_to(self.target): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(run_cli("update", "--target", str(self.target), "--force")[0], 2)
        self.assertEqual(snapshot, {p.relative_to(self.target): p.read_bytes() for p in self.target.rglob("*") if p.is_file()})
