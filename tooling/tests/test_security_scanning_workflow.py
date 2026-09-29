from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SecurityScanningWorkflowTests(unittest.TestCase):
    """The bundle runs pull-request code on `pull_request`, so it holds no credential."""

    def setUp(self) -> None:
        self.workflow = (ROOT / "workflows" / "security-scanning.yml").read_text(
            encoding="utf-8"
        )

    def test_declares_and_reads_no_secrets(self) -> None:
        self.assertIn("  pull_request:\n", self.workflow)
        self.assertNotIn("\n    secrets:\n", self.workflow)
        self.assertNotIn("secrets.", self.workflow)
        self.assertNotIn("FOSSA_API_KEY", self.workflow)
        self.assertNotIn("SNYK_TOKEN", self.workflow)

    def test_credentialed_provider_jobs_live_in_adapter_templates(self) -> None:
        for removed in (
            "name: FOSSA\n",
            "name: Snyk Open Source\n",
            "fossa-command:",
            "snyk-open-source-command:",
            "FOSSA_COMMAND",
            "SNYK_OPEN_SOURCE_COMMAND",
        ):
            self.assertNotIn(removed, self.workflow)
        self.assertIn("`fossa.yml` and\n# `snyk.yml`", self.workflow)


if __name__ == "__main__":
    unittest.main()
