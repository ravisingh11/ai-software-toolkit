from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))

from ai_toolkit import config  # noqa: E402
from ai_toolkit.runtime import ToolkitError  # noqa: E402


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve()

    def test_round_trip(self):
        configuration = config.default_configuration("v2.1.0", components=["guardrails", "skills"], clients=["codex", "claude-code"], skills_dir=".claude/skills")
        path = config.write_configuration(self.target, configuration)
        text = path.read_text(encoding="utf-8")
        self.assertIn('revision = "v2.1.0"', text)
        self.assertIn('components = ["guardrails", "skills"]', text)
        self.assertIn("never in this file", text)
        self.assertEqual(config.read_configuration(self.target), configuration)

    def test_missing_configuration_is_none(self):
        self.assertIsNone(config.read_configuration(self.target))

    def test_invalid_configurations_are_rejected(self):
        cases = [
            {"toolkit": []},
            {"toolkit": {"components": []}, "agents": {}, "guardrails": {}},
            {"toolkit": {"components": ["nope"]}, "agents": {}, "guardrails": {}},
            {"toolkit": {"components": ["skills"]}, "agents": {"clients": ["vim"]}, "guardrails": {}},
            {"toolkit": {"components": ["skills"]}, "agents": {"skills_dir": "/abs"}, "guardrails": {}},
            {"toolkit": {"components": ["skills"]}, "agents": {}, "guardrails": {"policy": "../x"}},
            {"toolkit": {"components": ["skills"], "revision": 3}, "agents": {}, "guardrails": {}},
        ]
        for document in cases:
            with self.assertRaises(ToolkitError):
                config.validate_configuration(document)
        (self.target / config.TOML_NAME).write_text("[toolkit\n", encoding="utf-8")
        with self.assertRaises(ToolkitError):
            config.read_configuration(self.target)

    def test_defaults_fill_missing_optional_keys(self):
        configuration = config.validate_configuration({"toolkit": {"components": ["qa"]}, "agents": {}, "guardrails": {}})
        self.assertEqual(configuration["agents"]["skills_dir"], ".agents/skills")
        self.assertEqual(configuration["guardrails"]["providers"], ".guardrails/providers.yaml")
        self.assertEqual(configuration["toolkit"]["revision"], "")

    def test_symlinked_configuration_is_not_overwritten(self):
        real = self.target / "real.toml"
        real.write_text("", encoding="utf-8")
        os.symlink(real, self.target / config.TOML_NAME)
        with self.assertRaises(ToolkitError):
            config.write_configuration(self.target, config.default_configuration("v1", components=["skills"], clients=[]))
        os.symlink(real, self.target / config.LOCK_NAME)
        with self.assertRaises(ToolkitError):
            config.write_lock(self.target, config.build_lock("v1", components=["skills"], managed={}))


class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve()
        (self.target / "a.txt").write_text("a\n", encoding="utf-8")
        (self.target / "b.txt").write_text("b\n", encoding="utf-8")

    def test_hash_build_write_read(self):
        managed = config.hash_managed(self.target, ["a.txt", "b.txt", "missing.txt", "a.txt"])
        self.assertEqual(sorted(managed), ["a.txt", "b.txt"])
        lock = config.build_lock("v1", components=["skills", "guardrails"], managed=managed, previous={"revision": "v0"})
        self.assertEqual(lock["components"], ["guardrails", "skills"])
        config.write_lock(self.target, lock)
        self.assertEqual(config.read_lock(self.target), lock)
        self.assertIsNone(config.read_lock(self.target / "elsewhere"))

    def test_invalid_locks_are_rejected(self):
        path = self.target / config.LOCK_NAME
        path.write_text(json.dumps({"version": 99, "toolkit": {}, "managed": {}}), encoding="utf-8")
        with self.assertRaises(ToolkitError):
            config.read_lock(self.target)
        path.write_text(json.dumps({"version": 1, "toolkit": {}, "managed": {"../x": "h"}}), encoding="utf-8")
        with self.assertRaises(ToolkitError):
            config.read_lock(self.target)
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ToolkitError):
            config.read_lock(self.target)

    def test_classify(self):
        managed = config.hash_managed(self.target, ["a.txt", "b.txt"])
        lock = config.build_lock("v1", components=["skills"], managed={**managed, "gone.txt": "0" * 64})
        (self.target / "b.txt").write_text("changed\n", encoding="utf-8")
        (self.target / "c.txt").write_text("new\n", encoding="utf-8")
        result = config.classify(self.target, lock, ["a.txt", "b.txt", "c.txt", "gone.txt"])
        self.assertEqual(result["unmodified"], ["a.txt"])
        self.assertEqual(result["modified"], ["b.txt"])
        self.assertEqual(result["new"], ["c.txt"])
        self.assertEqual(result["missing"], ["gone.txt"])
        self.assertEqual(result["removed"], [])
        result = config.classify(self.target, lock, ["a.txt"])
        self.assertEqual(result["removed"], ["b.txt", "gone.txt"])
        result = config.classify(self.target, None, ["a.txt"])
        self.assertEqual(result["new"], ["a.txt"])


if __name__ == "__main__":
    unittest.main()
