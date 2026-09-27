"""Check that seeded scanners can demonstrate red and green without real providers."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "skills"


class SeededScannerTests(unittest.TestCase):
    def test_seeded_checks_fail_before_fix_and_pass_after(self):
        cases = (
            ("dependency-upgrade", "check_advisory.py", "requirements.txt", "2.31.0", "2.32.0"),
            ("fix-security-finding", "scan.py", "runner.py", "shell=True", "shell=False"),
        )
        for name, scanner, target, old, new in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(FIXTURES / name, root, dirs_exist_ok=True)
                before = subprocess.run([sys.executable, scanner], cwd=root, capture_output=True)
                self.assertNotEqual(before.returncode, 0)
                path = root / target
                path.write_text(path.read_text().replace(old, new))
                after = subprocess.run([sys.executable, scanner], cwd=root, capture_output=True)
                self.assertEqual(after.returncode, 0, after.stderr)


    def test_standalone_findings_install_includes_contracts_and_blocks_missing_routes(self):
        root = FIXTURES.parents[3]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "skills"
            result = subprocess.run(
                ["bash", str(root / "tooling/install-skills.sh"), "--skill", "address-pr-findings",
                 "--target", str(target), "--skip-existing"],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = target / "address-pr-findings"
            self.assertTrue((installed / "references/finding-format.md").is_file())
            self.assertTrue((installed / "references/dedupe-rules.md").is_file())
            for sibling in ("fix-ci", "fix-security-finding", "dependency-upgrade", "generate-unit-tests"):
                self.assertFalse((target / sibling).exists())
            instructions = (installed / "SKILL.md").read_text()
            self.assertIn("BLOCKED: missing", instructions)
            self.assertIn("Load it before", instructions)
            self.assertIn("first apply the routing dependency check", instructions)


if __name__ == "__main__":
    unittest.main()
