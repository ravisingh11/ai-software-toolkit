from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "proof_scorecard.py"
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("proof_scorecard", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise AssertionError(f"cannot load module spec: {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture(
    authority: str | None = "passed",
    supplemental: str | None = "failed",
    mode: str = "advisory",
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    profiles = json.loads((ROOT / "policies" / "profiles.yaml").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "policies" / "control-catalog.yaml").read_text(encoding="utf-8"))
    providers = json.loads((ROOT / "policies" / "provider-config.yaml").read_text(encoding="utf-8"))
    policy: dict[str, Any] = {
        "version": 2,
        "name": "test",
        "profiles": ["github"],
        "overrides": {
            "change": {
                "deep-sast": mode,
                "dependency-change-review": "not_activated",
                "platform-secret-protection": "not_activated",
                "dependency-remediation": "not_activated",
            },
            "release": {},
        },
    }
    providers["selections"]["deep-sast"]["supplemental"] = ["snyk-code"]
    results: dict[str, Any] = {}
    for provider_id, status in (("github-codeql", authority), ("snyk-code", supplemental)):
        if status is None:
            continue
        result: dict[str, Any] = {"producer": provider_id, "status": status}
        if status in {"passed", "failed"}:
            result["evidence"] = [f"run: {provider_id}"]
        else:
            result["reason"] = "no result"
        results[provider_id] = result
    evidence = {"version": 2, "subject": {"type": "git-commit", "revision": "abc123"}, "results": {"deep-sast": results}}
    return policy, profiles, catalog, providers, evidence


class ScorecardV2Tests(unittest.TestCase):
    def card(
        self,
        authority: str | None = "passed",
        supplemental: str | None = "failed",
        mode: str = "advisory",
        all_controls: bool = False,
    ) -> dict[str, Any]:
        policy, profiles, catalog, providers, evidence = fixture(authority, supplemental, mode)
        return MODULE.scorecard(policy, profiles, catalog, providers, evidence, "change", "abc123", subject_type="git-commit", all_catalog_controls=all_controls)

    def test_authoritative_pass_stays_green_despite_supplemental_failure(self) -> None:
        card = self.card()

        self.assertEqual(card["version"], 2)
        self.assertEqual(card["status"], "GREEN")
        self.assertEqual(card["decision"], "allow")
        self.assertEqual(card["controls"][0]["evidence_status"], "passed")
        self.assertEqual(card["controls"][0]["supplemental"][0]["status"], "failed")

    def test_missing_authority_is_orange_advisory_and_red_enforced(self) -> None:
        advisory = self.card(None, "passed", "advisory")
        enforced = self.card(None, "passed", "enforced")

        self.assertEqual((advisory["status"], advisory["decision"]), ("ORANGE", "allow"))
        self.assertEqual((enforced["status"], enforced["decision"]), ("RED", "block"))
        self.assertEqual(advisory["controls"][0]["evidence_status"], "no_result")

    def test_full_catalog_marks_unselected_control_gray(self) -> None:
        card = self.card(all_controls=True)
        row = next(control for control in card["controls"] if control["id"] == "static-quality")

        self.assertEqual(row["readiness"], "GRAY")
        self.assertEqual(row["evidence_status"], "not_activated")

    def test_default_output_omits_unselected_and_evidence_only_controls(self) -> None:
        card = self.card()
        control_ids = {control["id"] for control in card["controls"]}

        self.assertEqual(control_ids, {"deep-sast"})
        self.assertNotIn("static-quality", control_ids)
        self.assertNotIn("artifact-sbom", control_ids)

    def test_human_output_renders_capability_and_authoritative_provider_names(self) -> None:
        output = MODULE.render(self.card())

        self.assertIn("Deep SAST — GitHub CodeQL", output)
        self.assertIn("supplemental: Snyk Code=failed", output)
        self.assertNotIn("Activation:", output)

    def test_human_output_explains_non_passing_authoritative_result(self) -> None:
        output = MODULE.render(self.card("failed", None))

        self.assertIn("ORANGE Deep SAST — GitHub CodeQL: failed", output)
        self.assertIn("evidence: run: github-codeql", output)

        output = MODULE.render(self.card("not_run", None))
        self.assertIn("reason: no result", output)

    def test_public_json_recursively_excludes_raw_producer_statuses(self) -> None:
        card = self.card("not_run", None)

        encoded = json.dumps(card, sort_keys=True)
        self.assertNotIn('"not_run"', encoded)
        self.assertNotIn('"missing"', encoded)
        self.assertIn('"no_result"', encoded)


class PullRequestCompanionTests(unittest.TestCase):
    def fixture(self) -> tuple[dict[str, Any], ...]:
        policy, profiles, catalog, providers, evidence = fixture()
        policy["profiles"] = ["core", "github"]
        policy["overrides"]["change"].update({
            control_id: "not_activated"
            for control_id in json.loads((ROOT / "policies" / "profiles.yaml").read_text())["profiles"]["core"]["defaults"]["change"]
        })
        policy["overrides"]["change"]["pr-metadata"] = "advisory"
        return policy, profiles, catalog, providers, evidence

    def test_pull_request_metadata_row_is_scored_beside_commit_checks(self) -> None:
        policy, profiles, catalog, providers, evidence = self.fixture()
        companion = {
            "version": 2,
            "subject": {"type": "pull-request", "revision": "sha256:pr"},
            "results": {"pr-metadata": {"repository-pr-metadata": {
                "producer": "Repository PR Metadata", "status": "failed",
                "evidence": ["Pull-request title does not satisfy title_pattern."],
            }}},
        }
        card = MODULE.scorecard(
            policy, profiles, catalog, providers, evidence, "change", "abc123",
            subject_type="git-commit", all_catalog_controls=True,
            companions=[("pull-request", "sha256:pr", companion)],
        )
        rows = {row["id"]: row for row in card["controls"]}

        self.assertEqual(rows["pr-metadata"]["evidence_status"], "failed")
        self.assertEqual(card["advisory"]["total"], 2)
        self.assertEqual(card["status"], "ORANGE")
        self.assertEqual(card["companion_subjects"], [{"type": "pull-request", "revision": "sha256:pr"}])
        self.assertIn("Companion subject: pull-request@sha256:pr", MODULE.render(card))

    def test_without_companion_the_row_is_marked_as_checked_separately(self) -> None:
        policy, profiles, catalog, providers, evidence = self.fixture()
        card = MODULE.scorecard(
            policy, profiles, catalog, providers, evidence, "change", "abc123",
            subject_type="git-commit", all_catalog_controls=True,
        )
        row = next(row for row in card["controls"] if row["id"] == "pr-metadata")

        self.assertEqual(row["evidence_status"], "not_activated")
        self.assertEqual(row["inactive_reason"], "other_subject")
        self.assertNotIn("companion_subjects", card)
        self.assertIn("PR Metadata — Checked separately on the pull-request subject", MODULE.render(card))

    def test_cli_reports_missing_pull_request_result_as_unverified(self) -> None:
        import subprocess
        import tempfile

        policy, profiles, catalog, providers, evidence = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for name, document in (("policy", policy), ("profiles", profiles), ("catalog", catalog),
                                   ("providers", providers), ("evidence", evidence)):
                paths[name] = root / f"{name}.json"
                paths[name].write_text(json.dumps(document), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), *(f"--{name}={path}" for name, path in paths.items()),
                 "--operation=change", "--revision=abc123", "--subject-type=git-commit",
                 "--all-catalog-controls", "--pull-request-revision=unavailable", "--json"],
                capture_output=True, text=True, check=False,
            )
        card = json.loads(completed.stdout)
        row = next(row for row in card["controls"] if row["id"] == "pr-metadata")

        self.assertEqual(row["evidence_status"], "no_result")
        self.assertEqual(row["effective_mode"], "advisory")
        self.assertEqual(card["advisory"], {"passed": 1, "total": 2, "percent": 50.0})


if __name__ == "__main__":
    unittest.main()
