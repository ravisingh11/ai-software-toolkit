from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "security/semgrep/guardrails.yml"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class SemgrepRuleTests(unittest.TestCase):
    def run_semgrep(self, fixture: str) -> dict:
        # Semgrep ignores directories named tests by default, even with
        # --no-git-ignore. Exercise the canonical fixtures outside that path.
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            shutil.copyfile(RULES, workspace / "rules.yml")
            shutil.copytree(FIXTURES / fixture, workspace / fixture)
            try:
                completed = subprocess.run(
                    ["semgrep", "scan", "--metrics", "off", "--config", "rules.yml", "--json", fixture],
                    cwd=workspace, text=True, capture_output=True, timeout=60,
                    env={**os.environ, "SEMGREP_ENABLE_VERSION_CHECK": "0"},
                )
            except FileNotFoundError:
                self.skipTest("Semgrep 1.175.0 is required to execute rule fixtures")
            self.assertIn(completed.returncode, (0, 1), completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["errors"], [])
            self.assertEqual(len(result["paths"]["scanned"]), 2, "Both fixture files must actually be scanned")
            return result

    def test_tls_verification_rules_match_only_unsafe_fixtures(self) -> None:
        unsafe = self.run_semgrep("unsafe")
        safe = self.run_semgrep("safe")
        self.assertEqual(
            {result["check_id"] for result in unsafe["results"]},
            {"guardrails.python-disabled-tls-verification", "guardrails.javascript-disabled-tls-verification"},
        )
        self.assertEqual(safe["results"], [])


if __name__ == "__main__":
    unittest.main()
