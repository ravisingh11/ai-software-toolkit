from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tooling" / "validators" / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("validate_repository", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

CONTROL_IDS = {
    "repository-validation",
    "documentation-validation",
    "repository-ground-truth",
    "change-scope",
    "pr-metadata",
    "format-and-lint",
    "migration-validation",
    "build",
    "unit-tests",
    "changed-code-coverage",
    "functional-qa",
    "custom-static-analysis",
    "secret-detection",
    "deep-sast",
    "dependency-change-review",
    "platform-secret-protection",
    "dependency-remediation",
    "artifact-provenance",
    "static-quality",
    "dependency-vulnerability",
    "license-compliance",
    "ai-engineering-review",
    "ai-qa-review",
    "ai-security-review",
    "ai-repository-standards-review",
    "runtime-soak",
    "container-vulnerability",
    "iac-misconfiguration",
    "artifact-sbom",
    "artifact-vulnerability",
    "deployment-policy",
    "dynamic-application-security",
    "runtime-assurance",
}


def load(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class ControlCatalogPolicyTests(unittest.TestCase):
    def validator(self, name: str):
        validator = getattr(MODULE, name, None)
        self.assertIsNotNone(validator, f"missing contract validator: {name}")
        return validator

    def test_catalog_contains_exact_v2_capabilities(self) -> None:
        catalog = load("policies/control-catalog.yaml")

        self.assertEqual(catalog["version"], 2)
        self.assertEqual({control["id"] for control in catalog["controls"]}, CONTROL_IDS)
        self.validator("validate_control_catalog_document")(catalog)

    def test_every_control_has_v2_contract_fields(self) -> None:
        required = {
            "id", "name", "purpose", "stage", "availability",
            "evidence_subject", "enforcement_policy",
        }

        for control in load("policies/control-catalog.yaml")["controls"]:
            with self.subTest(control_id=control["id"]):
                self.assertEqual(set(control), required)

    def test_rejects_invalid_availability(self) -> None:
        catalog = load("policies/control-catalog.yaml")
        catalog["controls"][0]["availability"] = "planned"

        with self.assertRaisesRegex(ValueError, "availability"):
            self.validator("validate_control_catalog_document")(catalog)

    def test_rejects_invalid_evidence_subject(self) -> None:
        catalog = load("policies/control-catalog.yaml")
        catalog["controls"][0]["evidence_subject"] = "unknown-subject"

        with self.assertRaisesRegex(ValueError, "evidence_subject"):
            self.validator("validate_control_catalog_document")(catalog)

    def test_rejects_missing_or_unknown_stage(self) -> None:
        for stage in (None, "unknown-stage"):
            with self.subTest(stage=stage):
                catalog = load("policies/control-catalog.yaml")
                if stage is None:
                    catalog["controls"][0].pop("stage")
                else:
                    catalog["controls"][0]["stage"] = stage
                with self.assertRaisesRegex(ValueError, "stage|fields"):
                    self.validator("validate_control_catalog_document")(catalog)

    def test_catalog_string_boundaries_match_schema(self) -> None:
        schema = load("guardrails/control-catalog.schema.json")
        properties = schema["$defs"]["control"]["properties"]

        for field in ("name", "purpose"):
            maximum = properties[field]["maxLength"]
            with self.subTest(field=field, boundary="maximum"):
                catalog = load("policies/control-catalog.yaml")
                catalog["controls"][0][field] = "x" * maximum
                self.validator("validate_control_catalog_document")(catalog)
            with self.subTest(field=field, boundary="above-maximum"):
                catalog = load("policies/control-catalog.yaml")
                catalog["controls"][0][field] = "x" * (maximum + 1)
                with self.assertRaisesRegex(ValueError, field):
                    self.validator("validate_control_catalog_document")(catalog)

        self.assertEqual(set(properties["stage"]["enum"]), MODULE.CONTROL_STAGES)

    def test_schema_nonempty_strings_match_handwritten_nonblank_rule(self) -> None:
        constrained_fields = {
            "guardrails/control-catalog.schema.json": (
                ("control", "name"),
                ("control", "purpose"),
            ),
            "guardrails/profiles.schema.json": (
                ("profile", "display_name"),
                ("profile", "description"),
            ),
            "guardrails/providers.schema.json": (
                ("provider", "display_name"),
                ("check", "check_name"),
                ("check", "workflow"),
                ("provider", "template"),
            ),
            "guardrails/policy.schema.json": ((None, "name"),),
            "guardrails/evidence.schema.json": (
                (None, "subject.revision"),
                ("result", "producer"),
                ("result", "reason"),
            ),
        }

        for relative_path, fields in constrained_fields.items():
            schema = load(relative_path)
            for definition, field in fields:
                with self.subTest(path=relative_path, definition=definition, field=field):
                    if field == "subject.revision":
                        property_schema = schema["properties"]["subject"]["properties"]["revision"]
                    elif definition is None:
                        property_schema = schema["properties"][field]
                    else:
                        property_schema = schema["$defs"][definition]["properties"][field]
                    self.assertEqual(property_schema["pattern"], "\\S")

    def test_handwritten_provider_validator_accepts_and_checks_trusted_paths(self) -> None:
        catalog_document = load("policies/control-catalog.yaml")
        catalog = {
            control["id"]: control for control in catalog_document["controls"]
        }
        providers = load("policies/provider-config.yaml")

        self.validator("validate_provider_document")(providers, catalog)

        check = providers["providers"]["repository-validator"]["checks"][
            "repository-validation"
        ]
        check["trusted_paths"] = [{"not": "a path"}]
        with self.assertRaisesRegex(ValueError, "trusted_paths"):
            self.validator("validate_provider_document")(providers, catalog)

    def test_profile_defaults_are_exact_and_advisory(self) -> None:
        profiles = load("policies/profiles.yaml")
        expected = {
            "core": {
                "change": {
                    "repository-validation",
                    "documentation-validation",
                    "repository-ground-truth",
                    "change-scope",
                    "pr-metadata",
                    "format-and-lint",
                    "migration-validation",
                    "build",
                    "unit-tests",
                    "changed-code-coverage",
                    "custom-static-analysis",
                    "secret-detection",
                },
                "release": {
                    "repository-validation",
                    "documentation-validation",
                    "repository-ground-truth",
                    "build",
                    "unit-tests",
                    "custom-static-analysis",
                    "secret-detection",
                },
            },
            "github": {
                "change": {
                    "deep-sast",
                    "dependency-change-review",
                    "platform-secret-protection",
                    "dependency-remediation",
                },
                "release": {"artifact-provenance"},
            },
        }

        self.assertEqual(profiles["version"], 2)
        self.assertEqual(set(profiles["profiles"]), set(expected))
        for profile_id, operations in expected.items():
            for operation, control_ids in operations.items():
                with self.subTest(profile=profile_id, operation=operation):
                    defaults = profiles["profiles"][profile_id]["defaults"][operation]
                    self.assertEqual(set(defaults), control_ids)
                    self.assertEqual(set(defaults.values()), {"advisory"})

        self.validator("validate_profiles_document")(
            profiles, {control_id: {} for control_id in CONTROL_IDS}
        )

    def test_rejects_unknown_profile_control(self) -> None:
        profiles = load("policies/profiles.yaml")
        profiles["profiles"]["core"]["defaults"]["change"]["unknown"] = "advisory"

        with self.assertRaisesRegex(ValueError, "unknown control"):
            self.validator("validate_profiles_document")(
                profiles, {control_id: {} for control_id in CONTROL_IDS}
            )

    def test_contract_schemas_are_v2_json_schema_2020_12(self) -> None:
        for relative_path in (
            "guardrails/control-catalog.schema.json",
            "guardrails/profiles.schema.json",
            "guardrails/providers.schema.json",
            "guardrails/policy.schema.json",
            "guardrails/evidence.schema.json",
        ):
            with self.subTest(path=relative_path):
                path = ROOT / relative_path
                self.assertTrue(path.exists(), f"missing schema: {relative_path}")
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(schema["properties"]["version"]["const"], 2)

    def test_baseline_selects_only_core_with_empty_overrides(self) -> None:
        baseline = load("guardrails/baseline.yaml")

        self.assertEqual(
            baseline,
            {
                "$schema": "./policy.schema.json",
                "version": 2,
                "name": "baseline",
                "profiles": ["core"],
                "overrides": {"change": {}, "release": {}},
            },
        )


if __name__ == "__main__":
    unittest.main()
