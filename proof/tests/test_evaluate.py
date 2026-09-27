from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "evaluate.py"
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("proof_v2_evaluate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def contracts() -> tuple[dict, dict, dict, dict]:
    profiles = json.loads((ROOT / "policies" / "profiles.yaml").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "policies" / "control-catalog.yaml").read_text(encoding="utf-8"))
    providers = json.loads((ROOT / "policies" / "provider-config.yaml").read_text(encoding="utf-8"))
    selected_change_controls = {
        control_id
        for profile in profiles["profiles"].values()
        for control_id in profile["defaults"]["change"]
    }
    policy = {
        "version": 2,
        "name": "test",
        "profiles": ["core"],
        "overrides": {
            "change": {
                control_id: "not_activated"
                for control_id in selected_change_controls - {"build", "deep-sast"}
            },
            "release": {},
        },
    }
    providers["providers"]["alternate-build"] = {
        "display_name": "Alternate Build",
        "activation": "external",
        "capabilities": ["build"],
        "checks": {"build": {"check_name": "Alternate Build", "workflow": "Build", "app_slug": "alternate-build"}},
        "template": None,
        "template_available": False,
        "secrets": [],
        "enabled_by_default": False,
    }
    providers["selections"]["build"]["supplemental"] = ["alternate-build"]
    return policy, profiles, catalog, providers


class ProviderContractTests(unittest.TestCase):
    def test_catalog_declares_ai_reviews_advisory_only(self) -> None:
        _, _, catalog, _ = contracts()
        policies = {
            control["id"]: control["enforcement_policy"]
            for control in catalog["controls"]
        }

        self.assertEqual(policies["build"], "promotable")
        self.assertEqual(policies["ai-engineering-review"], "advisory-only")
        self.assertEqual(policies["ai-qa-review"], "advisory-only")
        self.assertEqual(policies["functional-qa"], "advisory-only")
        self.assertEqual(policies["ai-security-review"], "advisory-only")
        self.assertEqual(
            policies["ai-repository-standards-review"], "advisory-only"
        )

    def test_core_profile_includes_configurable_repository_quality_commands(self) -> None:
        _, profiles, catalog, providers = contracts()
        change = profiles["profiles"]["core"]["defaults"]["change"]
        catalog_ids = {control["id"] for control in catalog["controls"]}

        self.assertEqual(change["format-and-lint"], "advisory")
        self.assertEqual(change["migration-validation"], "advisory")
        self.assertIn("format-and-lint", catalog_ids)
        self.assertIn("migration-validation", catalog_ids)
        self.assertEqual(
            providers["selections"]["format-and-lint"]["authoritative"],
            "repository-format-and-lint",
        )
        self.assertEqual(
            providers["selections"]["migration-validation"]["authoritative"],
            "repository-migration-validation",
        )

    def test_pull_request_subject_is_supported_for_pr_metadata(self) -> None:
        policy, profiles, catalog, providers = contracts()
        control = next(
            item for item in catalog["controls"] if item["id"] == "pr-metadata"
        )

        self.assertEqual(control["evidence_subject"], "pull-request")
        self.assertEqual(
            providers["selections"]["pr-metadata"]["authoritative"],
            "repository-pr-metadata",
        )
        policy["overrides"]["change"]["pr-metadata"] = "advisory"
        result = MODULE.evaluate(
            policy,
            profiles,
            catalog,
            providers,
            {
                "version": 2,
                "subject": {"type": "pull-request", "revision": "sha256:abc123"},
                "results": {
                    "pr-metadata": {
                        "repository-pr-metadata": {
                            "producer": "Repository PR Metadata",
                            "status": "passed",
                            "evidence": ["PR metadata satisfied the configured contract"],
                        }
                    }
                },
            },
            "change",
            "sha256:abc123",
            "pull-request",
        )

        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["controls"][0]["id"], "pr-metadata")

    def test_pr_metadata_provider_declares_exact_head_artifact_contract(self) -> None:
        _, _, catalog, providers = contracts()
        controls = {control["id"]: control for control in catalog["controls"]}
        definitions, _ = MODULE.validate_provider_config(providers, controls)
        check = definitions["repository-pr-metadata"]["checks"]["pr-metadata"]

        self.assertEqual(check["external_id_prefix"], "proof:pr-metadata:")
        self.assertEqual(check["artifact_name_prefix"], "proof-pr-metadata-")
        self.assertEqual(check["artifact_member"], "proof-evidence.json")

    def test_codex_review_provider_uses_exact_github_review_identity(self) -> None:
        _, _, catalog, providers = contracts()
        controls = {control["id"]: control for control in catalog["controls"]}
        definitions, selections = MODULE.validate_provider_config(providers, controls)
        codex = definitions["codex-github-review"]

        self.assertEqual(codex["activation"], "external")
        self.assertEqual(codex["checks"], {})
        self.assertEqual(
            codex["reviews"]["ai-engineering-review"]["review_author"],
            "chatgpt-codex-connector[bot]",
        )
        self.assertEqual(
            selections["ai-engineering-review"]["authoritative"],
            "codex-github-review",
        )

    def test_runtime_rejects_missing_or_unknown_control_stage(self) -> None:
        _, _, catalog, _ = contracts()
        for stage in (None, "unknown-stage"):
            with self.subTest(stage=stage):
                candidate = json.loads(json.dumps(catalog))
                if stage is None:
                    candidate["controls"][0].pop("stage")
                else:
                    candidate["controls"][0]["stage"] = stage
                with self.assertRaisesRegex(ValueError, "stage"):
                    MODULE.catalog_map(candidate)

    def test_runtime_rejects_policy_override_outside_operation_stage(self) -> None:
        policy, profiles, catalog, _ = contracts()
        controls = MODULE.catalog_map(catalog)
        profile_definitions = MODULE.validate_profiles(profiles, controls)
        policy["overrides"]["change"]["artifact-provenance"] = "enforced"

        with self.assertRaisesRegex(
            ValueError,
            "artifact-provenance cannot be configured for change",
        ):
            MODULE.validate_policy(policy, set(profile_definitions), controls)

    def test_repository_validator_trusts_every_outcome_defining_input(self) -> None:
        providers = json.loads(
            (ROOT / "policies" / "provider-config.yaml").read_text(encoding="utf-8")
        )
        checks = providers["providers"]["repository-validator"]["checks"]

        self.assertEqual(
            checks["repository-validation"]["trusted_paths"],
            [
                ".proof/validators/validate_repository.py",
                ".proof/evaluate.py",
            ],
        )
        self.assertEqual(
            checks["documentation-validation"]["trusted_paths"],
            [
                ".proof/validators/validate_documentation.py",
                ".proof/documentation.yaml",
            ],
        )
        self.assertEqual(
            checks["repository-ground-truth"]["trusted_paths"],
            [
                ".proof/validate_ground_truth.py",
                ".proof/ground-truth-ai.yaml",
            ],
        )
        scope = providers["providers"]["repository-change-scope"]["checks"][
            "change-scope"
        ]
        self.assertEqual(scope["workflow_path"], ".github/workflows/change-scope.yml")
        self.assertEqual(scope["external_id_prefix"], "proof:change-scope:")
        self.assertEqual(scope["artifact_name_prefix"], "proof-change-scope-")
        self.assertEqual(scope["artifact_member"], "proof-evidence.json")

    def test_runtime_rejects_actions_check_without_workflow_path(self) -> None:
        _, _, catalog, providers = contracts()
        providers["providers"]["repository-build"]["checks"]["build"].pop(
            "workflow_path", None
        )
        controls = {control["id"]: control for control in catalog["controls"]}

        with self.assertRaisesRegex(ValueError, "workflow_path"):
            MODULE.validate_provider_config(providers, controls)

    def test_runtime_rejects_overlapping_check_and_review_contracts(self) -> None:
        _, _, catalog, providers = contracts()
        provider = providers["providers"]["repository-build"]
        provider["reviews"] = {"build": {"review_author": "build-reviewer[bot]"}}
        controls = {control["id"]: control for control in catalog["controls"]}

        with self.assertRaisesRegex(
            ValueError,
            "repository-build build cannot declare both a check and a review",
        ):
            MODULE.validate_provider_config(providers, controls)

    def test_runtime_rejects_unsafe_or_duplicate_trusted_paths(self) -> None:
        _, _, catalog, providers = contracts()
        controls = {control["id"]: control for control in catalog["controls"]}
        check = providers["providers"]["repository-build"]["checks"]["build"]
        invalid_values = (
            [],
            [{"path": ".github/workflows/build.yml"}],
            [".github/workflows/build.yml", ".github/workflows/build.yml"],
            ["/etc/passwd"],
            ["../build.yml"],
            ["validators/../build.yml"],
            ["validators\\build.yml"],
        )

        for trusted_paths in invalid_values:
            with self.subTest(trusted_paths=trusted_paths):
                check["trusted_paths"] = trusted_paths
                with self.assertRaisesRegex(ValueError, "trusted_paths"):
                    MODULE.validate_provider_config(providers, controls)

    def test_provider_schema_declares_unique_safe_trusted_paths(self) -> None:
        schema = json.loads(
            (ROOT / "proof" / "providers.schema.json").read_text(encoding="utf-8")
        )

        trusted_paths = schema["$defs"]["check"]["properties"]["trusted_paths"]

        self.assertTrue(trusted_paths["uniqueItems"])
        self.assertEqual(trusted_paths["minItems"], 1)
        self.assertEqual(
            trusted_paths["items"]["pattern"],
            r"^(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)(?!.*\\)[^\u0000-\u001f\u007f]+$",
        )
        self.assertEqual(
            schema["$defs"]["check"]["dependentRequired"]["trusted_paths"],
            ["workflow_path"],
        )

    def test_runtime_rejects_trusted_paths_for_external_app_checks(self) -> None:
        _, _, catalog, providers = contracts()
        controls = {control["id"]: control for control in catalog["controls"]}
        providers["providers"]["alternate-build"]["checks"]["build"]["trusted_paths"] = [
            ".github/workflows/build.yml"
        ]

        with self.assertRaisesRegex(ValueError, "trusted_paths.*workflow_path"):
            MODULE.validate_provider_config(providers, controls)


def evidence(
    authority: str | None = "passed",
    supplemental: str | None = None,
    *,
    revision: str = "abc123",
    subject_type: str = "git-commit",
) -> dict:
    provider_results = {}
    for provider_id, status in (
        ("repository-build", authority),
        ("alternate-build", supplemental),
    ):
        if status is None:
            continue
        result = {"producer": provider_id, "status": status}
        if status in {"passed", "failed"}:
            result["evidence"] = [f"run: {provider_id}"]
        else:
            result["reason"] = "provider did not produce a result"
        provider_results[provider_id] = result
    return {
        "version": 2,
        "subject": {"type": subject_type, "revision": revision},
        "results": {"build": provider_results} if provider_results else {},
    }


class EvaluateV2Tests(unittest.TestCase):
    def evaluate(self, document: dict, *, policy_document: dict | None = None, all_controls: bool = False) -> dict:
        policy, profiles, catalog, providers = contracts()
        return MODULE.evaluate(
            policy_document or policy,
            profiles,
            catalog,
            providers,
            document,
            "change",
            "abc123",
            "git-commit",
            all_catalog_controls=all_controls,
        )

    def test_profile_default_is_advisory_and_override_takes_precedence(self) -> None:
        policy, _, _, _ = contracts()
        policy["overrides"]["change"]["build"] = "enforced"

        result = self.evaluate(evidence("failed"), policy_document=policy)

        self.assertEqual(result["decision"], "block")
        self.assertEqual(result["summary"]["enforced"], {"passed": 0, "total": 1})
        self.assertEqual(result["controls"][0]["effective_mode"], "enforced")

    def test_runtime_rejects_enforced_advisory_only_control(self) -> None:
        for control in ("ai-engineering-review", "functional-qa"):
            with self.subTest(control=control):
                policy, profiles, catalog, providers = contracts()
                policy["overrides"]["change"][control] = "enforced"
                with self.assertRaisesRegex(ValueError, f"{control} is advisory-only"):
                    MODULE.evaluate(
                        policy, profiles, catalog, providers, evidence(),
                        "change", "abc123", "git-commit",
                    )

    def test_selected_profiles_are_additive(self) -> None:
        policy, _, _, _ = contracts()
        policy["profiles"].append("github")
        document = evidence()
        document["results"]["deep-sast"] = {
            "github-codeql": {
                "producer": "GitHub CodeQL",
                "status": "passed",
                "evidence": ["run: 42"],
            }
        }

        result = self.evaluate(document, policy_document=policy)

        self.assertEqual({row["id"] for row in result["controls"]}, {"build", "deep-sast"})
        self.assertEqual(result["summary"]["advisory"], {"passed": 2, "total": 2})

    def test_runtime_requires_exact_core_and_github_profile_definitions(self) -> None:
        policy, profiles, catalog, providers = contracts()
        profiles["profiles"]["extra"] = profiles["profiles"]["github"]

        with self.assertRaisesRegex(ValueError, "exactly core and github"):
            MODULE.evaluate(policy, profiles, catalog, providers, evidence(), "change", "abc123", "git-commit")

        del profiles["profiles"]["extra"]
        del profiles["profiles"]["github"]
        with self.assertRaisesRegex(ValueError, "exactly core and github"):
            MODULE.evaluate(policy, profiles, catalog, providers, evidence(), "change", "abc123", "git-commit")

    def test_runtime_rejects_non_advisory_profile_defaults(self) -> None:
        policy, profiles, catalog, providers = contracts()
        profiles["profiles"]["core"]["defaults"]["change"]["build"] = "enforced"

        with self.assertRaisesRegex(ValueError, "defaults must be advisory"):
            MODULE.evaluate(policy, profiles, catalog, providers, evidence(), "change", "abc123", "git-commit")

    def test_runtime_rejects_missing_control_from_exact_profile_operation_set(self) -> None:
        policy, profiles, catalog, providers = contracts()
        del profiles["profiles"]["core"]["defaults"]["change"]["build"]

        with self.assertRaisesRegex(ValueError, "core change controls must exactly match"):
            MODULE.evaluate(policy, profiles, catalog, providers, evidence(), "change", "abc123", "git-commit")

    def test_runtime_rejects_extra_control_in_exact_profile_operation_set(self) -> None:
        policy, profiles, catalog, providers = contracts()
        profiles["profiles"]["github"]["defaults"]["release"]["deep-sast"] = "advisory"

        with self.assertRaisesRegex(ValueError, "github release controls must exactly match"):
            MODULE.evaluate(policy, profiles, catalog, providers, evidence(), "change", "abc123", "git-commit")

    def test_runtime_rejects_invalid_external_id_prefix(self) -> None:
        policy, profiles, catalog, providers = contracts()
        providers["providers"]["repository-build"]["checks"]["build"]["external_id_prefix"] = ""

        with self.assertRaisesRegex(ValueError, "external_id_prefix"):
            MODULE.evaluate(
                policy,
                profiles,
                catalog,
                providers,
                evidence(),
                "change",
                "abc123",
                "git-commit",
            )

    def test_authoritative_pass_is_the_only_satisfier(self) -> None:
        result = self.evaluate(evidence("passed", "failed"))

        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["status"], "GREEN")
        row = result["controls"][0]
        self.assertEqual(row["authoritative_provider"]["id"], "repository-build")
        self.assertEqual(row["authoritative_evidence_status"], "passed")
        self.assertEqual(row["supplemental"][0]["status"], "failed")

    def test_supplemental_pass_cannot_satisfy_missing_authority(self) -> None:
        result = self.evaluate(evidence(None, "passed"))

        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["status"], "ORANGE")
        self.assertEqual(result["summary"]["advisory"], {"passed": 0, "total": 1})

    def test_authoritative_non_pass_is_orange_in_advisory_and_red_in_enforced(self) -> None:
        for status in ("failed", "blocked", "not_run", None):
            with self.subTest(status=status, mode="advisory"):
                result = self.evaluate(evidence(status))
                self.assertEqual(result["decision"], "allow")
                self.assertEqual(result["status"], "ORANGE")
            with self.subTest(status=status, mode="enforced"):
                policy, _, _, _ = contracts()
                policy["overrides"]["change"]["build"] = "enforced"
                result = self.evaluate(evidence(status), policy_document=policy)
                self.assertEqual(result["decision"], "block")
                self.assertEqual(result["status"], "RED")

    def test_exact_revision_and_subject_type_mismatches_block(self) -> None:
        wrong_subject = evidence(subject_type="artifact")
        wrong_subject["results"] = {}
        for document in (
            evidence(revision="different"),
            wrong_subject,
        ):
            with self.subTest(subject=document["subject"]):
                result = self.evaluate(document)
                self.assertEqual(result["decision"], "block")
                self.assertEqual(result["status"], "RED")
                self.assertEqual(result["findings"][0]["kind"], "subject_mismatch")

    def test_subject_mismatch_makes_all_authoritative_and_supplemental_results_unusable(self) -> None:
        document = evidence("passed", "passed", revision="stale123")

        result = self.evaluate(document)

        row = result["controls"][0]
        self.assertEqual(row["authoritative_evidence_status"], "missing")
        self.assertIsNone(row["authoritative_result"])
        self.assertEqual(row["supplemental"][0]["status"], "missing")
        self.assertIsNone(row["supplemental"][0]["result"])
        mismatch = result["findings"][0]
        self.assertEqual(mismatch["expected_subject"], {"type": "git-commit", "revision": "abc123"})
        self.assertEqual(mismatch["observed_subject"], {"type": "git-commit", "revision": "stale123"})

    def test_unselected_full_catalog_rows_are_gray_and_not_activated(self) -> None:
        result = self.evaluate(evidence(), all_controls=True)
        unselected = {row["id"]: row for row in result["controls"] if row["id"] != "build"}

        self.assertEqual(unselected["deep-sast"]["readiness"], "GRAY")
        self.assertEqual(unselected["deep-sast"]["effective_mode"], "not_activated")
        self.assertEqual(unselected["artifact-sbom"]["readiness"], "GRAY")

    def test_rejects_malformed_nested_evidence_before_evaluation(self) -> None:
        document = evidence()
        document["results"]["build"]["repository-build"]["status"] = "passed"
        del document["results"]["build"]["repository-build"]["evidence"]

        with self.assertRaisesRegex(ValueError, "evidence records"):
            self.evaluate(document)

    def test_rejects_evidence_fields_over_schema_maximum_lengths(self) -> None:
        cases = (
            ("producer", "p" * 201, "not_run", "producer"),
            ("evidence", ["e" * 1001], "not_run", "evidence records"),
            ("reason", "r" * 1001, "passed", "reason"),
        )
        for field, value, status, message in cases:
            with self.subTest(field=field):
                document = evidence(status)
                document["results"]["build"]["repository-build"][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.evaluate(document)


class ChangeScopeEvidenceTests(unittest.TestCase):
    def metadata(self) -> dict:
        return {
            "version": 1,
            "metrics": {
                "files": 2, "added_lines": 20, "changed_lines": 30,
                "max_added_lines_per_file": 12, "binary_files": 0,
                "total_files": 3, "total_added_lines": 25, "total_changed_lines": 40,
                "excluded_files": 1, "excluded_added_lines": 5,
                "excluded_changed_lines": 10, "excluded_binary_files": 0,
            },
            "thresholds": {
                "max_files": 12, "max_added_lines": 300,
                "max_changed_lines": 500, "max_added_lines_per_file": 150,
            },
        }

    def document(self) -> dict:
        return {
            "version": 2, "subject": {"type": "git-commit", "revision": "abc123"},
            "results": {"change-scope": {"repository-change-scope": {
                "producer": "trusted workflow", "status": "passed",
                "evidence": ["artifact://scope"], "change_scope": self.metadata(),
            }}},
        }

    def validate(self, document: dict) -> None:
        _, _, catalog, providers = contracts()
        controls = MODULE.catalog_map(catalog)
        MODULE.validate_evidence(document, controls, providers["providers"])

    def test_metadata_is_optional_and_accepts_valid_pass_and_warning(self) -> None:
        document = self.document()
        self.validate(document)
        row = document["results"]["change-scope"]["repository-change-scope"]
        row["change_scope"]["thresholds"]["max_files"] = 1
        row["status"] = "failed"
        self.validate(document)
        del row["change_scope"]
        self.validate(document)

    def test_rejects_wrong_control_or_provider(self) -> None:
        document = self.document()
        row = document["results"]["change-scope"]["repository-change-scope"]
        document["results"] = {"build": {"repository-build": row}}
        with self.assertRaisesRegex(ValueError, "only valid"):
            self.validate(document)
        _, _, catalog, providers = contracts()
        providers["providers"]["alternate-scope"] = {"capabilities": ["change-scope"]}
        document["results"] = {"change-scope": {"alternate-scope": row}}
        with self.assertRaisesRegex(ValueError, "only valid"):
            MODULE.validate_evidence(document, MODULE.catalog_map(catalog), providers["providers"])

    def test_rejects_malformed_or_inconsistent_metadata(self) -> None:
        cases = [None, {}, {**self.metadata(), "version": True}, {**self.metadata(), "extra": 1}]
        for group, key, value in (
            ("metrics", "files", True), ("metrics", "files", -1),
            ("metrics", "files", 2.0), ("metrics", "files", 2**53),
            ("metrics", "files", float("inf")), ("metrics", "extra", 0),
            ("metrics", "total_added_lines", 24), ("metrics", "binary_files", 3),
            ("metrics", "binary_files", 2), ("metrics", "max_added_lines_per_file", 21),
            ("metrics", "max_added_lines_per_file", 9), ("metrics", "excluded_binary_files", 1),
            ("thresholds", "max_files", True), ("thresholds", "max_files", 0), ("thresholds", "max_files", 1),
            ("thresholds", "extra", 0),
        ):
            value_metadata = copy.deepcopy(self.metadata())
            value_metadata[group][key] = value
            cases.append(value_metadata)
        missing = self.metadata()
        del missing["metrics"]["files"]
        cases.append(missing)
        for metadata in cases:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                MODULE.validate_change_scope(metadata, "passed")
        for status in ("failed", "blocked", "not_run"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                MODULE.validate_change_scope(self.metadata(), status)

    def test_schema_restricts_metadata_to_scope_provider_and_bounded_fields(self) -> None:
        schema = json.loads((ROOT / "proof" / "evidence.schema.json").read_text())
        definitions = schema["$defs"]
        results = schema["properties"]["results"]
        scope = results["properties"]["change-scope"]
        self.assertEqual(scope["properties"]["repository-change-scope"], {"$ref": "#/$defs/result"})
        self.assertEqual(scope["additionalProperties"], {"$ref": "#/$defs/plainResult"})
        self.assertEqual(definitions["providerResults"]["additionalProperties"], {"$ref": "#/$defs/plainResult"})
        self.assertIn({"not": {"required": ["change_scope"]}}, definitions["plainResult"]["allOf"])
        metadata = definitions["changeScope"]
        self.assertFalse(metadata["additionalProperties"])
        for group, minimum in (("metrics", 0), ("thresholds", 1)):
            fields = metadata["properties"][group]
            self.assertFalse(fields["additionalProperties"])
            self.assertEqual(set(fields["required"]), set(self.metadata()[group]))
            for field in fields["properties"].values():
                self.assertEqual(field, {"type": "integer", "minimum": minimum, "maximum": 2**53 - 1})

    def test_zero_counts_and_exact_thresholds_are_valid(self) -> None:
        metadata = self.metadata()
        metadata["metrics"] = dict.fromkeys(metadata["metrics"], 0)
        metadata["thresholds"] = dict.fromkeys(metadata["thresholds"], 1)
        MODULE.validate_change_scope(metadata, "passed")
        metadata = self.metadata()
        metadata["thresholds"] = {"max_files": 2, "max_added_lines": 20, "max_changed_lines": 30, "max_added_lines_per_file": 12}
        MODULE.validate_change_scope(metadata, "passed")


if __name__ == "__main__":
    unittest.main()
