from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "configure_proof.py"
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("configure_proof", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def contracts() -> tuple[dict, dict, dict, dict]:
    policy = {"version": 2, "name": "test", "profiles": ["core"], "overrides": {"change": {}, "release": {}}}
    profiles = json.loads((ROOT / "policies" / "profiles.yaml").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "policies" / "control-catalog.yaml").read_text(encoding="utf-8"))
    providers = json.loads((ROOT / "policies" / "provider-config.yaml").read_text(encoding="utf-8"))
    base = {"activation": "external", "template": None, "template_available": False, "secrets": [], "enabled_by_default": False}
    providers["providers"]["alternate-build"] = {
        **base, "display_name": "Alternate Build", "capabilities": ["build"], "checks": {},
    }
    providers["selections"]["deep-sast"]["supplemental"] = ["snyk-code"]
    return policy, profiles, catalog, providers


class ConfigureProofV2Tests(unittest.TestCase):
    def apply(self, **changes):
        policy, profiles, catalog, providers = contracts()
        MODULE.apply_changes(policy, profiles, catalog, providers, operation="change", all_operations=False, **changes)
        return policy, providers

    def test_profile_enable_and_disable_are_additive(self) -> None:
        policy, providers = self.apply(enable_profiles=["github"], disable_profiles=[])
        self.assertEqual(policy["profiles"], ["core", "github"])

        MODULE.apply_changes(policy, contracts()[1], contracts()[2], providers, operation="change", all_operations=False, enable_profiles=[], disable_profiles=["core"])
        self.assertEqual(policy["profiles"], ["github"])

    def test_rejects_unknown_profile_and_removing_last_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown profile"):
            self.apply(enable_profiles=["unknown"], disable_profiles=[])
        with self.assertRaisesRegex(ValueError, "last profile"):
            self.apply(enable_profiles=[], disable_profiles=["core"])

    def test_set_supports_all_modes_and_operation_scope(self) -> None:
        policy, _ = self.apply(enable_profiles=[], disable_profiles=[], sets=["build=enforced"])
        self.assertEqual(policy["overrides"]["change"]["build"], "enforced")
        self.assertNotIn("build", policy["overrides"]["release"])

        policy, profiles, catalog, providers = contracts()
        MODULE.apply_changes(policy, profiles, catalog, providers, operation="change", all_operations=True, sets=["build=not_activated"])
        self.assertEqual(policy["overrides"], {"change": {"build": "not_activated"}, "release": {"build": "not_activated"}})

    def test_rejects_stage_inapplicable_mode_without_mutating_policy(self) -> None:
        policy, profiles, catalog, providers = contracts()

        with self.assertRaisesRegex(
            ValueError,
            "artifact-provenance cannot be configured for change",
        ):
            MODULE.apply_changes(
                policy,
                profiles,
                catalog,
                providers,
                operation="change",
                all_operations=False,
                sets=["artifact-provenance=enforced"],
            )

        self.assertEqual(policy["overrides"], {"change": {}, "release": {}})

    def test_all_operations_rejects_control_that_does_not_apply_to_every_operation(self) -> None:
        policy, profiles, catalog, providers = contracts()

        with self.assertRaisesRegex(
            ValueError,
            "artifact-provenance cannot be configured for change",
        ):
            MODULE.apply_changes(
                policy,
                profiles,
                catalog,
                providers,
                operation="release",
                all_operations=True,
                sets=["artifact-provenance=advisory"],
            )

        self.assertEqual(policy["overrides"], {"change": {}, "release": {}})

    def test_set_rejects_enforced_advisory_only_control(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "ai-engineering-review is advisory-only"
        ):
            self.apply(
                enable_profiles=[],
                disable_profiles=[],
                sets=["ai-engineering-review=enforced"],
            )

    def test_rejects_unknown_or_evidence_only_policy_controls(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown control"):
            self.apply(enable_profiles=[], disable_profiles=[], sets=["unknown=advisory"])
        with self.assertRaisesRegex(ValueError, "evidence-only"):
            self.apply(enable_profiles=[], disable_profiles=[], sets=["artifact-sbom=advisory"])

    def test_provider_selection_and_supplemental_mutations(self) -> None:
        policy, profiles, catalog, providers = contracts()
        MODULE.apply_changes(
            policy, profiles, catalog, providers,
            operation="change", all_operations=False,
            remove_supplemental=["deep-sast=snyk-code"],
            select_providers=["deep-sast=snyk-code"],
            add_supplemental=["deep-sast=github-codeql"],
        )

        self.assertEqual(providers["selections"]["deep-sast"], {"authoritative": "snyk-code", "supplemental": ["github-codeql"]})

    def test_rejects_authority_that_is_still_supplemental(self) -> None:
        with self.assertRaisesRegex(ValueError, "remove it from supplemental"):
            self.apply(enable_profiles=[], disable_profiles=[], select_providers=["deep-sast=snyk-code"])

    def test_rejects_duplicate_supplemental_and_capability_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate supplemental"):
            self.apply(enable_profiles=[], disable_profiles=[], add_supplemental=["deep-sast=snyk-code"])
        with self.assertRaisesRegex(ValueError, "does not provide"):
            self.apply(enable_profiles=[], disable_profiles=[], select_providers=["build=github-codeql"])

    def test_rejects_removing_unknown_supplemental(self) -> None:
        with self.assertRaisesRegex(ValueError, "is not supplemental"):
            self.apply(enable_profiles=[], disable_profiles=[], remove_supplemental=["build=alternate-build"])

    def test_list_shows_effective_modes_and_provider_display_names(self) -> None:
        policy, profiles, catalog, providers = contracts()
        output = MODULE.render_listing(policy, profiles, catalog, providers, "change")

        self.assertIn("advisory", output)
        self.assertIn("Build", output)
        self.assertIn("Repository Build", output)
        self.assertIn("Snyk Code", output)

    def test_effective_mode_output_is_machine_readable(self) -> None:
        policy, profiles, catalog, providers = contracts()
        policy["overrides"]["change"]["change-scope"] = "enforced"

        output = MODULE.render_effective_mode(
            policy, profiles, catalog, providers, "change", "change-scope"
        )

        self.assertEqual(json.loads(output), {
            "control_id": "change-scope",
            "mode": "enforced",
            "operation": "change",
        })

    def test_cli_exposes_only_v2_configuration_interfaces(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"], text=True, capture_output=True, check=True)

        for option in (
            "--enable-profile", "--disable-profile", "--select-provider",
            "--add-supplemental", "--remove-supplemental", "--set",
            "--operation", "--all-operations", "--list", "--dry-run",
            "--effective-mode",
        ):
            self.assertIn(option, result.stdout)
        for retired in ("--manifest", "--sync-providers", "--enable-provider", "--set-provider-mode"):
            self.assertNotIn(retired, result.stdout)

    def test_rejects_identical_policy_and_provider_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "configuration.yaml"

            with self.assertRaisesRegex(ValueError, "different paths"):
                MODULE.write_configuration_pair(path, path, {"version": 2}, {"version": 2})

    def test_configuration_pair_rolls_back_when_second_atomic_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / "policy.yaml"
            providers_path = root / "providers.yaml"
            original_policy = b'{"version": 2, "name": "before"}\n'
            original_providers = b'{"version": 2, "name": "before"}\n'
            policy_path.write_bytes(original_policy)
            providers_path.write_bytes(original_providers)
            os.chmod(policy_path, 0o640)
            os.chmod(providers_path, 0o600)
            real_replace = os.replace
            calls = 0

            def fail_second_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated provider replace failure")
                return real_replace(source, destination)

            with mock.patch.object(MODULE.os, "replace", side_effect=fail_second_replace):
                with self.assertRaisesRegex(OSError, "simulated provider"):
                    MODULE.write_configuration_pair(
                        policy_path,
                        providers_path,
                        {"version": 2, "name": "after"},
                        {"version": 2, "name": "after"},
                    )

            self.assertEqual(policy_path.read_bytes(), original_policy)
            self.assertEqual(providers_path.read_bytes(), original_providers)
            self.assertEqual(policy_path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(providers_path.stat().st_mode & 0o777, 0o600)

    def test_successful_atomic_pair_write_preserves_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / "policy.yaml"
            providers_path = root / "providers.yaml"
            policy_path.write_text("{}\n", encoding="utf-8")
            providers_path.write_text("{}\n", encoding="utf-8")
            os.chmod(policy_path, 0o640)
            os.chmod(providers_path, 0o600)

            MODULE.write_configuration_pair(
                policy_path,
                providers_path,
                {"version": 2, "name": "after"},
                {"version": 2, "providers": {}, "selections": {}},
            )

            self.assertEqual(json.loads(policy_path.read_text(encoding="utf-8"))["name"], "after")
            self.assertEqual(policy_path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(providers_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
