from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))
import activation  # noqa: E402
from ai_toolkit import VERSION, report  # noqa: E402


class ActivationIndexTests(unittest.TestCase):
    def test_guide_tracks_every_catalog_check_and_actual_provider_contract(self):
        catalog = json.loads((ROOT / "policies/control-catalog.yaml").read_text())
        providers = json.loads((ROOT / "policies/provider-config.yaml").read_text())
        guide = (ROOT / "docs/activation.md").read_text()
        self.assertEqual(guide, activation.render_guide(catalog, providers))
        self.assertEqual(len(catalog["controls"]), 33)
        for control in catalog["controls"]:
            with self.subTest(check=control["id"]):
                self.assertEqual(guide.count(f"### {control['id']}\n"), 1)
                provider_id = providers["selections"][control["id"]]["authoritative"]
                hint = activation.hints(control, provider_id, providers["providers"][provider_id])
                self.assertIn(control["purpose"], guide)
                self.assertTrue(hint["guide"].endswith("#" + control["id"]))

    def test_fork_guidance_does_not_offer_unsupported_secret_bypass(self):
        guidance = report.REASON_ACTIONS["credential-withheld"]
        self.assertIn("withheld", guidance)
        self.assertNotIn("SCAN_FORKS", guidance)

    def test_distribution_entry_points_report_one_version(self):
        spec = importlib.util.spec_from_file_location("installer_version", ROOT / "tooling/install.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.assertEqual(module.VERSION, VERSION)
        for command in ([sys.executable, "tooling/install.py", "--version"],
                        [sys.executable, "tooling/ai_toolkit", "--version"]):
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
            self.assertIn(VERSION, result.stdout)
        self.assertEqual(json.loads((ROOT / "proof/control-catalog.schema.json").read_text())["properties"]["version"]["const"], 2)
