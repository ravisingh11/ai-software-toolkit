from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))

from ai_toolkit import skills  # noqa: E402
from ai_toolkit.runtime import ToolkitError  # noqa: E402


class SkillInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve()
        self.destination = self.target / ".agents" / "skills"

    def test_canonical_and_resolution(self):
        names = skills.canonical_skills()
        self.assertIn("toolkit-setup", names)
        self.assertIn("qa-bootstrap", names)
        self.assertEqual(skills.resolve_skills(["all"]), names)
        starter = skills.resolve_skills(["starter"])
        self.assertTrue(starter and all(name in names for name in starter))
        self.assertEqual(skills.resolve_skills(["code-review", "code-review"]), ["code-review"])
        with self.assertRaises(ToolkitError):
            skills.resolve_skills(["does-not-exist"])
        with self.assertRaises(ToolkitError):
            skills.skill_files("does-not-exist")

    def test_client_directories(self):
        environment = {"HOME": str(self.target), "CODEX_HOME": str(self.target / "cx")}
        self.assertEqual(skills.client_user_dir("codex", environment), self.target / "cx" / "skills")
        self.assertEqual(skills.client_user_dir("claude-code", environment), self.target / ".claude" / "skills")
        self.assertEqual(skills.client_project_dir("claude-code", self.target), self.target / ".claude" / "skills")
        with self.assertRaises(ToolkitError):
            skills.client_user_dir("emacs", environment)
        with self.assertRaises(ToolkitError):
            skills.client_project_dir("emacs", self.target)

    def test_install_skip_merge_replace(self):
        rows = skills.install_skills(["toolkit-setup"], self.destination)
        self.assertEqual([row["skill"] for row in rows], ["toolkit-setup", "_shared-project-ops"])
        self.assertEqual(rows[0]["action"], "install")
        self.assertTrue((self.destination / "toolkit-setup" / "SKILL.md").is_file())
        self.assertTrue((self.destination / "_shared-project-ops").is_dir())

        skill_file = self.destination / "toolkit-setup" / "SKILL.md"
        skill_file.write_text("local edit\n", encoding="utf-8")
        extra = self.destination / "toolkit-setup" / "notes.md"
        extra.write_text("mine\n", encoding="utf-8")
        (self.destination / "toolkit-setup" / "agents" / "openai.yaml").unlink()

        rows = skills.install_skills(["toolkit-setup"], self.destination, existing="skip")
        self.assertEqual(rows[0]["action"], "skip")
        self.assertEqual(skill_file.read_text(encoding="utf-8"), "local edit\n")

        rows = skills.install_skills(["toolkit-setup"], self.destination, existing="merge")
        self.assertEqual(rows[0]["action"], "merge")
        self.assertEqual(skill_file.read_text(encoding="utf-8"), "local edit\n")
        self.assertTrue((self.destination / "toolkit-setup" / "agents" / "openai.yaml").is_file())
        self.assertEqual(rows[0]["files"], ["toolkit-setup/agents/openai.yaml"])

        rows = skills.install_skills(["toolkit-setup"], self.destination, existing="replace")
        self.assertEqual(rows[0]["action"], "replace")
        self.assertNotEqual(skill_file.read_text(encoding="utf-8"), "local edit\n")
        self.assertFalse(extra.exists())

        with self.assertRaises(ToolkitError):
            skills.install_skills(["toolkit-setup"], self.destination, existing="clobber")

    def test_dry_run_writes_nothing(self):
        rows = skills.install_skills(["code-review"], self.destination, dry_run=True)
        self.assertFalse(self.destination.exists())
        self.assertTrue(rows[0]["files"])

    def test_refuses_non_directory_and_symlink_destinations(self):
        self.destination.mkdir(parents=True)
        (self.destination / "code-review").write_text("file", encoding="utf-8")
        with self.assertRaises(ToolkitError):
            skills.install_skills(["code-review"], self.destination)
        (self.destination / "code-review").unlink()
        outside = self.target / "outside"
        outside.mkdir()
        os.symlink(outside, self.destination / "code-review")
        with self.assertRaises(ToolkitError):
            skills.install_skills(["code-review"], self.destination, existing="merge")

    def test_managed_skill_files(self):
        self.assertEqual(skills.managed_skill_files(self.target, self.destination), [])
        skills.install_skills(["toolkit-setup"], self.destination)
        (self.destination / "my-own-skill").mkdir()
        (self.destination / "my-own-skill" / "SKILL.md").write_text("mine", encoding="utf-8")
        managed = skills.managed_skill_files(self.target, self.destination)
        self.assertIn(".agents/skills/toolkit-setup/SKILL.md", managed)
        self.assertTrue(any(path.startswith(".agents/skills/_shared-project-ops/") for path in managed))
        self.assertFalse(any("my-own-skill" in path for path in managed))


if __name__ == "__main__":
    unittest.main()
