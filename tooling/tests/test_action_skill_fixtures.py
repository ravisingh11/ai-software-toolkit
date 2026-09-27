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


if __name__ == "__main__":
    unittest.main()
