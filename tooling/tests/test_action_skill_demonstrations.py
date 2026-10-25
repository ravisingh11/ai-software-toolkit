"""Hosted verification of outputs captured from actual, separately recorded Codex runs.

These checks establish fixture behavior, not agent identity or native provenance.
No model invocation, credentials or production services are needed in CI.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "tooling/tests/fixtures/skills"
EVIDENCE = ROOT / "docs/verification/action-skills/codex"


@unittest.skipUnless(os.environ.get("GITHUB_ACTIONS") == "true", "Captured client outputs are verified in hosted CI")
class CodexActionSkillDemonstrations(unittest.TestCase):
    def prepare(self, name):
        records = json.loads((EVIDENCE / "captures.json").read_text())
        record = next(row for row in records if row["skill"] == name)
        encoded = json.loads((EVIDENCE / (name + ".patch.json")).read_text())
        self.assertEqual(encoded["format"], "git-unified-diff-lines")
        patch_bytes = "".join(encoded["lines"]).encode()
        self.assertEqual(hashlib.sha256(patch_bytes).hexdigest(), record["patch_sha256"])
        directory = tempfile.TemporaryDirectory(prefix="skill-demonstration-")
        self.addCleanup(directory.cleanup)
        work = Path(directory.name)
        shutil.copytree(SEEDS / name, work, dirs_exist_ok=True)
        patch = work / "captured.patch"
        patch.write_bytes(patch_bytes)
        return work, patch

    def command(self, work, *args, passes=True, timeout=60):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(args, cwd=work, env=environment, text=True,
                                capture_output=True, timeout=timeout)
        if passes:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, "Negative control unexpectedly passed")
        return result

    def apply(self, work, patch):
        self.command(work, "git", "apply", "--check", str(patch))
        self.command(work, "git", "apply", str(patch))

    def suite(self, work, *, python=sys.executable, passes=True):
        return self.command(work, python, "-m", "unittest", "discover", "-v", passes=passes)

    def original_tests_preserved(self, name, work):
        for source in (SEEDS / name).glob("test_*.py"):
            old = ast.parse(source.read_text())
            new = ast.parse((work / source.name).read_text())
            methods = {node.name: ast.dump(node) for node in ast.walk(new)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for node in ast.walk(old):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertEqual(methods.get(node.name), ast.dump(node), node.name)

    def test_fix_ci(self):
        work, patch = self.prepare("fix-ci")
        failed = self.suite(work, passes=False)
        self.assertIn("test_negative_divisor", failed.stderr)
        self.apply(work, patch)
        self.original_tests_preserved("fix-ci", work)
        self.suite(work)
        self.command(work, sys.executable, "-c",
                     "from calc import divide; assert divide(-6,-3)==2; assert divide(-6,3)==-2")
        print("REAL_CLIENT_EVIDENCE fix-ci: original failed; fixed suite and signed division passed")

    def test_generated_tests_reject_mutations(self):
        work, patch = self.prepare("generate-unit-tests")
        original = (work / "durations.py").read_text()
        self.apply(work, patch)
        self.assertEqual((work / "durations.py").read_text(), original)
        self.assertTrue(list(work.glob("test_*.py")))
        self.suite(work)
        mutations = [
            ('raise TypeError("duration must be a string")', "return 0"),
            ('raise ValueError(f"invalid duration: {text!r}")', "return 0"),
            ('raise ValueError("duration must be positive")', "return 0"),
            ('"ms": 1', '"ms": 2'),
            ('"s": 1000', '"s": 1'),
            ('"m": 60_000', '"m": 1'),
            ('"h": 3_600_000', '"h": 1'),
            ("text.strip()", "text"),
        ]
        for before, after in mutations:
            with self.subTest(mutation=before):
                self.assertIn(before, original)
                (work / "durations.py").write_text(original.replace(before, after, 1))
                self.suite(work, passes=False)
        (work / "durations.py").write_text(original)
        print("REAL_CLIENT_EVIDENCE generate-unit-tests: valid suite passed; eight behavior mutations rejected")

    def test_security_fix_and_old_code_regression(self):
        work, patch = self.prepare("fix-security-finding")
        original = (work / "runner.py").read_text()
        self.command(work, sys.executable, "scan.py", passes=False)
        self.apply(work, patch)
        self.original_tests_preserved("fix-security-finding", work)
        self.command(work, sys.executable, "scan.py")
        self.suite(work)
        # The captured regression mocks subprocess.run; no injection payload is executed.
        test = (work / "test_runner.py").read_text()
        self.assertIn('patch("runner.subprocess.run")', test)
        fixed = (work / "runner.py").read_text()
        (work / "runner.py").write_text(original)
        self.suite(work, passes=False)
        (work / "runner.py").write_text(fixed)
        print("REAL_CLIENT_EVIDENCE fix-security-finding: scanner cleared; mocked regression rejected old implementation")

    def test_dependency_upgrade_installation_and_synthetic_advisory(self):
        work, patch = self.prepare("dependency-upgrade")
        original = (work / "requirements.txt").read_text()
        self.command(work, sys.executable, "check_advisory.py", passes=False)
        self.apply(work, patch)
        self.original_tests_preserved("dependency-upgrade", work)
        requirements = (work / "requirements.txt").read_text()
        self.assertEqual(requirements, original.replace("requests==2.31.0", "requests==2.32.5"))
        self.command(work, sys.executable, "check_advisory.py")
        self.command(work, sys.executable, "-m", "venv", str(work / "venv"))
        python = str(work / "venv/bin/python")
        self.command(work, python, "-m", "pip", "install", "--disable-pip-version-check",
                     "--no-input", "-r", "requirements.txt", timeout=180)
        self.command(work, python, "-m", "pip", "check")
        self.command(work, python, "-c", "import requests, idna; assert requests.__version__=='2.32.5'; assert idna.__version__=='3.7'")
        self.suite(work, python=python)
        rollback = (work / "ADVISORY.md").read_text()
        self.assertIn("2.31.0", rollback)
        self.assertIn("rollback", rollback.lower())
        (work / "requirements.txt").write_text(original)
        self.command(work, sys.executable, "check_advisory.py", passes=False)
        print("REAL_CLIENT_EVIDENCE dependency-upgrade: pip installation/check and tests passed; original synthetic advisory rejected")

    def test_review_findings_and_original_code_negative_control(self):
        work, patch = self.prepare("address-pr-findings")
        original = (work / "store.py").read_text()
        self.apply(work, patch)
        self.original_tests_preserved("address-pr-findings", work)
        findings = json.loads((work / "findings.json").read_text())
        self.assertEqual({row["id"] for row in findings}, {"ENG-001", "ENG-002", "STD-001"})
        for row in findings:
            self.assertNotEqual(row["status"], "open")
            self.assertTrue(row["verification"]["result"])
            if row["id"] in {"ENG-001", "ENG-002"}:
                self.assertEqual(row["status"], "resolved")
                self.assertEqual(row["verification"]["result"], "passed")
                self.assertEqual(row["verification"]["command"], "python3 -m unittest discover -v")
                self.assertIn("https://github.com/ravisingh11/ai-software-toolkit/actions/runs/",
                              row["verification"]["method"])
            else:
                self.assertEqual(row["status"], "deferred")
                self.assertIn("import", row["verification"]["residualRisk"])
        self.suite(work)
        self.command(work, sys.executable, "-c", """
import store
for key in (None, 1, '', []):
    try:
        store.put(key, 1)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid key accepted')
for index in range(10000):
    store.put('key-'+str(index), index)
assert len(store._CACHE) < 10000, 'cache is unbounded'
assert store.get('key-9999') == 9999
""")
        fixed = (work / "store.py").read_text()
        (work / "store.py").write_text(original)
        self.suite(work, passes=False)
        (work / "store.py").write_text(fixed)
        print("REAL_CLIENT_EVIDENCE address-pr-findings: validation, bounded cache and decision records passed; old implementation rejected")
