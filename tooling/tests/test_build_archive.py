from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "build_archive.py"


def load():
    spec = importlib.util.spec_from_file_location("build_archive", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name).resolve()
        cls.archive, cls.checksum = cls.module.build(cls.root / "dist" / "ai-toolkit.pyz", build_revision="vTEST")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_payload_excludes_tests_and_bytecode(self):
        files = {path.relative_to(ROOT).as_posix() for path in self.module.payload_files()}
        self.assertIn("tooling/install.py", files)
        self.assertIn("tooling/ai_toolkit/cli.py", files)
        self.assertIn("policies/provider-config.yaml", files)
        self.assertIn("skills/toolkit-setup/SKILL.md", files)
        self.assertTrue(any(name.startswith("security/semgrep/tests/fixtures/") for name in files))
        self.assertFalse(any(name.startswith("tooling/tests/") for name in files))
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in files))
        self.assertFalse(any(name.startswith("docs/") for name in files))

    def test_archive_contents_and_checksum(self):
        self.assertTrue(self.archive.is_file())
        self.assertTrue(self.module.verify(self.archive))
        digest, name = self.checksum.read_text(encoding="utf-8").split()
        self.assertEqual(name, "ai-toolkit.pyz")
        self.assertEqual(digest, self.module.sha256_file(self.archive))
        with zipfile.ZipFile(self.archive) as bundle:
            names = set(bundle.namelist())
            self.assertIn("__main__.py", names)
            self.assertIn("payload/tooling/ai_toolkit/BUILD.json", names)
            self.assertIn('"revision": "vTEST"', bundle.read("payload/tooling/ai_toolkit/BUILD.json").decode())
        tampered = self.root / "tampered.pyz"
        tampered.write_bytes(self.archive.read_bytes() + b"\n")
        tampered.with_name("tampered.pyz.sha256").write_text(self.checksum.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertFalse(self.module.verify(tampered))
        self.assertFalse(self.module.verify(self.root / "absent.pyz"))

    def test_launcher_runs_cli_from_cache(self):
        cache = self.root / "cache"
        environment = {**os.environ, "AI_TOOLKIT_CACHE": str(cache)}
        for _ in range(2):
            completed = subprocess.run([sys.executable, str(self.archive), "--version"], text=True, capture_output=True, env=environment)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("(vTEST)", completed.stdout)
        extracted = [path for path in cache.iterdir() if path.is_dir()]
        self.assertEqual(len(extracted), 1)
        self.assertTrue((extracted[0] / ".complete").is_file())
        self.assertTrue((extracted[0] / "tooling" / "install.py").is_file())
        completed = subprocess.run([sys.executable, str(self.archive), "skills", "list"], text=True, capture_output=True, env=environment)
        self.assertIn("toolkit-setup", completed.stdout)
        with patch.dict(os.environ, {"AI_TOOLKIT_CACHE": "", "XDG_CACHE_HOME": str(self.root / "xdg")}):
            completed = subprocess.run([sys.executable, str(self.archive), "--version"], text=True, capture_output=True, env=dict(os.environ))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.root / "xdg" / "ai-toolkit").is_dir())

    def test_main_builds_and_verifies(self):
        output = self.root / "out" / "ai-toolkit.pyz"
        with patch.object(sys, "argv", ["build_archive.py", "--output", str(output), "--revision", "vMAIN"]), contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(self.module.main(), 0)
        self.assertIn("Built", stdout.getvalue())
        with patch.object(sys, "argv", ["build_archive.py", "--verify", str(output)]), contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(self.module.main(), 0)
        self.assertIn("OK", stdout.getvalue())
        output.write_bytes(output.read_bytes() + b"x")
        with patch.object(sys, "argv", ["build_archive.py", "--verify", str(output)]), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(self.module.main(), 1)
        self.assertIn("MISMATCH", stderr.getvalue())

    def test_revision_falls_back_to_version(self):
        self.assertTrue(self.module.revision())
        with patch.object(self.module.shutil, "which", return_value=None):
            self.assertRegex(self.module.revision(), r"^\d+\.\d+\.\d+$")
        self.assertRegex(self.module.revision(self.root), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
