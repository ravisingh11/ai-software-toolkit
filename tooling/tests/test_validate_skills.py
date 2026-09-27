from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "validate-skills.py"


def load():
    spec = importlib.util.spec_from_file_location("validate_skills", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ActionSkillValidationTests(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.skills = root / "skills"
        self.fixtures = root / "fixtures"
        shutil.copytree(ROOT / "skills" / "fix-ci", self.skills / "fix-ci")
        shutil.copytree(ROOT / "tooling" / "tests" / "fixtures" / "skills" / "fix-ci", self.fixtures / "fix-ci")
        self.patches = [patch.object(self.module, "ROOT", root), patch.object(self.module, "SKILLS_DIR", self.skills), patch.object(self.module, "FIXTURES_DIR", self.fixtures)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def assert_fails(self, message: str):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.module.validate_action_skill("fix-ci")
        self.assertIn(message, stderr.getvalue())

    def test_shipped_action_skills_validate(self):
        for name in self.module.ACTION_SKILLS:
            with patch.object(self.module, "SKILLS_DIR", ROOT / "skills"), patch.object(self.module, "FIXTURES_DIR", ROOT / "tooling" / "tests" / "fixtures" / "skills"):
                self.module.validate_action_skill(name)

    def test_missing_pieces_are_reported(self):
        self.module.validate_action_skill("fix-ci")
        ledger = self.skills / "fix-ci" / "VERIFICATION.md"
        original = ledger.read_text(encoding="utf-8")
        ledger.write_text(original.replace("| claude-code | no |", "| vim | no |"), encoding="utf-8")
        self.assert_fails("no row for claude-code")
        ledger.write_text(original.replace("| codex | no | — | — |", "| codex | yes | 2026-01-01 | — |"), encoding="utf-8")
        self.assert_fails("verified without a toolkit revision")
        ledger.write_text(original.replace("| codex | no |", "| codex | maybe |"), encoding="utf-8")
        self.assert_fails("must say yes or no")
        ledger.write_text(original.replace("| codex | no | — | — |", "| codex | yes | 2026-01-01 | v2.1.0 |"), encoding="utf-8")
        self.assert_fails("invalid toolkit revision")
        ledger.unlink()
        self.assert_fails("missing VERIFICATION.md")
        (self.fixtures / "fix-ci" / "TASK.md").unlink()
        self.assert_fails("seeded fixture")
        skill = self.skills / "fix-ci" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8").replace("## Stop conditions", "## Stopping"), encoding="utf-8")
        self.assert_fails("Stop conditions")
        skill.unlink()
        self.assert_fails("no SKILL.md")


    def test_duplicate_client_rows_rejected(self):
        ledger = self.skills / "fix-ci" / "VERIFICATION.md"
        ledger.write_text(ledger.read_text() + "\n| codex | no | — | — | — | — | — |\n")
        self.assert_fails("duplicate client")

    def test_verified_revision_must_match_skill_and_fixture(self):
        root = self.skills.parent
        def git(*args):
            return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
        git("init")
        git("config", "user.email", "fixture@example.test")
        git("config", "user.name", "Fixture")
        git("add", ".")
        git("commit", "-m", "seed")
        revision = git("rev-parse", "HEAD")
        ledger = self.skills / "fix-ci" / "VERIFICATION.md"
        original_ledger = ledger.read_text()
        good = f"| codex | yes | 2026-01-01 | {revision} | client 1.0 | Fixed with passing checks | https://example.test/evidence |"
        original_row = "| codex | no | — | — | — | — | — |"
        ledger.write_text(original_ledger.replace(original_row, good))
        self.module.validate_action_skill("fix-ci")
        for index in (2, 4, 5, 6):
            cells = [cell.strip() for cell in good.strip("|").split("|")]
            cells[index] = "—"
            ledger.write_text(original_ledger.replace(original_row, "| " + " | ".join(cells) + " |"))
            self.assert_fails("metadata is incomplete")
        for bad_date in ("2026-02-30", "2099-01-01", "20260101"):
            ledger.write_text(original_ledger.replace(original_row, good.replace("2026-01-01", bad_date)))
            self.assert_fails("date is invalid")
        ledger.write_text(original_ledger.replace(original_row, good.replace("https://example.test/evidence", "not shared")))
        self.assert_fails("needs evidence")
        ledger.write_text(original_ledger.replace(original_row, good.replace("https://example.test/evidence", "withheld: private environment transcript retained by maintainer")))
        self.module.validate_action_skill("fix-ci")
        for path in (self.skills / "fix-ci" / "SKILL.md", self.fixtures / "fix-ci" / "TASK.md"):
            original = path.read_text()
            path.write_text(original + "\nChanged\n")
            self.assert_fails("verification is stale")
            path.write_text(original)
        extra = self.fixtures / "fix-ci" / "extra.py"
        extra.write_text("# new fixture content\n")
        self.assert_fails("verification is stale")


if __name__ == "__main__":
    unittest.main()
