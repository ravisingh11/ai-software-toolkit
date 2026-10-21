from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "render_scorecard_badge.py"
SPEC = importlib.util.spec_from_file_location("render_scorecard_badge", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise AssertionError(f"cannot load module spec: {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


REVISION = "a" * 40
RUN_URL = "https://github.com/owner/repo/actions/runs/12345/attempts/2"
CREATED_AT = "2026-09-08T12:00:00Z"


def scorecard(
    *,
    status: str = "GREEN",
    decision: str = "allow",
    enforced: tuple[int, int] = (10, 10),
    advisory: tuple[int, int] = (4, 4),
    revision: str = REVISION,
) -> dict[str, Any]:
    return {
        "version": 2,
        "status": status,
        "decision": decision,
        "policy": "test-policy",
        "operation": "change",
        "subject": {"type": "git-commit", "revision": revision},
        "enforced": {"passed": enforced[0], "total": enforced[1], "percent": 100.0},
        "advisory": {"passed": advisory[0], "total": advisory[1], "percent": 100.0},
        "controls": [{"id": "private-control", "provider": "secret-provider"}],
        "findings": [{"message": "private-finding"}],
        "evidence": ["https://checks.example/private"],
        "reason": "private-reason",
    }


class RendererTests(unittest.TestCase):
    def test_lifecycle_labels_require_bound_collector_context(self) -> None:
        card = scorecard()
        subject = {"type": "artifact", "revision": "sha256:" + "c" * 64}
        environment = {"type": "environment", "revision": "sha256:" + "d" * 64}
        card["companion_subjects"] = [subject, environment]
        row = {"id": "artifact-sbom", "effective_mode": "advisory", "evidence_status": "passed",
               "authoritative_provider": {"id": "trivy-artifact-sbom"},
               "evidence_subject": "artifact", "evidence_revision": subject["revision"]}
        card["controls"] = [row]
        card["enforced"] = {"passed": 0, "total": 0}
        card["advisory"] = {"passed": 1, "total": 1}
        row["authoritative_result"] = {"status": "passed"}
        with self.assertRaises(ValueError):
            MODULE._lifecycle_context(card, "owner/repo")
        card["lifecycle_verification"] = {
            "version": 1, "scope": "verification", "provenance_verified": True,
            "subjects": {"artifact": subject, "environment": environment},
            "context": {"repository": "owner/repo", "pull_request_number": 1, "head_sha": REVISION,
                        "base_sha": "b" * 40, "run_id": 123, "run_attempt": 1, "workflow_sha": "e" * 40,
                        "artifact_kind": "verification-fixture", "environment_scope": "verification"}}
        self.assertEqual(MODULE._lifecycle_context(card, "owner/repo"), {"artifact-sbom": "Verification artifact"})
        for key, value in (("head_sha", "f" * 40), ("repository", "attacker/repo"), ("run_attempt", 2),
                           ("environment_scope", "production")):
            previous = card["lifecycle_verification"]["context"][key]
            card["lifecycle_verification"]["context"][key] = value
            with self.assertRaises(ValueError):
                MODULE._lifecycle_context(card, "owner/repo")
            card["lifecycle_verification"]["context"][key] = previous
        row["evidence_revision"] = "sha256:" + "0" * 64
        with self.assertRaises(ValueError):
            MODULE._lifecycle_context(card, "owner/repo")

    def test_freshness_runtime_behavior(self) -> None:
        baseline = {
            "version": 1, "operation": "change", "repository": "owner/repo",
            "source_run_id": 12345, "source_run_attempt": 1,
            "source_run_created_at": "2026-10-18T12:00:00Z",
            "published_at": "2026-10-19T12:00:00Z",
            "subject_digest": "sha256:" + "a" * 64,
        }
        result = subprocess.run(
            ["node", str(ROOT / "tooling/tests/scorecard_freshness_harness.cjs")],
            input=json.dumps({"baseline": baseline, "script": MODULE._FRESHNESS_SCRIPT}),
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def write_source(self, root: Path, card: dict[str, Any] | None = None) -> Path:
        source = root / "source"
        source.mkdir()
        (source / "scorecard-20260908-120000Z.json").write_text(
            json.dumps(card or scorecard()) + "\n", encoding="utf-8"
        )
        (source / "scorecard-20260908-120000Z.md").write_text(
            "PRIVATE SOURCE MARKDOWN\n", encoding="utf-8"
        )
        return source

    def render(self, source: Path, output: Path, **overrides: Any) -> dict[str, Any]:
        values = {
            "repository": "owner/repo",
            "run_id": 12345,
            "run_attempt": 2,
            "run_url": RUN_URL,
            "source_run_created_at": CREATED_AT,
            "expected_revision": REVISION,
        }
        values.update(overrides)
        return MODULE.render_badge(source, output, **values)

    def test_green_output_is_bounded_and_contains_public_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            output = root / "published"

            metadata = self.render(source, output)

            digest = hashlib.sha256(REVISION.encode()).hexdigest()
            self.assertEqual(metadata["message"], "GREEN 14/14")
            self.assertEqual(metadata["source_run_id"], 12345)
            self.assertEqual(metadata["source_run_attempt"], 2)
            self.assertEqual(metadata["source_run_created_at"], CREATED_AT)
            self.assertEqual(metadata["subject_digest"], f"sha256:{digest}")
            names = {path.name for path in output.iterdir()}
            self.assertEqual(
                names,
                {
                    "proof-badge.svg",
                    "scorecard.json",
                    "scorecard.md",
                    "index.html",
                },
            )
            for path in output.iterdir():
                text = path.read_text(encoding="utf-8")
                for expected in (
                    "Latest PR Scorecard",
                    "GREEN",
                    "14/14",
                    "change",
                    "owner/repo",
                    "12345",
                    "2",
                    CREATED_AT,
                    digest,
                ):
                    self.assertIn(expected, text, path.name)
                for private in (
                    REVISION,
                    "private-control",
                    "private-finding",
                    "secret-provider",
                    "private-reason",
                    "checks.example",
                    "PRIVATE SOURCE MARKDOWN",
                ):
                    self.assertNotIn(private, text, path.name)
            page = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('.freshness{position:sticky;top:12px;z-index:10;', page)
            self.assertIn(':root{--snapshot-anchor-offset:120px}', page)
            self.assertIn('@media(max-width:800px){:root{--snapshot-anchor-offset:24px}.freshness{position:static}', page)
            self.assertIn('scroll-margin-top:var(--snapshot-anchor-offset)', page)
            self.assertIn('padding:12px;z-index:20}', page)
            self.assertIn('id="snapshot-freshness-status" role="status" aria-live="polite"', page)
            self.assertIn('id="snapshot-refresh" href="?snapshot-refresh=12345-2"', page)
            self.assertIn('<noscript><p>JavaScript is off.', page)
            self.assertIn('Freshness not checked.', page)
            self.assertIn('<span class="brand-name">AI Software Toolkit</span>', page)
            self.assertNotIn('<span class="brand-name">Proof</span>', page)

    def provider_card(self) -> dict[str, Any]:
        card = scorecard(enforced=(0, 0), advisory=(1, 1))
        provider = {"id": "github-codeql", "display_name": "PRIVATE untrusted label"}
        card["controls"] = [
            {"id": "deep-sast", "effective_mode": "advisory", "evidence_status": "passed",
             "authoritative_provider": dict(provider), "configured_provider": dict(provider)},
            {"id": "static-quality", "effective_mode": "not_activated", "evidence_status": "not_activated",
             "authoritative_provider": None,
             "configured_provider": {"id": "sonarqube", "display_name": "SonarQube"}},
            {"id": "artifact-sbom", "effective_mode": "not_activated", "evidence_status": "not_activated",
             "authoritative_provider": None, "configured_provider": None},
        ]
        return card

    def test_default_setup_provider_has_public_label_without_hiding_missing_evidence(self) -> None:
        card = self.provider_card()
        card["status"] = "ORANGE"
        card["advisory"] = {"passed": 0, "total": 1, "percent": 0.0}
        row = card["controls"][0]
        row["evidence_status"] = "no_result"
        provider = {"id": "github-codeql-default-setup", "display_name": "PRIVATE ignored"}
        row["authoritative_provider"] = provider
        row["configured_provider"] = provider
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "published")
            result = next(row for row in metadata["controls"] if row["id"] == "deep-sast")
            self.assertEqual(result["provider"], "GitHub CodeQL default setup")
            self.assertEqual(result["status"], "no_result")
            self.assertEqual(result["mode"], "advisory")

    def test_provider_selection_is_visible_without_changing_activation_or_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "published"
            metadata = self.render(self.write_source(root, self.provider_card()), output)
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["deep-sast"]["provider"], "GitHub CodeQL")
            self.assertEqual(rows["static-quality"]["provider"], "SonarQube")
            self.assertEqual(rows["static-quality"]["status"], "not_activated")
            self.assertEqual(rows["artifact-sbom"]["provider"], "Not configured")
            self.assertEqual(rows["runtime-assurance"]["provider"], "Not reported")
            self.assertEqual((metadata["status"], metadata["decision"], metadata["passed"], metadata["total"]),
                             ("GREEN", "allow", 1, 1))
            for filename in ("index.html", "scorecard.md"):
                text = (output / filename).read_text()
                for label in ("Provider", "GitHub CodeQL", "SonarQube", "Not configured"):
                    self.assertIn(label, text)
            self.assertIn('>GitHub CodeQL</a>', (output / "index.html").read_text())
            for path in output.iterdir():
                self.assertNotIn("PRIVATE", path.read_text())

    def test_missing_evidence_still_names_selected_provider_and_legacy_rows_are_honest(self) -> None:
        card = self.provider_card()
        card.update(status="ORANGE", advisory={"passed": 0, "total": 1})
        card["controls"][0]["evidence_status"] = "no_result"
        del card["controls"][0]["configured_provider"]
        del card["controls"][1]["configured_provider"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "published")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["deep-sast"]["provider"], "GitHub CodeQL")
            self.assertEqual(rows["deep-sast"]["status"], "no_result")
            self.assertEqual(rows["static-quality"]["provider"], "Not reported")

    def test_malformed_conflicting_or_wrong_capability_providers_are_not_published(self) -> None:
        for value in ([], "private", {}, {"id": []}, {"id": "github-codeql"},
                      {"id": "github-codeql", "display_name": ""},
                      {"id": "gitleaks", "display_name": "Private mismatch"}, None):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                card = self.provider_card(); card["controls"][0]["configured_provider"] = value
                root = Path(directory)
                metadata = self.render(self.write_source(root, card), root / "published")
                row = next(row for row in metadata["controls"] if row["id"] == "deep-sast")
                self.assertEqual(row["provider"], "Not reported")
        row = {"configured_provider": {"id": "github-codeql", "display_name": "CodeQL"}}
        self.assertEqual(MODULE._provider_label("build", row), "Not reported")

    def test_custom_provider_identity_is_withheld_from_public_outputs(self) -> None:
        card = self.provider_card()
        provider = {"id": "private-provider", "display_name": "<script>private secret</script>"}
        card["controls"][0].update(configured_provider=provider, authoritative_provider=provider)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "published"
            metadata = self.render(self.write_source(root, card), output)
            row = next(row for row in metadata["controls"] if row["id"] == "deep-sast")
            self.assertEqual(row["provider"], "Configured provider (see source report)")
            for path in output.iterdir():
                text = path.read_text()
                self.assertNotIn("private-provider", text)
                self.assertNotIn("private secret", text)
                self.assertNotIn("<script>", text)

    def test_provider_links_bind_configuration_and_reported_run_to_snapshot(self) -> None:
        urls = ["https://github.com/owner/repo/actions/runs/42",
                "https://github.com/owner/repo/actions/runs/42/attempts/2",
                "https://github.com/owner/repo/actions/runs/42/job/3",
                "https://github.com/owner/repo/actions/runs/42/attempts/2/job/3",
                "https://github.com/owner/repo/runs/91"]
        config_url = f"https://github.com/owner/repo/blob/{REVISION}/.proof/providers.yaml"
        for url in urls:
            for status, result_status in (("passed", "passed"), ("failed", "failed"),
                                          ("blocked", "blocked"), ("no_result", "not_run")):
                with self.subTest(url=url, status=status), tempfile.TemporaryDirectory() as directory:
                    card = self.provider_card()
                    card["repository"] = "private/forged"
                    card["controls"][0].update(evidence_status=status, authoritative_result={
                        "status": result_status, "producer": "GitHub Check: PRIVATE",
                        "evidence": [f"PRIVATE check: run-bound artifact; {url}"]})
                    if status != "passed":
                        card.update(status="ORANGE", advisory={"passed": 0, "total": 1})
                    root = Path(directory); output = root / "published"
                    source = self.write_source(root, card)
                    metadata = self.render(source, output)
                    rows = {row["id"]: row for row in metadata["controls"]}
                    self.assertEqual(rows["deep-sast"]["provider_config_url"], config_url)
                    self.assertEqual(rows["deep-sast"]["provider_run_url"], url)
                    self.assertEqual(rows["deep-sast"]["status"], status)
                    self.assertEqual(rows["static-quality"]["provider_config_url"], config_url)
                    self.assertIsNone(rows["static-quality"]["provider_run_url"])
                    self.assertEqual(rows["artifact-sbom"]["provider_config_url"], config_url)
                    self.assertIsNone(rows["runtime-assurance"]["provider_config_url"])
                    for filename in ("index.html", "scorecard.md", "scorecard.json"):
                        text = (output / filename).read_text()
                        self.assertIn(url, text)
                        self.assertIn(config_url, text)
                        self.assertNotIn("PRIVATE", text)
                        self.assertNotIn("private/forged", text)
                    page = (output / "index.html").read_text()
                    self.assertEqual(page.count(f'href="{url}"'), 3)
                    self.assertIn(f'href="{url}">Open producer result', page)
                    self.assertIn(f"[GitHub CodeQL]({config_url})", (output / "scorecard.md").read_text())
                    self.assertTrue(all(row["provider_config_url"] is None
                                        for row in MODULE.inspect_scorecard(source)["controls"]))

    def test_collector_evidence_formats_publish_only_run_location(self) -> None:
        url = "https://github.com/owner/repo/actions/runs/42/job/7"
        for text in (f"CodeQL: {url}", f"CodeQL: success; {url}",
                     f"CodeQL: run-bound artifact; {url}",
                     f"Meaningful: 5 files, 97 changed lines. Total: 8 files.; {url}",
                     f"Secret Scanning and push protection are enabled with no open alerts.; {url}"):
            with self.subTest(text=text):
                row = self.provider_card()["controls"][0]
                row["authoritative_result"] = {"status": "passed", "evidence": [text]}
                self.assertEqual(MODULE._provider_links(row, "GitHub CodeQL", "owner/repo", REVISION)["provider_run_url"], url)
        row["evidence_status"] = "no_result"
        row["authoritative_result"] = {"status": "not_run", "evidence": [f"CodeQL: skipped; {url}"]}
        self.assertEqual(MODULE._provider_links(row, "GitHub CodeQL", "owner/repo", REVISION)["provider_run_url"], url)

    def test_provider_run_links_reject_unsafe_or_unbound_evidence(self) -> None:
        url = "https://github.com/owner/repo/actions/runs/42"
        unsafe = [url + suffix for suffix in ("?token=secret", "#private", "/extra", "/", "/job/0", "/attempts/0", "\n")]
        unsafe += [url.replace("42", value) for value in ("0", "-1", "01", "%34%32", "４２", "1" * 21)]
        unsafe += [url.replace("github.com", host) for host in
                   ("github.com.evil.example", "user:secret@github.com", "github.com:443", "GITHUB.COM")]
        unsafe += [url.replace("owner/repo", "other/repo"), url.replace("https:", "http:"),
                   "javascript:alert(1)", url.replace("/actions/", "/%61ctions/"), url + "\x7f"]
        values = [[f"CodeQL: {value}"] for value in unsafe]
        values += [None, {}, "CodeQL: " + url, [None, {}, 4], ["x" * 2001],
                   [f"CodeQL: {url}"] * 101, [f"CodeQL: {url} trailing"]]
        for evidence in values:
            with self.subTest(evidence=evidence):
                row = self.provider_card()["controls"][0]
                row["authoritative_result"] = {"status": "passed", "evidence": evidence}
                links = MODULE._provider_links(row, "GitHub CodeQL", "owner/repo", REVISION)
                self.assertIsNone(links["provider_run_url"])
                self.assertIsNotNone(links["provider_config_url"])
        valid_row = self.provider_card()["controls"][0]
        valid_row["authoritative_result"] = {"status": "passed", "evidence": [f"CodeQL: {url}"]}
        mutations = [{"effective_mode": "not_activated"}, {"authoritative_provider": None},
                     {"authoritative_provider": {"id": "gitleaks"}},
                     {"authoritative_result": {"status": "failed", "evidence": [f"CodeQL: {url}"]}},
                     {"configured_provider": {"id": "custom", "display_name": "Private"}},
                     {"authoritative_result": {"status": "passed"}, "supplemental_results": [valid_row["authoritative_result"]]}]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                row = {**valid_row, **mutation}
                self.assertIsNone(MODULE._provider_links(row, MODULE._provider_label("deep-sast", row),
                                                        "owner/repo", REVISION)["provider_run_url"])
        # Skipped and malformed rows never acquire links or become passing evidence.
        card = self.provider_card(); card["controls"][0]["evidence_status"] = "skipped"
        self.assertTrue(all(row["provider_run_url"] is None for row in MODULE._control_details(card, "owner/repo")))

    def test_public_provider_labels_match_builtin_catalog_capabilities(self) -> None:
        config = json.loads((ROOT / "policies/provider-config.yaml").read_text())
        for provider_id, (name, capabilities) in MODULE.PUBLIC_PROVIDERS.items():
            provider = config["providers"][provider_id]
            self.assertEqual(name, provider["display_name"])
            self.assertEqual(set(capabilities), set(provider["capabilities"]))
            for control_id in capabilities:
                value = {"id": provider_id, "display_name": "Not published"}
                self.assertEqual(MODULE._provider_label(control_id, {"configured_provider": value}), name)
        self.assertEqual(set(MODULE.PUBLIC_PROVIDERS), set(config["providers"]))

    def breakdown_card(self) -> dict[str, Any]:
        card = scorecard(status="ORANGE", enforced=(1, 1), advisory=(1, 4))
        card["controls"] = [
            {"id": f"private-{index}", "effective_mode": mode, "evidence_status": status}
            for index, (mode, status) in enumerate([
                ("enforced", "passed"), ("advisory", "passed"),
                ("advisory", "failed"), ("advisory", "blocked"), ("advisory", "no_result"),
                ("not_activated", "not_activated"),
            ])
        ]
        return card

    def test_breakdown_preserves_distinct_results_and_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "published"
            metadata = self.render(self.write_source(root, self.breakdown_card()), output)
            self.assertEqual(metadata["result_breakdown"]["overall"], {
                "passed": 2, "failed": 1, "blocked": 1, "unverified": 1,
            })
            self.assertEqual(metadata["result_breakdown"]["enforced"], {
                "passed": 1, "failed": 0, "blocked": 0, "unverified": 0,
            })
            self.assertEqual(metadata["result_breakdown"]["inactive"], 1)
            page = (output / "index.html").read_text()
            self.assertIn("Selected checks", page)
            self.assertIn("Failed: 1 · Blocked: 1 · Unverified: 1 · Inactive: 1 (excluded)", page)
            self.assertNotIn("not passed", page)
            for filename in ("index.html", "scorecard.md"):
                text = (output / filename).read_text()
                self.assertIn("Inactive", text)
                self.assertIn("Unreported checks are not assumed inactive", text)
                for expected in ("Unverified", "Blocked", "mergeability or release readiness",
                                 "current PR head", "Test totals", MODULE._SIZE_GUIDANCE):
                    self.assertIn(expected, text)
                self.assertNotIn("private-", text)

    def test_missing_evidence_guidance_is_public_safe_and_subject_specific(self) -> None:
        ids = ["iac-misconfiguration", "artifact-provenance", "runtime-soak",
               "dependency-vulnerability", "dependency-remediation", "build"]
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(0, len(ids)))
        card["controls"] = [
            {"id": control_id, "effective_mode": "advisory", "evidence_status": "no_result",
             "reason": "PRIVATE-CANDIDATE-REASON"}
            for control_id in ids
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "published"
            self.render(self.write_source(root, card), output)
            for filename in ("index.html", "scorecard.md"):
                text = (output / filename).read_text()
                for expected in ("evaluated commit", "verification artifact", "verification environment",
                                 "manual Proof Lifecycle", "fork credential withholding",
                                 "SECURITY_SETTINGS_TOKEN", "producer result for this evaluated revision",
                                 "does not establish the exact cause", "not a passing result"):
                    self.assertIn(expected, text)
                self.assertNotIn("PRIVATE-CANDIDATE-REASON", text)

    def test_public_snapshot_identity_and_trusted_base_configuration(self) -> None:
        context = {"pull_request_number": 134, "base_revision": "b" * 40,
                   "runtime_revision": "c" * 40, "publisher_revision": "d" * 40}
        card = scorecard(enforced=(0, 0), advisory=(1, 1))
        card["controls"] = [{"id": "build", "effective_mode": "advisory", "evidence_status": "passed",
                             "configured_provider": {"id": "repository-build", "display_name": "Build"}}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root, card)
            result = self.render(source, root / "site", publication_context=context)
            self.assertEqual(result["snapshot_identity"]["evaluated_revision"], REVISION)
            for filename in ("index.html", "scorecard.md"):
                text = (root / "site" / filename).read_text()
                for expected in ("/pull/134", "/commit/" + REVISION, "PR base", "Policy / runtime", "Page renderer",
                                 "GitHub required merge checks are separate"):
                    self.assertIn(expected, text)
            self.assertIn("/blob/" + "c" * 40, next(row for row in result["controls"] if row["id"] == "build")["provider_config_url"])
            context["runtime_revision"] = None
            self.render(source, root / "legacy", publication_context=context)
            self.assertIn("Not recorded in this historical source", (root / "legacy/index.html").read_text())
            for overrides in ({"pull_request_number": True}, {"base_revision": "bad"},
                              {"publisher_revision": "<script>"}, {"runtime_revision": []}, {"extra": "private"}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    self.render(source, root / "invalid", publication_context={**context, **overrides})

    def test_known_evidence_conditions_and_manual_checks_are_distinct(self) -> None:
        rows = [
            {"id": "iac-misconfiguration", "effective_mode": "advisory", "evidence_status": "no_result",
             "authoritative_provider": {"id": "trivy-iac-config", "display_name": "Trivy"},
             "authoritative_result": {"status": "no_result", "reason": "Lifecycle evidence unavailable: PR/head/base identity differs"}},
            {"id": "dependency-vulnerability", "effective_mode": "advisory", "evidence_status": "no_result",
             "authoritative_provider": {"id": "snyk-open-source", "display_name": "Snyk"},
             "authoritative_result": {"status": "not_run", "reason": "Waiting is disabled for this provider; its check did not report this revision."}},
            {"id": "pr-metadata", "effective_mode": "advisory", "evidence_status": "failed",
             "authoritative_provider": {"id": "repository-pr-metadata", "display_name": "Metadata"},
             "authoritative_result": {"status": "failed", "evidence": ["Pull-request body is missing required marker: ## Verification",
                                      "Verified metadata producer; https://github.com/owner/repo/runs/123"]}},
        ]
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(0, len(rows)))
        card["controls"] = rows
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "site")
            published = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(published["iac-misconfiguration"]["diagnostic"]["code"], "pr_context_mismatch")
            self.assertEqual(published["dependency-vulnerability"]["diagnostic"]["code"], "provider_not_reported_no_wait")
            page = (root / "site/index.html").read_text()
            for expected in ("Evidence rejected", "not to wait", "## Verification", "Open producer result",
                             "Manual lifecycle checks needing evidence (1)", "Toolkit policy decision"):
                self.assertIn(expected, page)
            self.assertIn('href="https://github.com/owner/repo/runs/123"', page)
            for reason in MODULE._PUBLIC_REASONS:
                row = {**rows[0], "authoritative_result": {"status": "no_result", "reason": reason}}
                self.assertIsNotNone(MODULE._public_diagnostic(row))
            for bad in ("private reason", ["unhashable"]):
                row = {**rows[0], "authoritative_result": {"status": "no_result", "reason": bad}}
                self.assertIsNone(MODULE._public_diagnostic(row))
            self.assertIsNone(MODULE._public_diagnostic({}))
            self.assertIsNone(MODULE._public_diagnostic({**rows[0], "authoritative_provider": {"id": "private"}}))
            self.assertIsNone(MODULE._public_diagnostic({**rows[0], "evidence_status": "passed"}))
            skipped = {**rows[0], "authoritative_result": {"status": "no_result", "check_execution": {
                "version": 1, "started_at": "2026-09-08T12:00:00Z", "completed_at": "2026-09-08T12:00:00Z",
                "duration_seconds": 0, "conclusion": "skipped"}}}
            self.assertEqual(MODULE._public_diagnostic(skipped)["code"], "producer_skipped")

    def test_inline_metadata_card_links_to_its_bound_evaluation_run(self) -> None:
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(0, 1))
        card["controls"] = [{"id": "pr-metadata", "effective_mode": "advisory", "evidence_status": "failed",
                             "authoritative_provider": {"id": "repository-pr-metadata", "display_name": "Metadata"},
                             "authoritative_result": {"status": "failed", "evidence": [
                                 "Pull-request body is missing required marker: ## Verification"],
                                 "pr_metadata": {"version": 1, "title_matches": True,
                                                 "required_sections": 1, "missing_sections": 1}}}]
        context = {"pull_request_number": 134, "base_revision": "b" * 40,
                   "runtime_revision": None, "publisher_revision": "d" * 40}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "site", publication_context=context)
            row = next(row for row in metadata["controls"] if row["id"] == "pr-metadata")
            self.assertEqual(row["provider_run_url"], RUN_URL)
            page = (root / "site/index.html").read_text()
            self.assertIn(f'href="{RUN_URL}">Open producer result', page)
            self.assertIn("Missing required PR body section: ## Verification", page)

    def test_empty_enforcement_is_not_presented_as_a_passing_check(self) -> None:
        card = scorecard(status="GREEN", enforced=(0, 0), advisory=(1, 1))
        card["controls"] = [
            {"id": "build", "effective_mode": "advisory", "evidence_status": "passed"},
            {"id": "runtime-soak", "effective_mode": "not_activated", "evidence_status": "not_activated"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "published")
            self.assertEqual(metadata["result_breakdown"]["inactive"], 1)
            self.assertEqual(metadata["total"], 1)
            page = (root / "published/index.html").read_text()
            self.assertIn("No checks enforced", page)
            self.assertIn("Inactive: 1 (excluded)", page)
            self.assertNotIn('0<span>/0</span>', page)

    def test_incomplete_or_inconsistent_breakdown_is_unavailable(self) -> None:
        for mutation in ("missing", "empty", "duplicate", "unknown", "mode", "passed", "malformed"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                card = self.breakdown_card()
                if mutation == "missing":
                    del card["controls"]
                elif mutation == "empty":
                    card["controls"] = []
                elif mutation == "duplicate":
                    card["controls"][1]["id"] = card["controls"][0]["id"]
                elif mutation == "unknown":
                    card["controls"][2]["evidence_status"] = "skipped"
                elif mutation == "mode":
                    card["controls"][2]["effective_mode"] = []
                elif mutation == "passed":
                    card["controls"][2]["evidence_status"] = "passed"
                else:
                    card["controls"][2] = None
                root = Path(directory)
                metadata = self.render(self.write_source(root, card), root / "published")
                self.assertEqual(metadata["result_breakdown"], {"availability": "unavailable"})
                self.assertEqual(metadata["passed"], 2)
                page = (root / "published/index.html").read_text()
                self.assertIn("Result breakdown unavailable", page)
                self.assertNotIn("Inactive:", page)
                self.assertNotIn("not passed", page)

    def scope_card(self, *, exceeded: bool = False) -> dict[str, Any]:
        card = scorecard(status="ORANGE" if exceeded else "GREEN", advisory=(3 if exceeded else 4, 4))
        metrics = {"files": 2, "added_lines": 84, "changed_lines": 90,
                   "max_added_lines_per_file": 70, "binary_files": 0,
                   "total_files": 3, "total_added_lines": 92, "total_changed_lines": 100,
                   "excluded_files": 1, "excluded_added_lines": 8,
                   "excluded_changed_lines": 10, "excluded_binary_files": 0}
        card["controls"].append({"id": "change-scope", "effective_mode": "advisory",
            "authoritative_provider": {"id": "repository-change-scope"},
            "evidence_status": "failed" if exceeded else "passed",
            "authoritative_result": {"status": "failed" if exceeded else "passed",
                "change_scope": {"version": 1, "metrics": metrics,
                    "thresholds": {"max_files": 1 if exceeded else 12, "max_added_lines": 300,
                        "max_changed_lines": 500, "max_added_lines_per_file": 150},
                    "filenames": ["private-file.py"]}}})
        return card

    def test_scope_table_uses_validated_aggregate_metrics(self) -> None:
        for exceeded in (False, True):
            with self.subTest(exceeded=exceeded), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "published"
                metadata = self.render(self.write_source(root, self.scope_card(exceeded=exceeded)), output)
                self.assertEqual(metadata["change_scope"]["availability"], "available")
                page = (output / "index.html").read_text()
                for phrase in ("Files &amp; lines of code", "Advisory", "does not block", "Counted files", "Excluded", "Added + deleted lines"):
                    self.assertIn(phrase, page)
                self.assertIn("Above limit" if exceeded else "Within limit", page)
                for path in output.iterdir():
                    self.assertNotIn("private-file.py", path.read_text())

    def test_older_scope_evidence_is_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "published"
            metadata = self.render(self.write_source(root), output)
            self.assertEqual(metadata["change_scope"]["availability"], "unavailable")
            self.assertIn("Measurements unavailable", (output / "index.html").read_text())

    def test_enforced_scope_labels_blocking_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            card = self.scope_card(exceeded=True)
            card.update(status="RED", decision="block", enforced={"passed": 9, "total": 10}, advisory={"passed": 4, "total": 4})
            card["controls"][-1]["effective_mode"] = "enforced"
            output = root / "published"
            self.render(self.write_source(root, card), output)
            page = (output / "index.html").read_text()
            self.assertIn("Exceeding a limit blocks the policy decision.", page)
            self.assertNotIn("warns only", page)

    def test_untrusted_or_missing_producer_does_not_publish_metrics(self) -> None:
        for field, value in (("authoritative_provider", {"id": "other"}), ("evidence_status", "no_result"), ("effective_mode", "not_activated")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                card = self.scope_card()
                card["controls"][-1][field] = value
                metadata = self.render(self.write_source(root, card), root / "published")
                self.assertEqual(metadata["change_scope"], {"availability": "unavailable"})

    def test_invalid_scope_metrics_are_unavailable(self) -> None:
        for field, value in (("files", True), ("added_lines", -1), ("total_files", 4), ("changed_lines", 1), ("excluded_binary_files", 1)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                card = self.scope_card()
                card["controls"][-1]["authoritative_result"]["change_scope"]["metrics"][field] = value
                metadata = self.render(self.write_source(root, card), root / "published")
                self.assertEqual(metadata["change_scope"], {"availability": "unavailable"})

    def test_orange_and_red_semantics_render(self) -> None:
        cases = (
            (scorecard(status="ORANGE", advisory=(3, 4)), "ORANGE", "13/14"),
            (
                scorecard(status="RED", decision="block", enforced=(9, 10)),
                "RED",
                "13/14",
            ),
        )
        for index, (card, status, count) in enumerate(cases):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                output = root / f"published-{index}"
                metadata = self.render(self.write_source(root, card), output)
                self.assertEqual(metadata["status"], status)
                self.assertIn(
                    f"{status} {count}", (output / "proof-badge.svg").read_text()
                )

    def test_invalid_scorecard_semantics_fail_without_output(self) -> None:
        invalid_cards = []
        for field, value in (
            ("version", 1),
            ("operation", "release"),
            ("status", "GRAY"),
            ("decision", "maybe"),
        ):
            card = scorecard()
            card[field] = value
            invalid_cards.append(card)
        invalid_cards.extend(
            [
                scorecard(status="GREEN", advisory=(3, 4)),
                scorecard(status="ORANGE"),
                scorecard(status="RED", decision="block"),
                scorecard(status="RED", enforced=(9, 10)),
                scorecard(status="GREEN", decision="block"),
                scorecard(status="RED", decision="allow", enforced=(9, 10)),
                scorecard(enforced=(True, 10)),
                scorecard(enforced=(11, 10)),
                scorecard(enforced=(0, 0), advisory=(0, 0)),
            ]
        )
        card = scorecard()
        card["subject"]["type"] = "artifact"
        invalid_cards.append(card)
        card = scorecard(revision="A" * 40)
        invalid_cards.append(card)
        for field in ("status", "decision"):
            for value in ([], {}, 1, None):
                card = scorecard()
                card[field] = value
                invalid_cards.append(card)

        for index, card in enumerate(invalid_cards):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "published"
                with self.assertRaises(ValueError):
                    self.render(self.write_source(root, card), output)
                self.assertFalse(output.exists())

    def test_invalid_runtime_binding_fails_without_output(self) -> None:
        invalid = (
            {"run_id": 0},
            {"run_attempt": 0},
            {"run_attempt": True},
            {"repository": "owner"},
            {"source_run_created_at": "2026-09-08"},
            {"run_url": "http://github.com/owner/repo/actions/runs/12345/attempts/2"},
            {"run_url": "https://github.com/other/repo/actions/runs/12345/attempts/2"},
            {"run_url": "https://github.com/owner/repo/actions/runs/999/attempts/2"},
            {"expected_revision": "b" * 40},
        )
        for overrides in invalid:
            with (
                self.subTest(overrides=overrides),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                output = root / "published"
                with self.assertRaises(ValueError):
                    self.render(self.write_source(root), output, **overrides)
                self.assertFalse(output.exists())

    def test_invalid_source_layout_is_rejected(self) -> None:
        mutations = (
            "missing_json",
            "duplicate_json",
            "missing_markdown",
            "nested",
            "symlink",
            "large",
        )
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                source = self.write_source(root)
                json_path = next(source.glob("*.json"))
                markdown_path = next(source.glob("*.md"))
                if mutation == "missing_json":
                    json_path.unlink()
                elif mutation == "duplicate_json":
                    (source / "scorecard-20260908-120001Z.json").write_text(
                        json_path.read_text()
                    )
                elif mutation == "missing_markdown":
                    markdown_path.unlink()
                elif mutation == "nested":
                    (source / "nested").mkdir()
                elif mutation == "symlink":
                    markdown_path.unlink()
                    os.symlink(root / "outside.md", markdown_path)
                elif mutation == "large":
                    markdown_path.write_bytes(b"x" * (MODULE.MAX_MEMBER_BYTES + 1))
                with self.assertRaises(ValueError):
                    self.render(source, root / "published")

    def test_aggregate_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            for index in range(17):
                (source / f"extra-{index}.txt").write_bytes(
                    b"x" * MODULE.MAX_MEMBER_BYTES
                )
            with self.assertRaises(ValueError):
                self.render(source, root / "published")

    def test_execution_details_are_bounded_and_status_consistent(self) -> None:
        execution = {"version": 1, "started_at": "2026-09-27T01:00:00Z",
                     "completed_at": "2026-09-27T01:00:12Z", "duration_seconds": 12,
                     "conclusion": "success"}
        row = {"evidence_status": "passed", "authoritative_result": {"status": "passed", "check_execution": execution}}
        details = MODULE._execution_details(row)
        self.assertEqual(details["duration_seconds"], 12)
        self.assertEqual(details["availability"], "available")
        for mutation in ({"version": True}, {"duration_seconds": True}, {"duration_seconds": 11},
                         {"duration_seconds": -1}, {"conclusion": "failure"}, {"conclusion": []},
                         {"completed_at": "2026-09-27T01:00:12.123456789Z"}, {"completed_at": "invalid"}, {"started_at": "2026-09-27T02:00:00Z"},
                         {"started_at": "2026-09-27T01:00:00+00:99"}, {"started_at": None},
                         {"unexpected": "PRIVATE"}):
            with self.subTest(mutation=mutation):
                changed = {**row, "authoritative_result": {"status": "passed", "check_execution": {**execution, **mutation}}}
                self.assertEqual(MODULE._execution_details(changed), {"availability": "unavailable"})
        contradictory = {**row, "authoritative_result": {"status": "failed", "check_execution": execution}}
        self.assertEqual(MODULE._execution_details(contradictory), {"availability": "unavailable"})
        card = scorecard(enforced=(1, 1), advisory=(0, 0))
        card["controls"] = [{**row, "id": "build", "effective_mode": "enforced"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertIn("12s (12 seconds)", page)
            self.assertIn("Ran for <strong>12s</strong>", page)
            self.assertIn("2026-09-27T01:00:12Z", page)
            self.assertNotIn("Passing evidence reported for this snapshot", page)
            self.assertIn("Counts not reported", page)
            self.assertIn("This report does not include tests passed, failed, skipped, total.", page)

    def test_unknown_rows_are_not_described_as_excluded(self) -> None:
        card = scorecard()
        card["controls"] = [{"id": "build", "effective_mode": "enforced", "evidence_status": "passed"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertNotIn("excluded from the selected-check totals", page)
            self.assertIn("whether they count toward the totals is unknown", page)

    def test_totals_are_reconciled_with_the_listed_checks(self) -> None:
        ids = [row[0] for row in MODULE.PUBLIC_CONTROLS]
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(2, 3))
        card["controls"] = [
            {"id": "build", "effective_mode": "advisory", "evidence_status": "passed"},
            {"id": "unit-tests", "effective_mode": "advisory", "evidence_status": "passed"},
            {"id": "deep-sast", "effective_mode": "advisory", "evidence_status": "failed"},
            *({"id": control_id, "effective_mode": "not_activated", "evidence_status": "not_activated"}
              for control_id in ids if control_id not in {"build", "unit-tests", "deep-sast", "runtime-soak"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            inactive = len(ids) - 4
            self.assertIn(f"The totals count 3 selected checks. Of the {len(ids)} built-in checks listed below, "
                          f"3 are selected, {inactive} are not activated and 1 is not reported. "
                          "Only selected checks count toward the totals; selection does not mean execution or enforcement.", page)
            self.assertLess(page.index('class="metrics-note"'), page.index('id="results-title"'))

    def test_pull_request_checks_are_labeled_as_checked_separately(self) -> None:
        card = scorecard(status="GREEN", enforced=(0, 0), advisory=(1, 1))
        card["controls"] = [
            {"id": "build", "effective_mode": "advisory", "evidence_status": "passed"},
            {"id": "pr-metadata", "effective_mode": "not_activated", "evidence_status": "not_activated",
             "inactive_reason": "other_subject", "evidence_subject": "pull-request"},
            # Only the allowlisted pull-request subject gets the separate label.
            {"id": "deep-sast", "effective_mode": "not_activated", "evidence_status": "not_activated",
             "inactive_reason": "other_subject", "evidence_subject": "<script>"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["pr-metadata"]["separate_subject"], "pull-request")
            self.assertEqual(rows["pr-metadata"]["status"], "not_activated")
            self.assertIsNone(rows["deep-sast"]["separate_subject"])
            page = (root / "output/index.html").read_text()
            card_html = page[page.index('id="check-pr-metadata"'):]
            card_html = card_html[:card_html.index("</article>")]
            self.assertIn("Checked on the PR", card_html)
            self.assertIn("the pull request itself", card_html)
            self.assertNotIn("Not activated", card_html)
            self.assertNotIn("<script>", page)
            self.assertIn("1 is checked on the pull request", page)
            self.assertIn("Checks marked Checked on the PR run against the pull request", page)
            markdown = (root / "output/scorecard.md").read_text()
            self.assertIn("| PR Metadata | `pr-metadata` | Not reported | Not activated | Checked on the PR |", markdown)

    def test_reconciliation_mentions_custom_and_unmatched_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, self.breakdown_card()), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertIn("5 custom checks also count but are not listed by name.", page)
            self.assertNotIn("private-", page)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertIn("Individual results could not be matched to these totals", page)
            self.assertNotIn("Only selected checks count", page)

    def test_durations_are_human_readable(self) -> None:
        for seconds, expected in ((0, "0s"), (59, "59s"), (60, "1m 0s"), (743, "12m 23s"), (3723, "1h 2m 3s")):
            self.assertEqual(MODULE._duration(seconds), expected)

    def test_decision_meaning_reflects_enforcement(self) -> None:
        cases = (
            (scorecard(), "ALLOW means the enforced toolkit controls are satisfied", False),
            (scorecard(status="ORANGE", enforced=(0, 0), advisory=(3, 4)), "not gated by any control", True),
            (scorecard(status="RED", decision="block", enforced=(9, 10)), "BLOCK means at least one enforced control", False),
        )
        for card, expected, ungated in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.render(self.write_source(root, card), root / "output")
                page = (root / "output/index.html").read_text()
                markdown = (root / "output/scorecard.md").read_text()
                self.assertIn(expected, page)
                self.assertIn(expected, markdown)
                self.assertEqual("Advisory only" in page, ungated)
                if card["decision"] == "block":
                    self.assertNotIn("ALLOW means", page)

    def test_attention_counts_unnamed_custom_controls(self) -> None:
        card = self.breakdown_card()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertIn("3 custom controls without a passing result", page)
            self.assertNotIn("private-", page)
        card = scorecard()
        card["controls"] = [{"id": "build", "effective_mode": "enforced", "evidence_status": "passed"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            self.assertNotIn('id="attention-title"', (root / "output/index.html").read_text())

    def measured_card(self, tests: dict[str, Any] | None = None, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
        card = scorecard(status="GREEN", enforced=(0, 0), advisory=(2, 2))
        tests = tests or {"total": 415, "passed": 412, "failed": 0, "skipped": 3}
        coverage = coverage or {"measured_lines": 200, "covered_lines": 182, "threshold_percent": 90}
        card["controls"] = [
            {"id": control_id, "effective_mode": "advisory", "evidence_status": "passed",
             "authoritative_result": {"status": "passed", "measurements": {
                 "version": 1, "source": "pull-request-workflow", kind: values}}}
            for control_id, kind, values in (("unit-tests", "tests", tests), ("changed-code-coverage", "coverage", coverage))
        ]
        return card

    def test_self_reported_measurements_are_labeled_and_replace_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, self.measured_card()), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["unit-tests"]["measurements"]["tests"]["passed"], 412)
            self.assertEqual(rows["build"]["measurements"], {"availability": "unavailable"})
            page = (root / "output/index.html").read_text()
            markdown = (root / "output/scorecard.md").read_text()
            for text in (page, markdown):
                self.assertIn("412 passed · 0 failed · 3 skipped (415 tests)", text)
                self.assertIn("182 of 200 changed lines covered (91.0%) · target 90%", text)
                self.assertIn("not independently verified", text)
            self.assertNotIn("does not include tests passed", page)
            self.assertIn("for CodeQL, for vulnerabilities by severity", page)
            self.assertIn("Test totals, coverage, validator counts, and scanner finding counts, where shown, are "
                          "self-reported", page)

    def test_validator_measurements_are_summarized(self) -> None:
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(2, 3))
        values = (("repository-validation", "passed", "contracts", {"total": 4, "passed": 4, "failed": 0, "not_run": 0}),
                  ("documentation-validation", "failed", "documentation",
                   {"markdown_files": 171, "links_checked": 912, "broken_links": 2, "mapping_failures": 0}),
                  ("repository-ground-truth", "passed", "documents", {"declared": 6, "found": 6, "missing": 0}))
        card["controls"] = [
            {"id": control_id, "effective_mode": "advisory", "evidence_status": status,
             "authoritative_result": {"status": status, "measurements": {
                 "version": 1, "source": "pull-request-workflow", kind: numbers}}}
            for control_id, status, kind, numbers in values
        ]
        rows = {row["id"]: row for row in MODULE._control_details(card)}
        summaries = {control_id: MODULE._measurement_summary(rows[control_id]["measurements"]) for control_id, *_ in values}
        self.assertEqual(summaries, {
            "repository-validation": "4 passed · 0 failed · 0 not run (4 contract groups)",
            "documentation-validation": "171 Markdown files · 912 local links checked · 2 broken · 0 documentation mapping failures",
            "repository-ground-truth": "6 of 6 declared documents found · 0 missing",
        })

    def test_contradictory_validator_measurements_are_unavailable(self) -> None:
        consistent = MODULE._measurements_consistent
        self.assertFalse(consistent("contracts", {"total": 4, "passed": 3, "failed": 0, "not_run": 1}, "passed"))
        self.assertFalse(consistent("contracts", {"total": 4, "passed": 4, "failed": 0, "not_run": 0}, "failed"))
        self.assertFalse(consistent("documentation", {"markdown_files": 1, "links_checked": 1, "broken_links": 2,
                                                      "mapping_failures": 0}, "failed"))
        self.assertFalse(consistent("documentation", {"markdown_files": 1, "links_checked": 1, "broken_links": 0,
                                                      "mapping_failures": 0}, "failed"))
        self.assertFalse(consistent("documents", {"declared": 6, "found": 5, "missing": 1}, "passed"))
        self.assertFalse(consistent("documents", {"declared": 6, "found": 6, "missing": 1}, "failed"))
        self.assertTrue(consistent("documents", {"declared": 6, "found": 5, "missing": 1}, "failed"))
        self.assertFalse(consistent("migrations", {"checked": 1, "failed": 2}, "failed"))
        self.assertFalse(consistent("migrations", {"checked": 2, "failed": 1}, "passed"))
        self.assertTrue(consistent("migrations", {"checked": 0, "failed": 0}, "failed"))

    def test_migration_summary_distinguishes_nothing_to_check(self) -> None:
        summary = MODULE._measurement_summary
        self.assertEqual(summary({"availability": "available", "migrations": {"checked": 0, "failed": 0}}),
                         "No migrations found to check")
        self.assertEqual(summary({"availability": "available", "migrations": {"checked": 12, "failed": 1}}),
                         "12 migrations checked · 1 failed")

    def test_command_owned_checks_explain_exit_status_only(self) -> None:
        build = MODULE._counts_gap("Artifacts produced; build errors", "build")
        self.assertIn("Only the command's exit status is reported", build)
        self.assertIn("artifacts produced, build errors depend on its tools", build)
        self.assertIn("Only the overall result was reported", MODULE._counts_gap("Rules checked", "runtime-soak"))

    def test_scanners_without_collected_counts_say_where_counts_live(self) -> None:
        for control_id, expected in (("deep-sast", "GitHub code scanning"), ("static-quality", "SonarQube server"),
                                     ("dependency-change-review", "Dependency Review check"),
                                     ("dependency-vulnerability", "FOSSA adapter does not export finding counts"),
                                     ("license-compliance", "FOSSA project")):
            with self.subTest(control_id=control_id):
                gap = MODULE._counts_gap("Anything", control_id)
                self.assertIn(expected, gap)
                self.assertNotIn("Anything", gap)
        self.assertEqual(MODULE._counts_gap(MODULE._CHECK_ASSESSMENTS["secret-detection"][3], "secret-detection"),
                         "Only the overall result was reported. This report does not include secret findings.")

    def findings_row(self, control_id: str, status: str, numbers: dict[str, Any]) -> dict[str, Any]:
        return {"id": control_id, "effective_mode": "advisory", "evidence_status": status,
                "authoritative_result": {"status": status, "measurements": {
                    "version": 1, "source": "pull-request-workflow", "findings": numbers}}}

    def test_scanner_findings_are_summarized_by_severity(self) -> None:
        summary = MODULE._measurement_summary
        zero = dict.fromkeys(("total", "critical", "high", "medium", "low", "unrated"), 0)
        for numbers, expected in (
            ({**zero, "total": 17, "high": 1, "medium": 4, "low": 12}, "0 critical · 1 high · 4 medium · 12 low"),
            ({**zero, "total": 1203, "critical": 2, "low": 1200, "unrated": 1},
             "2 critical · 0 high · 0 medium · 1,200 low · 1 unrated"),
            ({**zero, "total": 3, "unrated": 3}, "3 findings · severity not rated by the scanner"),
            ({**zero, "total": 1, "unrated": 1}, "1 finding · severity not rated by the scanner"),
            (zero, "No findings reported"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(summary({"availability": "available", "findings": numbers}), expected)
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(1, 2))
        card["controls"] = [
            self.findings_row("custom-static-analysis", "passed", {**zero, "total": 5, "medium": 1, "low": 4}),
            self.findings_row("secret-detection", "failed", {**zero, "total": 2, "unrated": 2}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["secret-detection"]["measurements"]["findings"]["unrated"], 2)
            page = (root / "output/index.html").read_text()
            markdown = (root / "output/scorecard.md").read_text()
            for text in (page, markdown):
                self.assertIn("0 critical · 0 high · 1 medium · 4 low", text)
                self.assertIn("2 findings · severity not rated by the scanner", text)
            self.assertNotIn("does not include findings by severity.", page)
            self.assertNotIn("does not include secret findings", page)

    def test_snyk_controls_show_finding_counts(self) -> None:
        counts = {"total": 8, "critical": 0, "high": 2, "medium": 5, "low": 1, "unrated": 0}
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(1, 2))
        card["controls"] = [self.findings_row("deep-sast", "passed", counts),
                            self.findings_row("dependency-vulnerability", "failed", counts)]
        rows = {row["id"]: row for row in MODULE._control_details(card)}
        for control_id in ("deep-sast", "dependency-vulnerability"):
            with self.subTest(control_id=control_id):
                self.assertEqual(rows[control_id]["measurements"]["findings"], counts)
                self.assertIn("2 high", MODULE._measurement_summary(rows[control_id]["measurements"]))

    def test_inconsistent_or_misplaced_findings_are_unavailable(self) -> None:
        zero = dict.fromkeys(("total", "critical", "high", "medium", "low", "unrated"), 0)
        self.assertFalse(MODULE._measurements_consistent("findings", {**zero, "total": 2, "low": 1}, "passed"))
        self.assertTrue(MODULE._measurements_consistent("findings", {**zero, "total": 1, "low": 1}, "passed"))
        self.assertTrue(MODULE._measurements_consistent("findings", zero, "failed"))
        card = scorecard(status="GREEN", enforced=(0, 0), advisory=(3, 3))
        card["controls"] = [
            self.findings_row("custom-static-analysis", "passed", {**zero, "total": 2, "low": 1}),
            self.findings_row("static-quality", "passed", zero),
            self.findings_row("secret-detection", "passed", {**zero, "high": "1"}),
        ]
        rows = {row["id"]: row for row in MODULE._control_details(card)}
        self.assertEqual(rows["static-quality"]["status"], "passed")
        for control_id in ("custom-static-analysis", "static-quality", "secret-detection"):
            with self.subTest(control_id=control_id):
                self.assertEqual(rows[control_id]["measurements"], {"availability": "unavailable"})

    def ai_review_card(self, results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(2, len(results)))
        card["controls"] = [{"id": control_id, "effective_mode": "advisory", "evidence_status": result["status"],
                             "authoritative_result": result} for control_id, result in results.items()]
        return card

    def test_ai_review_finding_counts_are_shown_as_advisory_self_reported(self) -> None:
        counts = {"total": 4, "p0": 0, "p1": 1, "p2": 2, "p3": 1, "unresolved_blocking": 1}
        measured = {"version": 1, "source": "pull-request-workflow", "review_findings": counts}
        card = self.ai_review_card({
            "ai-qa-review": {"producer": "GitHub Check: AI QA Review", "status": "failed", "measurements": measured},
            "ai-security-review": {"producer": "GitHub Check: AI Security Review", "status": "passed", "measurements": {
                **measured, "review_findings": dict.fromkeys(counts, 0)}},
            "ai-engineering-review": {"producer": "GitHub Review: Codex Code Review", "status": "passed"},
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["ai-qa-review"]["measurements"]["review_findings"], counts)
            self.assertEqual(rows["ai-engineering-review"]["measurements"],
                             {"availability": "unavailable", "reason": "review_comments"})
            self.assertEqual(rows["ai-repository-standards-review"]["measurements"], {"availability": "unavailable"})
            page = (root / "output/index.html").read_text()
            markdown = (root / "output/scorecard.md").read_text()
            for text in (page, markdown):
                self.assertIn("4 findings: 0 P0 · 1 P1 · 2 P2 · 1 P3 · 1 unresolved P0/P1", text)
                self.assertIn("No findings reported by the AI reviewer", text)
                self.assertIn("AI review is advisory-only", text)
            self.assertIn("- AI QA Review: 4 findings: 0 P0 · 1 P1 · 2 P2 · 1 P3 · 1 unresolved P0/P1 "
                          "(AI review, advisory-only)", markdown)
            qa_card = page[page.index('id="check-ai-qa-review"'):]
            qa_card = qa_card[:qa_card.index("</article>")]
            self.assertIn("the AI provider's judgment", qa_card)
            self.assertNotIn("Counts not reported", qa_card)
            codex_card = page[page.index('id="check-ai-engineering-review"'):]
            codex_card = codex_card[:codex_card.index("</article>")]
            self.assertIn("Only the review state was reported", codex_card)
            self.assertIn("open the pull request&#x27;s reviews", codex_card)
            self.assertNotIn("Only the overall result was reported", codex_card)
            standards = page[page.index('id="check-ai-repository-standards-review"'):]
            standards = standards[:standards.index("</article>")]
            self.assertIn("Finding counts appear only when an AI PR Review adapter packages", standards)

    def test_ai_review_counts_are_arithmetic_only(self) -> None:
        consistent = MODULE._measurements_consistent
        counts = {"total": 3, "p0": 1, "p1": 1, "p2": 1, "p3": 0, "unresolved_blocking": 2}
        for status in ("passed", "failed"):
            self.assertTrue(consistent("review_findings", counts, status))
        self.assertFalse(consistent("review_findings", {**counts, "total": 4}, "failed"))
        self.assertFalse(consistent("review_findings", {**counts, "unresolved_blocking": 3}, "passed"))
        self.assertEqual(MODULE._measurement_summary({"availability": "available", "review_findings": {
            "total": 1, "p0": 0, "p1": 0, "p2": 0, "p3": 1, "unresolved_blocking": 0}}),
            "1 finding: 0 P0 · 0 P1 · 0 P2 · 1 P3 · 0 unresolved P0/P1")
        # A review producer only explains missing counts; it never overrides a check's measurements elsewhere.
        card = self.ai_review_card({"unit-tests": {"producer": "GitHub Review: X", "status": "passed"}})
        rows = {row["id"]: row for row in MODULE._control_details(card)}
        self.assertEqual(rows["unit-tests"]["measurements"], {"availability": "unavailable"})

    def test_coverage_percent_is_floored_and_empty_diffs_are_explicit(self) -> None:
        summary = MODULE._measurement_summary
        self.assertIn("(89.9%)", summary({"availability": "available", "coverage": {
            "measured_lines": 1000, "covered_lines": 899, "threshold_percent": 80}}))
        self.assertEqual(summary({"availability": "available", "coverage": {
            "measured_lines": 0, "covered_lines": 0, "threshold_percent": 80}}), "No measurable changed lines · target 80%")

    def test_invalid_or_contradictory_measurements_are_unavailable(self) -> None:
        for tests, coverage in (
            ({"total": 3, "passed": 2, "failed": 1, "skipped": 0}, None),
            ({"total": 9, "passed": 2, "failed": 0, "skipped": 0}, None),
            (None, {"measured_lines": 10, "covered_lines": 11, "threshold_percent": 90}),
            (None, {"measured_lines": 10, "covered_lines": 5, "threshold_percent": 90}),
        ):
            with self.subTest(tests=tests, coverage=coverage):
                card = self.measured_card(tests, coverage)
                rows = {row["id"]: row for row in MODULE._control_details(card)}
                target = "unit-tests" if tests else "changed-code-coverage"
                self.assertEqual(rows[target]["measurements"], {"availability": "unavailable"})
        card = self.measured_card()
        card["controls"][0]["authoritative_result"]["measurements"]["source"] = "trusted"
        card["controls"][1]["authoritative_result"]["status"] = "failed"
        rows = {row["id"]: row for row in MODULE._control_details(card)}
        self.assertEqual(rows["unit-tests"]["measurements"], {"availability": "unavailable"})
        self.assertEqual(rows["changed-code-coverage"]["measurements"], {"availability": "unavailable"})

    def pr_metadata_card(self, status: str = "passed", **detail: Any) -> dict[str, Any]:
        card = scorecard(status="GREEN", enforced=(0, 0), advisory=(1 if status == "passed" else 0, 1))
        values = {"version": 1, "title_matches": True, "required_sections": 3, "missing_sections": 0, **detail}
        card["controls"] = [{"id": "pr-metadata", "effective_mode": "advisory", "evidence_status": status,
                             "authoritative_provider": {"id": "repository-pr-metadata"},
                             "authoritative_result": {"status": status, "pr_metadata": values}}]
        return card

    def test_trusted_pr_metadata_detail_replaces_counts_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, self.pr_metadata_card()), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["pr-metadata"]["detail"], {
                "availability": "available", "title_matches": True, "required_sections": 3, "missing_sections": 0})
            self.assertEqual(rows["build"]["detail"], {"availability": "unavailable"})
            page = (root / "output/index.html").read_text()
            card_html = page[page.index('id="check-pr-metadata"'):]
            card_html = card_html[:card_html.index("</article>")]
            markdown = (root / "output/scorecard.md").read_text()
            for text in (card_html, markdown):
                self.assertIn("Title matches the required format · 3 of 3 required sections present", text)
                self.assertIn("trusted base-branch PR metadata validator", text)
            self.assertNotIn("Counts not reported", card_html)
            self.assertNotIn("self-reported", card_html.lower())
            self.assertNotIn("Self-reported measurements", markdown)

    def test_pr_metadata_summary_wording(self) -> None:
        summary = MODULE._pr_metadata_summary
        base = {"availability": "available", "title_matches": False, "missing_sections": 1}
        self.assertEqual(summary({**base, "required_sections": 1}),
                         "Title does not match the required format · 0 of 1 required section present")
        self.assertEqual(summary({**base, "missing_sections": 0, "required_sections": 0}),
                         "Title does not match the required format · No required sections configured")
        self.assertIsNone(summary({"availability": "unavailable"}))

    def test_invalid_or_contradictory_pr_metadata_detail_is_unavailable(self) -> None:
        cases = [({"title_matches": 1}, "passed"), ({"missing_sections": 4}, "failed"),
                 ({"required_sections": 21, "missing_sections": 21}, "failed"), ({"required_sections": True}, "passed"),
                 ({"version": 2}, "passed"), ({"extra": 0}, "passed"), ({"missing_sections": 1}, "passed"),
                 ({"title_matches": False}, "passed"), ({}, "failed")]
        for detail, status in cases:
            with self.subTest(detail=detail, status=status):
                rows = {row["id"]: row for row in MODULE._control_details(self.pr_metadata_card(status, **detail))}
                self.assertEqual(rows["pr-metadata"]["detail"], {"availability": "unavailable"})
        for mutate in (lambda row: row.update(authoritative_provider={"id": "other"}),
                       lambda row: row["authoritative_result"].update(status="failed")):
            card = self.pr_metadata_card()
            mutate(card["controls"][0])
            rows = {row["id"]: row for row in MODULE._control_details(card)}
            self.assertEqual(rows["pr-metadata"]["detail"], {"availability": "unavailable"})
        card = self.pr_metadata_card()
        card["controls"][0]["id"] = "build"
        rows = {row["id"]: row for row in MODULE._control_details(card)}
        self.assertEqual(rows["build"]["detail"], {"availability": "unavailable"})

    def test_pr_metadata_without_detail_explains_the_gap(self) -> None:
        card = self.pr_metadata_card()
        del card["controls"][0]["authoritative_result"]["pr_metadata"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            card_html = page[page.index('id="check-pr-metadata"'):]
            self.assertIn("does not include whether the title matches, required sections present and missing.",
                          card_html[:card_html.index("</article>")])

    def test_public_catalog_matches_canonical_controls(self) -> None:
        catalog = json.loads((ROOT / "policies/control-catalog.yaml").read_text())["controls"]
        expected = [(row["id"], "PR Size" if row["id"] == "change-scope" else row["name"], row["purpose"]) for row in catalog]
        self.assertEqual([row[:3] for row in MODULE.PUBLIC_CONTROLS], expected)
        self.assertEqual(set(MODULE._CHECK_ASSESSMENTS), {row["id"] for row in catalog})
        self.assertEqual(SCRIPT.read_bytes(), (ROOT / ".proof/render_scorecard_badge.py").read_bytes())

    def test_individual_checks_preserve_results_without_private_fields(self) -> None:
        card = self.breakdown_card()
        ids = ["build", "unit-tests", "change-scope", "deep-sast", "functional-qa", "runtime-soak"]
        for row, control_id in zip(card["controls"], ids):
            row.update(id=control_id, name="PRIVATE TITLE <script>", reason="PRIVATE REASON",
                       provider="PRIVATE PROVIDER", evidence_url="https://private.example")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual([rows[key]["status"] for key in ids],
                             ["passed", "passed", "failed", "blocked", "no_result", "not_activated"])
            self.assertEqual(rows["artifact-sbom"]["status"], "not_reported")
            for filename in ("index.html", "scorecard.md", "scorecard.json"):
                text = (root / "output" / filename).read_text()
                self.assertIn("PR Size", text)
                for private in ("PRIVATE TITLE", "PRIVATE REASON", "PRIVATE PROVIDER", "private.example"):
                    self.assertNotIn(private, text)
            page = (root / "output/index.html").read_text()
            self.assertEqual(page.count('<article class="check-detail '), len(MODULE.PUBLIC_CONTROLS))
            for label in ("Passed", "Failed", "Blocked", "Unverified", "Not activated", "Not reported"):
                self.assertIn(label, page)
            self.assertIn('href="#size-title"', page)
            self.assertEqual(page.count('scope="rowgroup"'), 4)
            self.assertEqual(page.count('Back to checks ↑'), len(MODULE.PUBLIC_CONTROLS))
            self.assertLess(page.index('</table></div></section><section class="checks"'), page.index('id="check-build"'))
            for control_id, name, *_ in MODULE.PUBLIC_CONTROLS:
                target = "size-title" if control_id == "change-scope" else f"check-{control_id}"
                self.assertIn(f'href="#{target}"', page)
                self.assertEqual(page.count(f'id="{target}"'), 1)
            self.assertIn('<th scope="col">Check</th><th scope="col">Result</th><th scope="col" class="mode-cell">Mode</th>', page)
            self.assertNotIn("Details ↓", page)
            # Checks needing attention lead the page, most severe first, before the totals.
            attention = page[page.index('id="attention-title"'):page.index('<div class="metrics">')]
            self.assertLess(attention.index('href="#size-title"'), attention.index('href="#check-deep-sast"'))
            self.assertLess(attention.index('href="#check-deep-sast"'), attention.index('href="#check-functional-qa"'))
            self.assertNotIn('href="#check-build"', attention)
            # Detail cards: attention first, then passes; inactive checks are grouped last.
            self.assertLess(page.index('id="check-deep-sast"'), page.index('id="check-build"'))
            self.assertLess(page.index('id="check-build"'), page.index('id="inactive-title"'))
            self.assertLess(page.index('id="inactive-title"'), page.index('id="check-runtime-soak"'))
            self.assertIn("Checked elsewhere, not activated, or not reported <span>(", page)
            self.assertIn("Not activated checks are excluded from the selected-check totals.", page)
            self.assertIn("whether they count toward the totals is unknown", page)
            self.assertNotIn("excluded from the totals above", page)
            # PR Size measurements are a subsection of its card, not a nested titled panel.
            scope_card = page[page.index('id="check-change-scope"'):page.index('id="check-deep-sast"')]
            self.assertIn('<h4 id="size-title"', scope_card)
            self.assertNotIn("<h2", scope_card)
            self.assertEqual(scope_card.count("Advisory"), 1)
            # Each check shows its canonical catalog ID, in the table row and in its detail heading.
            self.assertIn('<a href="#check-build">Build</a> <code class="check-id">build</code>', page)
            self.assertIn('<h3>Build <code class="check-id">build</code></h3>', page)
            markdown = (root / "output/scorecard.md").read_text()
            self.assertIn("| Check | ID | Provider | Mode | Result | Purpose |", markdown)
            self.assertIn("| Build | `build` |", markdown)
            self.assertIn('aria-label="Source report for Build"', page)
            self.assertNotIn('aria-label="Source report for Artifact SBOM"', page)

    def test_inconsistent_rows_do_not_publish_individual_passes(self) -> None:
        card = scorecard()
        card["controls"] = [{"id": "build", "effective_mode": "enforced", "evidence_status": "passed"}]
        for rows in (card["controls"], card["controls"] * 2, None):
            card["controls"] = rows
            self.assertTrue(all(row["status"] == "not_reported" for row in MODULE._control_details(card)))

    def test_unknown_control_names_remain_private(self) -> None:
        card = scorecard(enforced=(1, 1), advisory=(0, 0))
        card["controls"] = [{"id": "private-customer-control", "effective_mode": "enforced", "evidence_status": "passed"}]
        projected = MODULE._control_details(card)
        self.assertNotIn("private-customer-control", json.dumps(projected))
        self.assertTrue(all(row["status"] == "not_reported" for row in projected))

    def test_inspection_and_pages_urls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            inspected = MODULE.inspect_scorecard(source)
            self.assertEqual(inspected["subject_revision"], REVISION)
            self.assertEqual(inspected["status"], "GREEN")
            self.assertTrue(all(row["status"] == "not_reported" for row in inspected["controls"]))
            self.assertEqual(
                MODULE.pages_base_url("owner/repo"), "https://owner.github.io/repo/"
            )
            self.assertEqual(
                MODULE.pages_base_url("owner/owner.github.io"),
                "https://owner.github.io/",
            )

    def test_cli_inspection_and_fail_closed_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            inspection = root / "inspection.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--inspect-output",
                    str(inspection),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(inspection.read_text())["subject_revision"], REVISION
            )

            failed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--output-dir",
                    str(root / "out"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("ERROR", failed.stderr)

    def test_cli_normalizes_unhashable_enum_types_to_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root, {**scorecard(), "status": []})
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--inspect-output",
                    str(root / "inspection.json"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("ERROR", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_backup_cleanup_failure_does_not_undo_committed_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "published"
            output.mkdir()
            (output / "old.txt").write_text("old", encoding="utf-8")
            temporary = root / "temporary"
            temporary.mkdir()
            (temporary / "new.txt").write_text("new", encoding="utf-8")

            with mock.patch.object(
                MODULE.shutil, "rmtree", side_effect=OSError("cleanup failed")
            ):
                MODULE._replace_directory(temporary, output)

            self.assertEqual((output / "new.txt").read_text(encoding="utf-8"), "new")
            self.assertFalse((output / "old.txt").exists())

    def test_deep_json_is_normalized_to_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            json_path = next(source.glob("*.json"))
            json_path.write_text(
                '{"nested":' * 1_500 + "null" + "}" * 1_500, encoding="utf-8"
            )
            output = root / "published"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_text("unchanged", encoding="utf-8")

            with self.assertRaises(ValueError):
                self.render(source, output)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--inspect-output",
                    str(root / "inspection.json"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("ERROR", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_timestamp_overflow_is_normalized_to_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            output = root / "published"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            invalid_timestamp = "0001-01-01T00:00:00+23:59"

            with self.assertRaises(ValueError):
                self.render(source, output, source_run_created_at=invalid_timestamp)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--output-dir",
                    str(output),
                    "--repository",
                    "owner/repo",
                    "--run-id",
                    "12345",
                    "--run-attempt",
                    "2",
                    "--run-url",
                    RUN_URL,
                    "--source-run-created-at",
                    invalid_timestamp,
                    "--expected-revision",
                    REVISION,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("ERROR", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_output_filesystem_failure_is_a_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            parent_file = root / "not-a-directory"
            parent_file.write_text("file", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--output-dir",
                    str(parent_file / "published"),
                    "--repository",
                    "owner/repo",
                    "--run-id",
                    "12345",
                    "--run-attempt",
                    "2",
                    "--run-url",
                    RUN_URL,
                    "--source-run-created-at",
                    CREATED_AT,
                    "--expected-revision",
                    REVISION,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 3)
            self.assertIn("ERROR runtime", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_existing_output_file_is_a_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            output = root / "published"
            output.write_text("consumer file", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--output-dir",
                    str(output),
                    "--repository",
                    "owner/repo",
                    "--run-id",
                    "12345",
                    "--run-attempt",
                    "2",
                    "--run-url",
                    RUN_URL,
                    "--source-run-created-at",
                    CREATED_AT,
                    "--expected-revision",
                    REVISION,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 3)
            self.assertIn("ERROR runtime", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
