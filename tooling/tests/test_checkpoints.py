from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))
import checkpoints  # noqa: E402


class CheckpointPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / "repo"
        self.target.mkdir()
        shutil.copytree(ROOT / ".proof", self.target / ".proof", ignore=shutil.ignore_patterns("__pycache__"))
        self.git("init", "-q")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture")
        (self.target / "example.py").write_text("safe = True\n")
        self.git("add", "example.py")

    def git(self, *arguments):
        return subprocess.check_output(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", "-c", "maintenance.auto=false", "-c", "gc.auto=0", "-C", str(self.target), *arguments], text=True).strip()

    def inventory(self):
        return {str(p.relative_to(self.target)): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.target.rglob("*") if p.is_file()}

    def test_all_33_checks_and_policy_selection_remain_visible(self):
        value = checkpoints.plan(self.target, "pr")
        self.assertEqual(len(value["checks"]), 33)
        self.assertFalse(value["authorization_granted"])
        selected = [row for row in value["checks"] if row["selected"]]
        self.assertTrue(selected)
        self.assertTrue(all(row["authoritative_provider"] for row in selected))
        self.assertTrue(all(row["guide"] for row in value["checks"]))
        self.assertIn("approvals", value["platform_merge_requirements"])

    def test_partial_staging_uses_index_tree_without_writes(self):
        expected = self.git("write-tree")
        (self.target / "example.py").write_text("unstaged = True\n")
        (self.target / "ignored-private-data").write_text("do not read as evidence")
        before = self.inventory()
        value = checkpoints.plan(self.target, "pre-commit")
        self.assertEqual(value["subject"], {"type": "git-index", "revision": expected})
        self.assertEqual(self.inventory(), before)

    def test_tree_sorting_modes_and_deleted_files_match_git(self):
        (self.target / "a").mkdir()
        (self.target / "a/file").write_text("nested")
        (self.target / "a.txt").write_text("sibling")
        (self.target / "run.sh").write_text("#!/bin/sh\n")
        (self.target / "run.sh").chmod(0o755)
        self.git("add", ".")
        self.assertEqual(checkpoints.index_state(self.target)[0], self.git("write-tree"))
        self.git("rm", "--cached", "example.py")
        self.assertEqual(checkpoints.index_state(self.target)[0], self.git("write-tree"))

    def test_unborn_head_still_plans_exact_index_without_claiming_commit_evidence(self):
        target = self.target.parent / "unborn"
        target.mkdir()
        shutil.copytree(ROOT / ".proof", target / ".proof", ignore=shutil.ignore_patterns("__pycache__"))
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        (target / "first.py").write_text("first = True\n")
        subprocess.run(["git", "-C", str(target), "add", "."], check=True)
        expected = subprocess.check_output(["git", "-C", str(target), "write-tree"], text=True).strip()
        before = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob("*") if p.is_file()}
        value = checkpoints.plan(target, "pre-commit")
        self.assertEqual(value["subject"], {"type": "git-index", "revision": expected})
        self.assertNotIn("source_revision", value)
        self.assertEqual(len(value["checks"]), 33)
        self.assertFalse(any(row["existing_evidence"]["matches_commit"] for row in value["checks"]))
        self.assertEqual({str(p.relative_to(target)): p.read_bytes() for p in target.rglob("*") if p.is_file()}, before)
        self.assertIsNone(checkpoints.plan(target, "post-commit")["subject"])

    def test_intent_to_add_is_blocked_without_confusing_a_staged_empty_file(self):
        (self.target / "pending.py").write_text("not staged yet\n")
        self.git("add", "-N", "pending.py")
        before = self.inventory()
        with self.assertRaisesRegex(ValueError, "Intent-to-add"):
            checkpoints.index_state(self.target)
        self.assertIsNone(checkpoints.plan(self.target, "pre-commit")["subject"])
        self.assertEqual(self.inventory(), before)
        self.git("add", "pending.py")
        (self.target / "empty.txt").write_bytes(b"")
        self.git("add", "empty.txt")
        self.assertEqual(checkpoints.index_state(self.target)[0], self.git("write-tree"))

    def test_does_not_execute_target_helpers_or_credentials(self):
        (self.target / ".proof/evaluate.py").write_text("raise RuntimeError('target code executed')\n")
        with patch.dict(os.environ, {"PROVIDER_TOKEN": "credential-value-must-not-be-used"}), patch.object(checkpoints, "shutil") as tools:
            tools.which.return_value = None
            value = checkpoints.plan(self.target, "pre-commit")
        self.assertEqual(len(value["checks"]), 33)
        self.assertNotIn("credential-value-must-not-be-used", json.dumps(value))

    def test_missing_invalid_contracts_never_appear_passing(self):
        (self.target / ".proof/policy.yaml").write_text('{"bad":true}')
        value = checkpoints.plan(self.target, "pr")
        self.assertEqual(value["checks"], [])
        self.assertTrue(value["gaps"])
        self.assertFalse(value["authorization_granted"])

    def test_release_and_runtime_do_not_infer_artifact_or_environment_from_head(self):
        for checkpoint in ("release", "deployment", "runtime"):
            value = checkpoints.plan(self.target, checkpoint)
            self.assertIsNone(value["subject"])
            self.assertEqual(value["operation"], "release")
            self.assertTrue(value["gaps"])

    def test_symlinked_contract_and_index_symlink_reject(self):
        config = self.target / ".proof/policy.yaml"
        config.unlink()
        config.symlink_to(ROOT / ".proof/policy.yaml")
        self.assertEqual(checkpoints.plan(self.target, "pr")["checks"], [])
        link = self.target / "link"
        link.symlink_to("example.py")
        self.git("add", "link")
        with self.assertRaises(ValueError):
            checkpoints.index_state(self.target)

    def test_planner_reports_evidence_subject_without_authenticating_file(self):
        evidence = self.target / ".artifacts/proof/evidence.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text(json.dumps({"version": 2, "subject": {"type": "git-commit", "revision": "a" * 40}, "results": {}}))
        row = checkpoints.plan(self.target, "pr")["checks"][0]
        self.assertEqual(row["existing_evidence"]["status"], "not_run")
        self.assertFalse(row["existing_evidence"]["matches_commit"])
        self.assertFalse(row["existing_evidence"]["provider_authority_authenticated"])


if __name__ == "__main__":
    unittest.main()
