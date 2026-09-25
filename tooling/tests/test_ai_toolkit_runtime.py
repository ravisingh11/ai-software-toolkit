from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))

from ai_toolkit import runtime  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve()

    def test_build_metadata_and_revision(self):
        metadata = self.target / "BUILD.json"
        with patch.object(runtime, "BUILD_METADATA", metadata):
            self.assertEqual(runtime.build_metadata(), {})
            metadata.write_text("[]", encoding="utf-8")
            self.assertEqual(runtime.build_metadata(), {})
            metadata.write_text("{broken", encoding="utf-8")
            self.assertEqual(runtime.build_metadata(), {})
            metadata.write_text(json.dumps({"revision": "vPINNED"}), encoding="utf-8")
            self.assertEqual(runtime.revision(), "vPINNED")
            metadata.write_text(json.dumps({"revision": "  "}), encoding="utf-8")
            with patch.object(runtime.shutil, "which", return_value=None):
                self.assertEqual(runtime.revision(), runtime.VERSION)
        self.assertTrue(runtime.revision())

    def test_target_and_runtime_resolution(self):
        with self.assertRaises(runtime.ToolkitError):
            runtime.resolve_target(self.target / "missing")
        self.assertEqual(runtime.resolve_target(str(self.target)), self.target)
        self.assertIsNone(runtime.installed_runtime(self.target))
        self.assertEqual(runtime.script_path("doctor", self.target), ROOT / "tooling" / "doctor.py")
        guardrails = self.target / ".guardrails"
        guardrails.mkdir()
        (guardrails / "policy.yaml").write_text("{}", encoding="utf-8")
        (guardrails / "scan.py").write_text("", encoding="utf-8")
        self.assertEqual(runtime.installed_runtime(self.target), guardrails)
        self.assertEqual(runtime.script_path("scan", self.target), guardrails / "scan.py")
        self.assertEqual(runtime.script_path("doctor", self.target), ROOT / "tooling" / "doctor.py")
        self.assertEqual(runtime.script_path("scan", self.target, prefer_installed=False), ROOT / "tooling" / "scan_repository.py")
        with patch.dict(runtime.SCRIPTS, {"ghost": ("tooling/ghost.py", None)}):
            with self.assertRaises(runtime.ToolkitError):
                runtime.script_path("ghost", self.target)

    def test_git_helpers_and_json(self):
        self.assertIsNone(runtime.head_revision(self.target))
        with patch.object(runtime.shutil, "which", return_value=None):
            self.assertIsNone(runtime.git_output(self.target, ["status"]))
        path = self.target / "x.json"
        with self.assertRaises(runtime.ToolkitError):
            runtime.load_json(path)
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(runtime.ToolkitError):
            runtime.load_json(path)
        path.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(runtime.load_json(path), {"a": 1})
        self.assertEqual(len(runtime.sha256_file(path)), 64)
        self.assertEqual(runtime.relative(path, self.target), "x.json")
        self.assertEqual(runtime.relative(Path("/"), self.target), "/")


if __name__ == "__main__":
    unittest.main()
