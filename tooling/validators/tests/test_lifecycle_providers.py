from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("lifecycle_repository_validator", ROOT / "tooling/validators/validate_repository.py")
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)

PAIRS = {
    "iac-misconfiguration": "trivy-iac-config",
    "container-vulnerability": "trivy-container-image",
    "artifact-sbom": "trivy-artifact-sbom",
    "artifact-vulnerability": "trivy-artifact-sbom-scan",
    "artifact-provenance": "github-artifact-attestations",
    "deployment-policy": "repository-deployment-policy",
    "dynamic-application-security": "zap-baseline-local",
    "runtime-assurance": "repository-runtime-assurance",
    "runtime-soak": "repository-soak",
}


def load(path):
    return json.loads((ROOT / path).read_text())


class LifecycleProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.config = load("policies/provider-config.yaml")
        self.controls = {c["id"]: c for c in load("policies/control-catalog.yaml")["controls"]}

    def validate(self, value):
        VALIDATOR.validate_provider_document(value, self.controls)

    def test_every_lifecycle_capability_has_a_real_typed_contract(self):
        for control, provider in PAIRS.items():
            with self.subTest(control=control):
                self.assertEqual(self.controls[control]["availability"], "runnable")
                definition = self.config["providers"][provider]
                self.assertEqual(definition["capabilities"], [control])
                self.assertEqual(definition["checks"], {})
                self.assertEqual(definition["lifecycle"], {
                    "workflow": "Lifecycle Verification",
                    "workflow_path": ".github/workflows/lifecycle-verification.yml",
                    "artifact_name_prefix": "proof-lifecycle-evidence-",
                    "artifact_member": "lifecycle-receipt.json",
                })
                self.assertEqual(definition["enabled_by_default"], provider == "github-artifact-attestations")
                self.assertEqual(self.config["selections"][control]["authoritative"], provider)
        self.validate(self.config)

    def test_invalid_lifecycle_contracts_are_rejected(self):
        cases = [
            {"workflow": "Other"},
            {"workflow_path": ".github/workflows/attacker.yml"},
            {"artifact_name_prefix": "anything-"},
            {"artifact_member": "../receipt.json"},
            {"unknown": True},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                value = copy.deepcopy(self.config)
                value["providers"]["trivy-iac-config"]["lifecycle"].update(changes)
                with self.assertRaisesRegex(ValueError, "lifecycle"):
                    self.validate(value)

    def test_lifecycle_cannot_be_injected_into_another_provider(self):
        value = copy.deepcopy(self.config)
        value["providers"]["repository-build"]["lifecycle"] = self.config["providers"]["trivy-iac-config"]["lifecycle"]
        with self.assertRaisesRegex(ValueError, "lifecycle"):
            self.validate(value)

    def test_lifecycle_capability_cannot_be_rebound(self):
        value = copy.deepcopy(self.config)
        value["providers"]["trivy-iac-config"]["capabilities"] = ["deep-sast"]
        with self.assertRaisesRegex(ValueError, "lifecycle"):
            self.validate(value)

    def test_lifecycle_must_not_fall_back_to_an_ordinary_check(self):
        value = copy.deepcopy(self.config)
        value["providers"]["trivy-iac-config"]["checks"] = {
            "iac-misconfiguration": {"check_name": "Build", "workflow": "Build", "workflow_path": ".github/workflows/build.yml"}
        }
        with self.assertRaisesRegex(ValueError, "lifecycle"):
            self.validate(value)

    def test_lifecycle_is_never_silently_enabled_by_profile_defaults(self):
        profiles = load("policies/profiles.yaml")["profiles"]
        for profile in profiles.values():
            for operation, defaults in profile["defaults"].items():
                for control in PAIRS:
                    if control == "artifact-provenance" and operation == "release":
                        continue  # Existing GitHub release default is unchanged.
                    self.assertNotIn(control, defaults)
                self.assertTrue(all(mode == "advisory" for mode in defaults.values()))


if __name__ == "__main__":
    unittest.main()
