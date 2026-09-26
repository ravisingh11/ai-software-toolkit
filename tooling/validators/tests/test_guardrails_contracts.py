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


def load(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class GuardrailsContractValidationTests(unittest.TestCase):
    def validator(self, name: str):
        validator = getattr(MODULE, name, None)
        self.assertIsNotNone(validator, f"missing contract validator: {name}")
        return validator

    def catalog(self) -> dict[str, dict]:
        return {
            control["id"]: control
            for control in load("policies/control-catalog.yaml")["controls"]
        }

    def providers(self) -> dict:
        return load("policies/provider-config.yaml")["providers"]

    def test_canonical_provider_contract_is_valid(self) -> None:
        self.validator("validate_provider_document")(
            load("policies/provider-config.yaml"), self.catalog()
        )

    def test_changed_code_coverage_uses_its_own_workflow_template(self) -> None:
        provider = self.providers()["repository-changed-code-coverage"]

        self.assertEqual(provider["template"], "workflows/changed-code-coverage.yml")
        self.assertEqual(
            provider["checks"]["changed-code-coverage"]["workflow"],
            "Changed Code Coverage",
        )

    def test_provider_check_workflow_names_match_template_names(self) -> None:
        config = load("policies/provider-config.yaml")
        self.validator("validate_provider_template_names")(config)

        config["providers"]["repository-build"]["checks"]["build"]["workflow"] = "Duplicate Build Name"
        with self.assertRaisesRegex(ValueError, "template workflow name"):
            self.validator("validate_provider_template_names")(config)

    def test_declared_provider_templates_must_exist_even_when_disabled(self) -> None:
        config = load("policies/provider-config.yaml")
        provider = config["providers"]["snyk-code"]
        provider["template"] = None
        provider["template_available"] = True
        provider["enabled_by_default"] = False

        with self.assertRaisesRegex(ValueError, "without a template path"):
            self.validator("validate_provider_template_names")(config)

        provider["template"] = "workflows/missing-snyk.yml"

        with self.assertRaisesRegex(ValueError, "provider snyk-code template does not exist"):
            self.validator("validate_provider_template_names")(config)

    def test_unshipped_vendor_templates_are_not_declared_available(self) -> None:
        providers = self.providers()

        for provider_id in ("semgrep-app", "qa-bootstrap-workflow"):
            with self.subTest(provider_id=provider_id):
                self.assertIsNone(providers[provider_id]["template"])
                self.assertFalse(providers[provider_id]["template_available"])

    def test_adapter_backed_vendor_templates_are_shipped(self) -> None:
        providers = self.providers()

        for provider_id, template in (("snyk-code", "workflows/snyk.yml"), ("snyk-open-source", "workflows/snyk.yml"), ("fossa", "workflows/fossa.yml")):
            with self.subTest(provider_id=provider_id):
                self.assertEqual(providers[provider_id]["template"], template)
                self.assertTrue(providers[provider_id]["template_available"])
                text = (ROOT / template).read_text(encoding="utf-8")
                self.assertIn(".guardrails/adapter.py", text)
                self.assertIn(f"adapter.py {provider_id}", text)

    def test_actions_backed_checks_declare_exact_installed_workflow_paths(self) -> None:
        providers = self.providers()

        for provider_id, provider in providers.items():
            template = provider["template"]
            if template is None:
                continue
            expected_path = f".github/workflows/{Path(template).name}"
            for capability, check in provider["checks"].items():
                with self.subTest(provider_id=provider_id, capability=capability):
                    self.assertEqual(check.get("workflow_path"), expected_path)
                    self.assertNotIn("app_slug", check)

    def test_rejects_actions_check_without_exact_workflow_path(self) -> None:
        providers = load("policies/provider-config.yaml")
        providers["providers"]["repository-build"]["checks"]["build"].pop(
            "workflow_path", None
        )

        with self.assertRaisesRegex(ValueError, "workflow_path"):
            self.validator("validate_provider_document")(providers, self.catalog())

    def test_rejects_overlapping_check_and_review_contracts(self) -> None:
        providers = load("policies/provider-config.yaml")
        provider = providers["providers"]["repository-build"]
        provider["reviews"] = {"build": {"review_author": "build-reviewer[bot]"}}

        with self.assertRaisesRegex(
            ValueError,
            "repository-build build cannot declare both a check and a review",
        ):
            self.validator("validate_provider_document")(providers, self.catalog())

    def test_non_actions_check_uses_explicit_app_identity_without_fake_path(self) -> None:
        check = self.providers()["semgrep-app"]["checks"]["custom-static-analysis"]

        self.assertEqual(check.get("app_slug"), "semgrep-app")
        self.assertNotIn("workflow_path", check)

    def test_custom_probe_external_id_prefixes_are_explicit(self) -> None:
        providers = load("policies/provider-config.yaml")["providers"]
        cases = (
            ("repository-change-scope", "change-scope", "guardrails:change-scope:", "guardrails-change-scope-"),
            ("github-secret-protection", "platform-secret-protection", "guardrails:secret-protection:", "guardrails-secret-protection-"),
            ("github-dependabot", "dependency-remediation", "guardrails:dependabot:", "guardrails-dependabot-"),
        )
        for provider_id, control_id, external_prefix, artifact_prefix in cases:
            with self.subTest(provider_id=provider_id):
                check = providers[provider_id]["checks"][control_id]
                self.assertEqual(check["external_id_prefix"], external_prefix)
                self.assertEqual(check["artifact_name_prefix"], artifact_prefix)
                self.assertEqual(check["artifact_member"], "guardrails-evidence.json")

    def test_rejects_invalid_external_id_prefix(self) -> None:
        providers = load("policies/provider-config.yaml")
        providers["providers"]["repository-build"]["checks"]["build"]["external_id_prefix"] = ""

        with self.assertRaisesRegex(ValueError, "external_id_prefix"):
            self.validator("validate_provider_document")(providers, self.catalog())

    def test_core_and_github_default_providers_are_exact(self) -> None:
        providers = load("policies/provider-config.yaml")["providers"]
        enabled = {
            provider_id
            for provider_id, definition in providers.items()
            if definition["enabled_by_default"]
        }

        self.assertEqual(
            enabled,
            {
                "repository-validator",
                "repository-change-scope",
                "repository-pr-metadata",
                "repository-format-and-lint",
                "repository-migration-validation",
                "repository-build",
                "repository-unit-tests",
                "repository-changed-code-coverage",
                "semgrep-ce",
                "gitleaks",
                "github-codeql",
                "github-dependency-review",
                "github-secret-protection",
                "github-dependabot",
                "github-artifact-attestations",
            },
        )

    def test_default_selections_exclude_disabled_supplementals(self) -> None:
        document = load("policies/provider-config.yaml")
        providers = document["providers"]

        for control_id, selection in document["selections"].items():
            with self.subTest(control_id=control_id):
                self.assertTrue(
                    all(providers[provider_id]["enabled_by_default"] for provider_id in selection["supplemental"])
                )

    def test_rejects_unknown_authoritative_provider(self) -> None:
        providers = load("policies/provider-config.yaml")
        providers["selections"]["build"]["authoritative"] = "unknown"

        with self.assertRaisesRegex(ValueError, "unknown provider"):
            self.validator("validate_provider_document")(providers, self.catalog())

    def test_rejects_empty_or_multiple_authoritative_providers(self) -> None:
        for invalid in ("", ["repository-build", "repository-unit-tests"]):
            with self.subTest(authoritative=invalid):
                providers = load("policies/provider-config.yaml")
                providers["selections"]["build"]["authoritative"] = invalid
                with self.assertRaisesRegex(ValueError, "authoritative"):
                    self.validator("validate_provider_document")(providers, self.catalog())

    def test_rejects_authority_without_selected_capability(self) -> None:
        providers = load("policies/provider-config.yaml")
        providers["selections"]["build"]["authoritative"] = "repository-unit-tests"

        with self.assertRaisesRegex(ValueError, "does not provide build"):
            self.validator("validate_provider_document")(providers, self.catalog())

    def test_rejects_duplicate_supplemental_providers(self) -> None:
        providers = load("policies/provider-config.yaml")
        providers["selections"]["deep-sast"]["supplemental"] = ["snyk-code", "snyk-code"]

        with self.assertRaisesRegex(ValueError, "duplicate supplemental"):
            self.validator("validate_provider_document")(providers, self.catalog())

    def test_rejects_authority_reused_as_supplemental(self) -> None:
        providers = load("policies/provider-config.yaml")
        providers["selections"]["deep-sast"]["supplemental"] = ["github-codeql"]

        with self.assertRaisesRegex(ValueError, "also supplemental"):
            self.validator("validate_provider_document")(providers, self.catalog())

    def test_provider_schema_boundaries_match_handwritten_validation(self) -> None:
        schema = load("guardrails/providers.schema.json")
        properties = schema["$defs"]["provider"]["properties"]
        check_properties = schema["$defs"]["check"]["properties"]
        self.assertEqual(properties["capabilities"]["minItems"], 1)
        self.assertEqual(properties["template"]["minLength"], 1)
        self.assertEqual(properties["template"]["maxLength"], 200)
        self.assertEqual(check_properties["external_id_prefix"]["maxLength"], 150)
        self.assertEqual(check_properties["artifact_name_prefix"]["maxLength"], 150)
        self.assertEqual(check_properties["artifact_member"]["pattern"], "^[A-Za-z0-9._-]+$")
        self.assertEqual(check_properties["app_slug"]["maxLength"], 100)
        self.assertEqual(
            schema["$defs"]["check"]["oneOf"],
            [{"required": ["workflow_path"]}, {"required": ["app_slug"]}],
        )

        providers = load("policies/provider-config.yaml")
        providers["providers"]["repository-build"]["capabilities"] = []
        with self.assertRaisesRegex(ValueError, "capabilities"):
            self.validator("validate_provider_document")(providers, self.catalog())

        providers = load("policies/provider-config.yaml")
        providers["providers"]["repository-build"]["template"] = "x" * 201
        with self.assertRaisesRegex(ValueError, "template"):
            self.validator("validate_provider_document")(providers, self.catalog())

    def test_nested_evidence_contract_is_valid(self) -> None:
        self.validator("validate_evidence_document")(
            load("guardrails/evidence-example.yaml"), self.catalog(), self.providers()
        )

    def test_pull_request_evidence_contract_is_valid(self) -> None:
        evidence = {
            "version": 2,
            "subject": {"type": "pull-request", "revision": "sha256:metadata"},
            "results": {
                "pr-metadata": {
                    "repository-pr-metadata": {
                        "producer": "Repository PR Metadata",
                        "status": "passed",
                        "evidence": ["Pull-request metadata satisfies the contract."],
                    }
                }
            },
        }

        self.validator("validate_evidence_document")(
            evidence, self.catalog(), self.providers()
        )

    def test_rejects_malformed_nested_evidence(self) -> None:
        evidence = load("guardrails/evidence-example.yaml")
        result = next(iter(next(iter(evidence["results"].values())).values()))
        del result["producer"]

        with self.assertRaisesRegex(ValueError, "producer"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_rejects_flat_evidence_results(self) -> None:
        evidence = load("guardrails/evidence-example.yaml")
        evidence["results"] = {
            "unit-tests": {
                "producer": "repository test suite",
                "status": "passed",
                "evidence": ["command: python3 -m unittest"],
            }
        }

        with self.assertRaisesRegex(ValueError, "provider"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_evidence_rejects_unknown_control(self) -> None:
        evidence = load("guardrails/evidence-example.yaml")
        result = evidence["results"].pop("unit-tests")
        evidence["results"]["unknown-control"] = result

        with self.assertRaisesRegex(ValueError, "unknown control"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_evidence_rejects_unknown_provider(self) -> None:
        evidence = load("guardrails/evidence-example.yaml")
        result = evidence["results"]["unit-tests"].pop("repository-unit-tests")
        evidence["results"]["unit-tests"]["unknown-provider"] = result

        with self.assertRaisesRegex(ValueError, "unknown provider"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_evidence_rejects_provider_without_control_capability(self) -> None:
        evidence = load("guardrails/evidence-example.yaml")
        result = evidence["results"]["unit-tests"].pop("repository-unit-tests")
        evidence["results"]["unit-tests"]["repository-build"] = result

        with self.assertRaisesRegex(ValueError, "does not provide unit-tests"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_evidence_rejects_subject_type_mismatch(self) -> None:
        evidence = load("guardrails/evidence-example.yaml")
        evidence["subject"]["type"] = "artifact"

        with self.assertRaisesRegex(ValueError, "requires git-commit subject"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_evidence_provider_map_nonempty_boundary_matches_schema(self) -> None:
        schema = load("guardrails/evidence.schema.json")
        self.assertEqual(schema["$defs"]["providerResults"]["minProperties"], 1)

        evidence = load("guardrails/evidence-example.yaml")
        evidence["results"]["unit-tests"] = {}
        with self.assertRaisesRegex(ValueError, "at least one provider"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_evidence_optional_field_boundaries_match_schema(self) -> None:
        evidence = load("guardrails/evidence-example.yaml")
        result = evidence["results"]["unit-tests"]["repository-unit-tests"]
        result["status"] = "blocked"
        result["reason"] = "provider unavailable"
        result["evidence"] = []

        with self.assertRaisesRegex(ValueError, "evidence records"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

        evidence = load("guardrails/evidence-example.yaml")
        result = evidence["results"]["unit-tests"]["repository-unit-tests"]
        result["reason"] = ""
        with self.assertRaisesRegex(ValueError, "reason"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_evidence_rejects_whitespace_only_records(self) -> None:
        evidence = load("guardrails/evidence-example.yaml")
        result = evidence["results"]["unit-tests"]["repository-unit-tests"]
        result["evidence"] = ["   "]

        with self.assertRaisesRegex(ValueError, "evidence records"):
            self.validator("validate_evidence_document")(
                evidence, self.catalog(), self.providers()
            )

    def test_evidence_record_nonblank_boundary_matches_schema(self) -> None:
        schema = load("guardrails/evidence.schema.json")
        record_schema = schema["$defs"]["result"]["properties"]["evidence"]["items"]

        self.assertEqual(record_schema.get("pattern"), "\\S")

    def test_policy_rejects_invalid_override_mode(self) -> None:
        policy = load("guardrails/baseline.yaml")
        policy["overrides"]["change"]["build"] = "required"

        with self.assertRaisesRegex(ValueError, "override"):
            self.validator("validate_policy_document")(
                policy, {"core", "github"}, self.catalog()
            )

    def test_policy_rejects_unknown_override_control(self) -> None:
        policy = load("guardrails/baseline.yaml")
        policy["overrides"]["change"]["unknown-control"] = "advisory"

        with self.assertRaisesRegex(ValueError, "unknown control"):
            self.validator("validate_policy_document")(
                policy, {"core", "github"}, self.catalog()
            )

    def test_policy_rejects_enforced_advisory_only_control(self) -> None:
        policy = load("guardrails/baseline.yaml")
        policy["overrides"]["change"]["ai-engineering-review"] = "enforced"

        with self.assertRaisesRegex(
            ValueError,
            "ai-engineering-review is advisory-only and cannot be enforced",
        ):
            self.validator("validate_policy_document")(
                policy, {"core", "github"}, self.catalog()
            )


if __name__ == "__main__":
    unittest.main()
