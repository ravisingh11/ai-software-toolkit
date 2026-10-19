from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class ScorecardWaitConfigurationTests(unittest.TestCase):
    def collector_step(self) -> dict:
        workflow = yaml.safe_load((ROOT / "workflows/proof-scorecard.yml").read_text())
        return next(step for step in workflow["jobs"]["scorecard"]["steps"]
                    if step.get("name") == "Collect selected provider checks")

    def test_only_explicitly_disabled_snyk_providers_get_wait_hints(self) -> None:
        cases = [
            ({}, []),
            ({"PULL_REQUEST_NUMBER": ""}, []),
            ({"SNYK_CODE_ENABLED": "", "SNYK_OPEN_SOURCE_ENABLED": ""}, []),
            ({"SNYK_CODE_ENABLED": "true", "SNYK_OPEN_SOURCE_ENABLED": "true"}, []),
            ({"SNYK_CODE_ENABLED": "false"}, ["snyk-code"]),
            ({"SNYK_OPEN_SOURCE_ENABLED": "false"}, ["snyk-open-source"]),
            ({"SNYK_CODE_ENABLED": "false", "SNYK_OPEN_SOURCE_ENABLED": "false"},
             ["snyk-code", "snyk-open-source"]),
            ({"SNYK_CODE_ENABLED": "FALSE", "SNYK_OPEN_SOURCE_ENABLED": "False"},
             ["snyk-code", "snyk-open-source"]),
            ({"SNYK_CODE_ENABLED": "fAlSe"}, ["snyk-code"]),
            ({"SNYK_OPEN_SOURCE_ENABLED": " false "}, []),
            ({"SNYK_CODE_ENABLED": "false; touch injected"}, []),
        ]
        for variables, expected in cases:
            with self.subTest(variables=variables), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                collector = root / ".proof-trusted/.proof/github_evidence.py"
                collector.parent.mkdir(parents=True)
                collector.write_text(
                    "import json, pathlib, sys\n"
                    "if '--help' in sys.argv:\n"
                    "    print('--pull-request-number'); sys.exit(0)\n"
                    "output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
                    "output.write_text(json.dumps(sys.argv[1:]))\n"
                )
                environment = os.environ.copy()
                for name in ("SNYK_CODE_ENABLED", "SNYK_OPEN_SOURCE_ENABLED"):
                    environment.pop(name, None)
                environment.update({
                    "GITHUB_ENV": str(root / "github-env"),
                    "REVISION": "a" * 40,
                    "TRUSTED_BASE_REVISION": "b" * 40,
                    "TRUSTED_WORKFLOW_REF": "refs/heads/main",
                    "PULL_REQUEST_NUMBER": "17",
                    **variables,
                })
                result = subprocess.run(
                    ["bash", "-c", self.collector_step()["run"]], cwd=root,
                    env=environment, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                arguments = json.loads((root / ".artifacts/proof/evidence.json").read_text())
                hints = [arguments[index + 1] for index, argument in enumerate(arguments)
                         if argument == "--no-wait-provider"]
                self.assertEqual(hints, expected)
                self.assertIn(".proof-trusted/.proof/policy.yaml", arguments)
                self.assertFalse((root / "injected").exists())

    def test_wait_hints_read_repository_variables_without_secrets_or_pr_expressions(self) -> None:
        step = self.collector_step()
        for name in ("SNYK_CODE_ENABLED", "SNYK_OPEN_SOURCE_ENABLED"):
            self.assertEqual(step["env"][name], "${{ vars." + name + " }}")
        self.assertNotIn("${{", step["run"])
        # The settings-only credential is intentionally available to this
        # trusted collector; it must not become a wait hint or shell argument.
        self.assertEqual(step["env"].pop("PROOF_CODEQL_CONFIGURATION_TOKEN"),
                         "${{ secrets.PROOF_CODEQL_CONFIGURATION_TOKEN }}")
        self.assertNotIn("secrets.", json.dumps(step))
        self.assertNotIn("PROOF_CODEQL_CONFIGURATION_TOKEN", step["run"])
        workflow = yaml.safe_load((ROOT / "workflows/proof-scorecard.yml").read_text())
        self.assertNotIn("secrets.", json.dumps(workflow.get("env", {})))
        for job in workflow["jobs"].values():
            self.assertNotIn("secrets.", json.dumps(job.get("env", {})))



if __name__ == "__main__":
    unittest.main()
