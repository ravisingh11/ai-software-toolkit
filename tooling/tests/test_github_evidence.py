from __future__ import annotations

import importlib.util
import copy
import io
import json
import unittest
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest import mock
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "github_evidence.py"
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SPEC = importlib.util.spec_from_file_location("proof_v2_github_evidence", SCRIPT)
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
    base = {"activation": "github", "template": None, "template_available": True, "secrets": [], "enabled_by_default": True}
    providers["providers"]["github-build"] = {**base, "display_name": "GitHub Build", "capabilities": ["build"], "checks": {"build": {"check_name": "Build", "workflow": "Build", "workflow_path": ".github/workflows/build.yml"}}}
    providers["providers"]["external-build"] = {**base, "display_name": "External Build", "activation": "external", "capabilities": ["build"], "checks": {"build": {"check_name": "External Build", "workflow": "External", "app_slug": "external-build"}}, "enabled_by_default": False}
    providers["selections"]["build"] = {"authoritative": "github-build", "supplemental": ["external-build"]}
    return policy, profiles, catalog, providers


def check_run(
    name: str,
    run_id: int,
    *,
    check_id: int | None = None,
    status: str = "completed",
    conclusion: str | None = "success",
    head_sha: str | None = "abc123",
    app_slug: str | None = "github-actions",
    suite_id: int | None = None,
    created_at: str = "2026-08-28T12:00:00Z",
) -> dict:
    check = {
        "id": check_id if check_id is not None else run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "created_at": created_at,
        "details_url": f"https://github.com/owner/repo/actions/runs/{run_id}/job/1",
        "html_url": f"https://github.com/owner/repo/runs/{run_id}",
        "check_suite": {"id": suite_id if suite_id is not None else run_id + 10_000},
    }
    if head_sha is not None:
        check["head_sha"] = head_sha
    if app_slug is not None:
        check["app"] = {"slug": app_slug}
    return check


def artifact_archive(document: dict, member: str = "proof-evidence.json") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, json.dumps(document))
    return buffer.getvalue()


def artifact_contract(
    *,
    check_name: str = "Probe",
    workflow: str = "Probe",
    workflow_path: str = ".github/workflows/probe.yml",
    external_id_prefix: str = "custom:",
    artifact_name_prefix: str = "proof-probe-",
    provider_id: str = "custom-probe",
) -> dict:
    return {
        "check_name": check_name,
        "workflow": workflow,
        "workflow_path": workflow_path,
        "external_id_prefix": external_id_prefix,
        "artifact_name_prefix": artifact_name_prefix,
        "artifact_member": "proof-evidence.json",
        "provider_id": provider_id,
    }


def workflow_run(run_id: int, *, workflow: str = "Probe", path: str = ".github/workflows/probe.yml@refs/heads/main") -> dict:
    return {
        "id": run_id,
        "name": workflow,
        "path": path,
        "check_suite_id": run_id + 10_000,
        "head_sha": "base456",
        "event": "pull_request_target",
        "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
    }


def run_artifact(
    run_id: int,
    *,
    name: str | None = None,
    expired: bool = False,
    artifact_id: int = 77,
    artifact_run_id: int | None = None,
    head_sha: str = "base456",
) -> dict:
    return {
        "id": artifact_id,
        "name": name or f"proof-probe-{run_id}",
        "expired": expired,
        "archive_download_url": f"https://api.github.com/repos/owner/repo/actions/artifacts/{artifact_id}/zip",
        "workflow_run": {
            "id": run_id if artifact_run_id is None else artifact_run_id,
            "head_sha": head_sha,
        },
    }


def artifact_document(
    run_id: int,
    *,
    revision: str = "abc123",
    provider_id: str = "custom-probe",
    status: str = "passed",
    summary: str = "verified",
) -> dict:
    return {
        "version": 1,
        "run_id": run_id,
        "event": "pull_request_target",
        "base_sha": "base456",
        "base_ref": "refs/heads/main",
        "head_sha": revision,
        "revision": revision,
        "repository": "owner/repo",
        "provider_id": provider_id,
        "status": status,
        "summary": summary,
    }


def request_for(payload: dict, workflows: dict[int, str] | None = None):
    workflows = workflows or {}

    def request(url: str, token: str) -> dict:
        if "check-runs" in url:
            response = copy.deepcopy(payload)
            response.setdefault("total_count", len(response.get("check_runs", [])))
            return response
        if "/contents/" in url:
            return {"sha": "trusted-blob"}
        run_id = int(url.rsplit("/", 1)[1])
        workflow = workflows.get(run_id, "Wrong Workflow")
        return {
            "id": run_id,
            "name": workflow,
            "path": f".github/workflows/{workflow.lower().replace(' ', '-')}.yml@main",
            "check_suite_id": run_id + 10_000,
            "head_sha": "abc123",
            "event": "pull_request",
            "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
        }

    return request


class GitHubEvidenceV2Tests(unittest.TestCase):
    def collect(self, payload: dict, workflows: dict[int, str] | None = None) -> dict:
        policy, profiles, catalog, providers = contracts()
        with patch.object(MODULE, "_request", side_effect=request_for(payload, workflows)):
            return MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change", trusted_base_revision="base456",
            )

    def test_collects_only_proven_authoritative_and_supplemental_git_commit_checks(self) -> None:
        payload = {"check_runs": [
            check_run("Build", 101),
            check_run("External Build", 102, app_slug="external-build"),
        ]}

        evidence = self.collect(payload, {101: "Build", 102: "External"})

        self.assertEqual(evidence["subject"], {"type": "git-commit", "revision": "abc123"})
        self.assertEqual(evidence["results"]["build"]["github-build"]["status"], "passed")
        self.assertEqual(evidence["results"]["build"]["external-build"]["status"], "passed")
        self.assertNotIn("deep-sast", evidence["results"])

    def test_collects_codex_review_only_for_exact_head_and_bot_identity(self) -> None:
        policy, profiles, catalog, providers = contracts()
        for control_id in list(policy["overrides"]["change"]):
            policy["overrides"]["change"][control_id] = "not_activated"
        policy["overrides"]["change"]["build"] = "not_activated"
        policy["overrides"]["change"]["ai-engineering-review"] = "advisory"
        providers["selections"]["ai-engineering-review"] = {
            "authoritative": "codex-github-review",
            "supplemental": [],
        }
        reviews = [
            {
                "id": 71,
                "commit_id": "older",
                "state": "COMMENTED",
                "submitted_at": "2026-08-31T11:00:00Z",
                "html_url": "https://github.com/owner/repo/pull/17#pullrequestreview-71",
                "user": {"login": "chatgpt-codex-connector[bot]", "type": "Bot"},
            },
            {
                "id": 72,
                "commit_id": "abc123",
                "state": "COMMENTED",
                "submitted_at": "2026-08-31T12:00:00Z",
                "html_url": "https://github.com/owner/repo/pull/17#pullrequestreview-72",
                "user": {"login": "chatgpt-codex-connector[bot]", "type": "Bot"},
            },
        ]

        with patch.object(MODULE, "_request", return_value=reviews):
            evidence = MODULE.collect_checks(
                "owner/repo",
                "abc123",
                "token",
                policy,
                profiles,
                catalog,
                providers,
                "change",
                pull_request_number=17,
            )

        result = evidence["results"]["ai-engineering-review"]["codex-github-review"]
        self.assertEqual(result["status"], "passed")
        self.assertIn("pullrequestreview-72", result["evidence"][0])

    def test_codex_review_is_not_run_without_pr_or_exact_identity(self) -> None:
        contract = {"review_author": "chatgpt-codex-connector[bot]"}
        wrong_author = [{
            "id": 73,
            "commit_id": "abc123",
            "state": "COMMENTED",
            "submitted_at": "2026-08-31T12:00:00Z",
            "html_url": "https://github.com/owner/repo/pull/17#pullrequestreview-73",
            "user": {"login": "forged-reviewer[bot]", "type": "Bot"},
        }]

        missing = MODULE.collect_review_evidence(
            "owner/repo", "abc123", "token", None, contract, "Codex Code Review"
        )
        with patch.object(MODULE, "_request", return_value=wrong_author):
            forged = MODULE.collect_review_evidence(
                "owner/repo", "abc123", "token", 17, contract, "Codex Code Review"
            )

        self.assertEqual(missing["status"], "not_run")
        self.assertIn("pull-request number", missing["reason"])
        self.assertEqual(forged["status"], "not_run")
        self.assertIn("exact head and reviewer identity", forged["reason"])

    def test_changes_requested_review_is_failed_evidence(self) -> None:
        contract = {"review_author": "chatgpt-codex-connector[bot]"}
        reviews = [{
            "id": 74,
            "commit_id": "abc123",
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-08-31T12:00:00Z",
            "html_url": "https://github.com/owner/repo/pull/17#pullrequestreview-74",
            "user": {"login": "chatgpt-codex-connector[bot]", "type": "Bot"},
        }]

        with patch.object(MODULE, "_request", return_value=reviews):
            result = MODULE.collect_review_evidence(
                "owner/repo", "abc123", "token", 17, contract, "Codex Code Review"
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("CHANGES_REQUESTED", result["evidence"][0])

    def test_duplicate_selected_provider_check_runs_are_terminal_not_run(self) -> None:
        policy, profiles, catalog, providers = contracts()
        queued = {"check_runs": [
            check_run("Build", 201, check_id=1, status="completed", conclusion="success"),
            check_run("Build", 202, check_id=2, status="in_progress", conclusion=None),
            check_run("External Build", 203, status="completed", conclusion="success", app_slug="external-build"),
        ], "total_count": 3}
        with patch.object(MODULE, "_request", return_value=queued) as request:
            with patch.object(MODULE.time, "monotonic", side_effect=[0, 1, 2]):
                with patch.object(MODULE.time, "sleep"):
                    evidence = MODULE.collect_checks(
                        "owner/repo", "abc123", "token", policy, profiles, catalog, providers, "change", wait_seconds=30
                    )

        check_requests = [call.args[0] for call in request.call_args_list if "check-runs" in call.args[0]]
        self.assertEqual(len(check_requests), 2)
        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("duplicate", result["reason"].lower())

    def test_duplicate_matching_check_name_is_not_run(self) -> None:
        payload = {"check_runs": [
            check_run("Build", 301, check_id=9, conclusion="failure", created_at="2026-08-28T13:00:00Z"),
            check_run("Build", 302, check_id=10, conclusion="success", created_at="2026-08-28T12:00:00Z"),
        ]}

        evidence = self.collect(payload, {302: "Build"})

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("duplicate", result["reason"].lower())

    def test_same_name_check_from_different_app_does_not_make_workflow_ambiguous(self) -> None:
        payload = {"check_runs": [
            check_run("Build", 303, app_slug="github-advanced-security", conclusion="neutral"),
            check_run("Build", 304, app_slug="github-actions", conclusion="success"),
        ]}

        evidence = self.collect(payload, {304: "Build"})

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "passed")
        self.assertIn("/runs/304", result["evidence"][0])

    def test_collects_all_pages_for_url_encoded_check_name_before_trusting_exact_path(self) -> None:
        policy, profiles, catalog, providers = contracts()
        providers["providers"]["github-build"]["checks"]["build"]["check_name"] = "Build / Linux"
        page_one = {
            "total_count": 101,
            "check_runs": [
                check_run("Build / Linux", 311),
                *[check_run(f"Unrelated {index}", 1_000 + index) for index in range(99)],
            ],
        }
        page_two = {
            "total_count": 101,
            "check_runs": [check_run("Build / Linux", 312)],
        }
        requested_urls: list[str] = []

        def request(url: str, token: str) -> dict:
            requested_urls.append(url)
            if "check-runs" in url:
                return page_two if "page=2" in url else page_one
            run_id = int(url.rsplit("/", 1)[1])
            return {
                **workflow_run(
                    run_id,
                    workflow="Build",
                    path=(
                        ".github/workflows/forged-build.yml"
                        if run_id == 312
                        else ".github/workflows/build.yml"
                    ),
                ),
                "event": "pull_request",
                "head_sha": "abc123",
            }

        with patch.object(MODULE, "_request", side_effect=request):
            evidence = MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change",
            )

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("duplicate", result["reason"].lower())
        self.assertIn(
            "https://api.github.com/repos/owner/repo/commits/abc123/check-runs"
            "?check_name=Build%20%2F%20Linux&filter=all&per_page=100&page=1",
            requested_urls,
        )
        self.assertIn(
            "https://api.github.com/repos/owner/repo/commits/abc123/check-runs"
            "?check_name=Build%20%2F%20Linux&filter=all&per_page=100&page=2",
            requested_urls,
        )

    def test_filter_all_exposes_duplicates_hidden_by_github_default_latest(self) -> None:
        policy, profiles, catalog, providers = contracts()

        def request(url: str, token: str) -> dict:
            if "check-runs" in url:
                if "filter=all" in url:
                    return {
                        "total_count": 2,
                        "check_runs": [check_run("Build", 321), check_run("Build", 322)],
                    }
                return {"total_count": 1, "check_runs": [check_run("Build", 322)]}
            run_id = int(url.rsplit("/", 1)[1])
            return {
                **workflow_run(run_id, workflow="Build", path=".github/workflows/build.yml"),
                "event": "pull_request",
                "head_sha": "abc123",
            }

        with patch.object(MODULE, "_request", side_effect=request):
            evidence = MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change",
            )

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("duplicate", result["reason"].lower())

    def test_later_check_run_page_failure_is_not_run(self) -> None:
        policy, profiles, catalog, providers = contracts()
        page_one = {
            "total_count": 101,
            "check_runs": [
                check_run("Build", 331),
                *[check_run(f"Unrelated {index}", 2_000 + index) for index in range(99)],
            ],
        }

        def request(url: str, token: str) -> dict:
            if "check-runs" in url:
                if "page=2" in url:
                    raise URLError("page unavailable")
                return page_one
            run_id = int(url.rsplit("/", 1)[1])
            return {
                **workflow_run(run_id, workflow="Build", path=".github/workflows/build.yml"),
                "event": "pull_request",
                "head_sha": "abc123",
            }

        with patch.object(MODULE, "_request", side_effect=request):
            evidence = MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change",
            )

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("complete", result["reason"].lower())

    def test_malformed_check_run_total_count_is_not_run(self) -> None:
        policy, profiles, catalog, providers = contracts()
        malformed_counts = (None, True, "1", -1, 2)

        for total_count in malformed_counts:
            with self.subTest(total_count=total_count), patch.object(
                MODULE,
                "_request",
                return_value={"total_count": total_count, "check_runs": [check_run("Build", 341)]},
            ):
                evidence = MODULE.collect_checks(
                    "owner/repo", "abc123", "token", policy, profiles, catalog,
                    providers, "change",
                )

            result = evidence["results"]["build"]["github-build"]
            self.assertEqual(result["status"], "not_run")
            self.assertIn("complete", result["reason"].lower())

    def test_check_run_total_above_safe_page_limit_fails_without_unbounded_requests(self) -> None:
        policy, profiles, catalog, providers = contracts()
        requested_urls: list[str] = []

        def request(url: str, token: str) -> dict:
            requested_urls.append(url)
            return {
                "total_count": MODULE.MAX_CHECK_RUN_PAGES * MODULE.CHECK_RUNS_PER_PAGE + 1,
                "check_runs": [check_run("Build", 3_000 + index) for index in range(100)],
            }

        with patch.object(MODULE, "_request", side_effect=request):
            evidence = MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change",
            )

        self.assertEqual(evidence["results"]["build"]["github-build"]["status"], "not_run")
        self.assertEqual(len(requested_urls), len(MODULE.expected_checks(
            policy, profiles, catalog, providers, "change"
        )))

    def test_check_run_total_count_change_on_later_page_is_not_run(self) -> None:
        policy, profiles, catalog, providers = contracts()
        page_one = {
            "total_count": 101,
            "check_runs": [
                check_run("Build", 351),
                *[check_run(f"Unrelated {index}", 4_000 + index) for index in range(99)],
            ],
        }
        page_two = {
            "total_count": 100,
            "check_runs": [check_run("Unrelated later page", 4_100)],
        }

        def request(url: str, token: str) -> dict:
            if "check-runs" in url:
                return page_two if "page=2" in url else page_one
            run_id = int(url.rsplit("/", 1)[1])
            return {
                **workflow_run(run_id, workflow="Build", path=".github/workflows/build.yml"),
                "event": "pull_request",
                "head_sha": "abc123",
            }

        with patch.object(MODULE, "_request", side_effect=request):
            evidence = MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change",
            )

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("complete", result["reason"].lower())

    def test_missing_or_skipped_check_is_not_run(self) -> None:
        for payload, reason in (
            ({"check_runs": []}, "did not report"),
            ({"check_runs": [check_run("Build", 401, conclusion="skipped")]}, "skipped"),
        ):
            with self.subTest(reason=reason):
                evidence = self.collect(payload, {401: "Build"})
                result = evidence["results"]["build"]["github-build"]
                self.assertEqual(result["status"], "not_run")
                self.assertIn(reason, result["reason"])

    def test_wrong_or_missing_head_sha_is_untrusted(self) -> None:
        for head_sha in ("different", None):
            with self.subTest(head_sha=head_sha):
                evidence = self.collect({"check_runs": [check_run("Build", 501, head_sha=head_sha)]})
                result = evidence["results"]["build"]["github-build"]
                self.assertEqual(result["status"], "not_run")
                self.assertIn("exact revision", result["reason"])

    def test_non_github_actions_app_is_untrusted(self) -> None:
        evidence = self.collect({"check_runs": [check_run("Build", 601, app_slug="codecov")]})

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("github-actions", result["reason"])

    def test_external_app_check_requires_and_accepts_exact_declared_app_slug(self) -> None:
        contract = {
            "check_name": "External Build",
            "workflow": "External",
            "app_slug": "external-build",
        }

        for app_slug, expected_status in (("external-build", "passed"), ("forged-app", "not_run")):
            with self.subTest(app_slug=app_slug), patch.object(MODULE, "_request") as request:
                result = MODULE.proven_check_evidence(
                    "owner/repo",
                    "abc123",
                    "token",
                    contract,
                    check_run("External Build", 602, app_slug=app_slug),
                    "External Build",
                )

            self.assertEqual(result["status"], expected_status)
            request.assert_not_called()

    def test_declared_workflow_name_must_match_actions_run(self) -> None:
        evidence = self.collect({"check_runs": [check_run("Build", 701)]}, {701: "Different Workflow"})

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("workflow", result["reason"].lower())

    def test_workflow_provenance_lookup_failure_is_not_run(self) -> None:
        policy, profiles, catalog, providers = contracts()

        def request(url: str, token: str) -> dict:
            if "check-runs" in url:
                return {"total_count": 1, "check_runs": [check_run("Build", 702)]}
            raise URLError("workflow lookup unavailable")

        with patch.object(MODULE, "_request", side_effect=request):
            evidence = MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change",
            )

        result = evidence["results"]["build"]["github-build"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("provenance", result["reason"].lower())

    def test_canonical_semgrep_check_fans_out_to_core_and_github_capabilities(self) -> None:
        policy, profiles, catalog, providers = contracts()
        policy["profiles"].append("github")
        policy["overrides"]["change"]["build"] = "not_activated"
        policy["overrides"]["change"]["custom-static-analysis"] = "advisory"
        policy["overrides"]["change"]["deep-sast"] = "advisory"
        providers["selections"]["custom-static-analysis"]["supplemental"] = ["semgrep-app"]
        providers["selections"]["deep-sast"]["supplemental"] = ["semgrep-app"]

        with patch.object(MODULE, "_request", side_effect=request_for(
            {"check_runs": [check_run("Semgrep", 801, app_slug="semgrep-app")]}, {801: "Semgrep"},
        )):
            evidence = MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change",
            )

        core_result = evidence["results"]["custom-static-analysis"]["semgrep-app"]
        github_result = evidence["results"]["deep-sast"]["semgrep-app"]
        self.assertEqual(core_result["status"], "passed")
        self.assertEqual(github_result, core_result)
        self.assertIsNot(github_result, core_result)

    def test_conflicting_check_name_mapping_is_rejected_before_collection(self) -> None:
        policy, profiles, catalog, providers = contracts()
        providers["providers"]["external-build"]["checks"]["build"]["check_name"] = "Build"

        with self.assertRaisesRegex(ValueError, "ambiguous check name"):
            MODULE.expected_checks(policy, profiles, catalog, providers, "change")

    def test_external_id_prefix_is_propagated_without_provider_specific_logic(self) -> None:
        policy, profiles, catalog, providers = contracts()
        check = providers["providers"]["github-build"]["checks"]["build"]
        check["external_id_prefix"] = "custom-probe:"
        check["artifact_name_prefix"] = "proof-build-"
        check["artifact_member"] = "proof-evidence.json"

        expected = MODULE.expected_checks(
            policy, profiles, catalog, providers, "change"
        )

        self.assertEqual(expected["Build"]["external_id_prefix"], "custom-probe:")

    def test_workflow_path_is_propagated_without_provider_specific_logic(self) -> None:
        policy, profiles, catalog, providers = contracts()
        providers["providers"]["github-build"]["checks"]["build"]["workflow_path"] = ".github/workflows/build.yml"

        expected = MODULE.expected_checks(
            policy, profiles, catalog, providers, "change"
        )

        self.assertEqual(expected["Build"]["workflow_path"], ".github/workflows/build.yml")

    def test_trusted_paths_are_propagated_without_provider_specific_logic(self) -> None:
        policy, profiles, catalog, providers = contracts()
        providers["providers"]["github-build"]["checks"]["build"]["trusted_paths"] = [
            ".github/workflows/build.yml",
            ".proof/validators/validate_repository.py",
        ]

        expected = MODULE.expected_checks(
            policy, profiles, catalog, providers, "change"
        )

        self.assertEqual(
            expected["Build"]["trusted_paths"],
            [
                ".github/workflows/build.yml",
                ".proof/validators/validate_repository.py",
            ],
        )

    def test_app_slug_is_propagated_without_provider_specific_logic(self) -> None:
        policy, profiles, catalog, providers = contracts()

        expected = MODULE.expected_checks(
            policy, profiles, catalog, providers, "change"
        )

        self.assertEqual(expected["External Build"]["app_slug"], "external-build")

    def test_artifact_contract_is_propagated_without_provider_specific_logic(self) -> None:
        policy, profiles, catalog, providers = contracts()
        check = providers["providers"]["github-build"]["checks"]["build"]
        check["external_id_prefix"] = "custom-probe:"
        check["artifact_name_prefix"] = "proof-build-"
        check["artifact_member"] = "proof-evidence.json"

        expected = MODULE.expected_checks(
            policy, profiles, catalog, providers, "change"
        )

        self.assertEqual(expected["Build"]["artifact_name_prefix"], "proof-build-")
        self.assertEqual(expected["Build"]["artifact_member"], "proof-evidence.json")

    def test_collector_rejects_non_git_commit_subjects(self) -> None:
        policy, profiles, catalog, providers = contracts()

        with self.assertRaisesRegex(ValueError, "git-commit only"):
            MODULE.collect_checks(
                "owner/repo", "abc123", "token", policy, profiles, catalog,
                providers, "change", subject_type="artifact",
            )

    def test_artifact_download_follows_explicit_https_redirect_without_bearer_header(self) -> None:
        api_url = "https://api.github.com/repos/owner/repo/actions/artifacts/77/zip"
        signed_url = "https://results-receiver.actions.githubusercontent.com/signed/archive.zip"
        archive = artifact_archive(artifact_document(909))
        redirect = HTTPError(api_url, 302, "Found", {"Location": signed_url}, None)
        authenticated_opener = mock.Mock()
        authenticated_opener.open.side_effect = redirect
        download_response = mock.MagicMock()
        download_response.__enter__.return_value.read.return_value = archive

        with patch.object(
            MODULE, "build_opener", return_value=authenticated_opener, create=True
        ), patch.object(MODULE, "urlopen", return_value=download_response) as unsigned_open:
            downloaded = MODULE._request_bytes(api_url, "secret-token")

        self.assertEqual(downloaded, archive)
        self.assertIsNotNone(authenticated_opener.open.call_args)
        authenticated_request = authenticated_opener.open.call_args.args[0]
        self.assertEqual(authenticated_request.get_header("Authorization"), "Bearer secret-token")
        unsigned_request = unsigned_open.call_args.args[0]
        self.assertEqual(unsigned_request.full_url, signed_url)
        self.assertIsNone(unsigned_request.get_header("Authorization"))

    def test_artifact_download_rejects_non_https_redirect(self) -> None:
        api_url = "https://api.github.com/repos/owner/repo/actions/artifacts/77/zip"
        redirect = HTTPError(api_url, 302, "Found", {"Location": "http://storage.invalid/archive.zip"}, None)
        authenticated_opener = mock.Mock()
        authenticated_opener.open.side_effect = redirect

        with patch.object(
            MODULE, "build_opener", return_value=authenticated_opener, create=True
        ), patch.object(MODULE, "urlopen") as unsigned_open:
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                MODULE._request_bytes(api_url, "secret-token")

        unsigned_open.assert_not_called()

    def test_custom_platform_checks_have_proven_workflow_evidence(self) -> None:
        cases = (
            (
                "GitHub Secret Scan",
                "Secret Scan",
                "proof:secret-protection:",
                "proof-secret-protection-",
                "github-secret-protection",
                ".github/workflows/github-secret-protection.yml",
                901,
                {
                    "id": 901,
                    "name": "Secret Scan",
                    "path": ".github/workflows/github-secret-protection.yml@refs/heads/main",
                    "check_suite_id": 29001,
                    "head_sha": "base456",
                    "event": "pull_request_target",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                },
            ),
            (
                "Dependabot Verification",
                "Dependabot Verification",
                "proof:dependabot:",
                "proof-dependabot-",
                "github-dependabot",
                ".github/workflows/dependabot-verification.yml",
                902,
                {
                    "id": 902,
                    "name": "Dependabot Verification",
                    "path": ".github/workflows/dependabot-verification.yml@refs/heads/main",
                    "check_suite_id": 29002,
                    "head_sha": "base456",
                    "event": "pull_request_target",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                },
            ),
        )
        for check_name, workflow, prefix, artifact_prefix, provider_id, workflow_path, run_id, workflow_run in cases:
            artifact = run_artifact(run_id, name=f"{artifact_prefix}{run_id}")
            with self.subTest(check_name=check_name), patch.object(
                MODULE,
                "_request",
                side_effect=[workflow_run, {"total_count": 1, "artifacts": [artifact]}],
            ), patch.object(
                MODULE,
                "_request_bytes",
                return_value=artifact_archive(artifact_document(run_id, provider_id=provider_id)),
            ):
                result = MODULE.proven_check_evidence(
                    "owner/repo",
                    "abc123",
                    "token",
                    {
                        "check_name": check_name,
                        "workflow": workflow,
                        "workflow_path": workflow_path,
                        "external_id_prefix": prefix,
                        "artifact_name_prefix": artifact_prefix,
                        "artifact_member": "proof-evidence.json",
                        "provider_id": provider_id,
                    },
                    {
                        **check_run(check_name, run_id),
                        "external_id": f"{prefix}{run_id}:abc123",
                    },
                    check_name,
                    trusted_base_revision="base456",
                    trusted_workflow_ref="refs/heads/main",
                )

            self.assertEqual(result["status"], "passed")

    def test_forged_external_id_is_not_trusted(self) -> None:
        with patch.object(
            MODULE,
            "_request",
            return_value={"id": 903, "name": "Probe", "head_sha": "abc123", "pull_requests": []},
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                    "external_id_prefix": "custom:",
                },
                {**check_run("Probe", 903), "external_id": "custom:903:forged"},
                "Custom Probe",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("external", result["reason"].lower())

    def test_external_id_only_custom_check_is_not_trusted_without_artifact_contract(self) -> None:
        with patch.object(
            MODULE,
            "_request",
            return_value={
                "id": 904,
                "name": "Probe",
                "path": ".github/workflows/probe.yml@refs/heads/main",
                "check_suite_id": 10904,
                "head_sha": "base456",
                "event": "pull_request_target",
                "pull_requests": [{"head": {"sha": "also-other"}}],
            },
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {"check_name": "Probe", "workflow": "Probe", "workflow_path": ".github/workflows/probe.yml", "external_id_prefix": "custom:"},
                {**check_run("Probe", 904), "external_id": "custom:904:abc123"},
                "Custom Probe",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("artifact contract", result["reason"].lower())

    def test_custom_check_does_not_require_impossible_cross_event_suite_binding(self) -> None:
        artifact = run_artifact(905, name="proof-probe-905")
        with patch.object(
            MODULE,
            "_request",
            side_effect=[
                {
                    "id": 905,
                    "name": "Probe",
                    "path": ".github/workflows/probe.yml@refs/heads/main",
                    "check_suite_id": 99999,
                    "head_sha": "base456",
                    "event": "pull_request_target",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                },
                {"total_count": 1, "artifacts": [artifact]},
            ],
        ), patch.object(
            MODULE,
            "_request_bytes",
            return_value=artifact_archive(artifact_document(905)),
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                    "external_id_prefix": "custom:",
                    "artifact_name_prefix": "proof-probe-",
                    "artifact_member": "proof-evidence.json",
                    "provider_id": "custom-probe",
                },
                {**check_run("Probe", 905), "external_id": "custom:905:abc123"},
                "Custom Probe",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

        self.assertEqual(result["status"], "passed")

    def test_captured_pull_request_target_run_uses_artifact_for_subject_binding(self) -> None:
        live_run = json.loads(
            (FIXTURES / "pull_request_target_workflow_run.json").read_text(encoding="utf-8")
        )
        artifact = run_artifact(909)
        with patch.object(
            MODULE,
            "_request",
            side_effect=[live_run, {"total_count": 1, "artifacts": [artifact]}],
        ), patch.object(
            MODULE,
            "_request_bytes",
            return_value=artifact_archive(artifact_document(909)),
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                artifact_contract(),
                {
                    **check_run("Probe", 909),
                    "external_id": "custom:909:abc123",
                },
                "Custom Probe",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

        self.assertEqual(result["status"], "passed")

    def test_native_actions_check_still_requires_its_workflow_suite(self) -> None:
        with patch.object(
            MODULE,
            "_request",
            return_value={
                "id": 907,
                "name": "Probe",
                "path": ".github/workflows/probe.yml@main",
                "check_suite_id": 99999,
                "head_sha": "abc123",
                "event": "pull_request",
                "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
            },
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                },
                check_run("Probe", 907),
                "Native Probe",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("suite", result["reason"].lower())

    def test_duplicate_workflow_name_at_wrong_path_is_not_trusted(self) -> None:
        with patch.object(
            MODULE,
            "_request",
            return_value={
                "id": 906,
                "name": "Probe",
                "path": ".github/workflows/forged-probe.yml",
                "check_suite_id": 10906,
                "head_sha": "base456",
                "event": "pull_request_target",
                "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
            },
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                    "external_id_prefix": "custom:",
                },
                {**check_run("Probe", 906), "external_id": "custom:906:abc123"},
                "Custom Probe",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("path", result["reason"].lower())

    def test_native_actions_check_without_workflow_path_contract_is_not_trusted(self) -> None:
        with patch.object(MODULE, "_request") as request:
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {"check_name": "Probe", "workflow": "Probe"},
                check_run("Probe", 907),
                "Native Probe",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("workflow path", result["reason"].lower())
        request.assert_not_called()

    def test_native_actions_check_accepts_only_exact_bare_or_ref_suffixed_workflow_path(self) -> None:
        contract = {
            "check_name": "Probe",
            "workflow": "Probe",
            "workflow_path": ".github/workflows/probe.yml",
        }
        cases = (
            (".github/workflows/probe.yml", "passed"),
            (".github/workflows/probe.yml@refs/heads/main", "passed"),
            (".github/workflows/forged-probe.yml", "not_run"),
            (".github/workflows/forged-probe.yml@refs/heads/main", "not_run"),
        )

        for path, expected_status in cases:
            def request(url: str, token: str) -> dict:
                if "/contents/" in url:
                    return {"sha": "trusted-blob"}
                return {
                    "id": 908,
                    "name": "Probe",
                    "path": path,
                    "check_suite_id": 10908,
                    "head_sha": "abc123",
                    "event": "pull_request",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                }

            with self.subTest(path=path), patch.object(
                MODULE, "_request", side_effect=request,
            ):
                result = MODULE.proven_check_evidence(
                    "owner/repo",
                    "abc123",
                    "token",
                    contract,
                    check_run("Probe", 908),
                    "Native Probe",
                    trusted_base_revision="base456",
                )

            self.assertEqual(result["status"], expected_status)

    def test_native_actions_check_rejects_candidate_modified_workflow_definition(self) -> None:
        def request(url: str, token: str) -> dict:
            if "/actions/runs/908" in url:
                return {
                    "id": 908,
                    "name": "Probe",
                    "path": ".github/workflows/probe.yml",
                    "check_suite_id": 10908,
                    "head_sha": "abc123",
                    "event": "pull_request",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                }
            if "ref=abc123" in url:
                return {"sha": "candidate-workflow-blob"}
            if "ref=base456" in url:
                return {"sha": "trusted-workflow-blob"}
            raise AssertionError(f"unexpected request: {url}")

        with patch.object(MODULE, "_request", side_effect=request):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                },
                check_run("Probe", 908),
                "Native Probe",
                trusted_base_revision="base456",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("workflow definition", result["reason"].lower())

    def test_native_actions_check_accepts_same_blob_for_every_trusted_path(self) -> None:
        requested_urls: list[str] = []

        def request(url: str, token: str) -> dict:
            requested_urls.append(url)
            if "/actions/runs/908" in url:
                return {
                    "id": 908,
                    "name": "Probe",
                    "path": ".github/workflows/probe.yml",
                    "check_suite_id": 10908,
                    "head_sha": "abc123",
                    "event": "pull_request",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                }
            return {"sha": "same-blob"}

        with patch.object(MODULE, "_request", side_effect=request):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                    "trusted_paths": [
                        ".github/workflows/probe.yml",
                        ".proof/validators/validate_repository.py",
                    ],
                },
                check_run("Probe", 908),
                "Native Probe",
                trusted_base_revision="base456",
            )

        self.assertEqual(result["status"], "passed")
        self.assertTrue(any("validate_repository.py?ref=abc123" in url for url in requested_urls))
        self.assertTrue(any("validate_repository.py?ref=base456" in url for url in requested_urls))

    def test_native_actions_check_rejects_changed_trusted_path(self) -> None:
        def request(url: str, token: str) -> dict:
            if "/actions/runs/908" in url:
                return {
                    "id": 908,
                    "name": "Probe",
                    "path": ".github/workflows/probe.yml",
                    "check_suite_id": 10908,
                    "head_sha": "abc123",
                    "event": "pull_request",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                }
            if "validate_repository.py" in url and "ref=abc123" in url:
                return {"sha": "candidate-validator"}
            if "validate_repository.py" in url and "ref=base456" in url:
                return {"sha": "trusted-validator"}
            return {"sha": "same-workflow"}

        with patch.object(MODULE, "_request", side_effect=request):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                    "trusted_paths": [
                        ".github/workflows/probe.yml",
                        ".proof/validators/validate_repository.py",
                    ],
                },
                check_run("Probe", 908),
                "Native Probe",
                trusted_base_revision="base456",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("trusted path", result["reason"].lower())

    def test_native_actions_check_always_verifies_workflow_path_in_addition_to_trusted_paths(self) -> None:
        requested_urls: list[str] = []

        def request(url: str, token: str) -> dict:
            requested_urls.append(url)
            if "/actions/runs/908" in url:
                return {
                    "id": 908,
                    "name": "Probe",
                    "path": ".github/workflows/probe.yml",
                    "check_suite_id": 10908,
                    "head_sha": "abc123",
                    "event": "pull_request",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                }
            if "probe.yml" in url and "ref=abc123" in url:
                return {"sha": "candidate-workflow"}
            if "probe.yml" in url and "ref=base456" in url:
                return {"sha": "trusted-workflow"}
            return {"sha": "same-validator"}

        with patch.object(MODULE, "_request", side_effect=request):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                    "trusted_paths": [
                        ".proof/validators/validate_repository.py",
                    ],
                },
                check_run("Probe", 908),
                "Native Probe",
                trusted_base_revision="base456",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("workflow definition", result["reason"].lower())
        self.assertTrue(any("probe.yml?ref=abc123" in url for url in requested_urls))
        self.assertTrue(any("probe.yml?ref=base456" in url for url in requested_urls))

    def test_native_actions_check_requires_trusted_base_revision(self) -> None:
        with patch.object(MODULE, "_request", return_value={
            "id": 908,
            "name": "Probe",
            "path": ".github/workflows/probe.yml",
            "check_suite_id": 10908,
            "head_sha": "abc123",
            "event": "pull_request",
            "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
        }):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                },
                check_run("Probe", 908),
                "Native Probe",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("trusted base revision", result["reason"].lower())

    def test_native_actions_check_fails_closed_when_trusted_path_api_lookup_fails(self) -> None:
        def request(url: str, token: str) -> dict:
            if "/actions/runs/908" in url:
                return {
                    "id": 908,
                    "name": "Probe",
                    "path": ".github/workflows/probe.yml",
                    "check_suite_id": 10908,
                    "head_sha": "abc123",
                    "event": "pull_request",
                    "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}],
                }
            raise URLError("contents unavailable")

        with patch.object(MODULE, "_request", side_effect=request):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                },
                check_run("Probe", 908),
                "Native Probe",
                trusted_base_revision="base456",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("trusted path", result["reason"].lower())

    def test_non_pr_event_or_missing_pull_request_target_head_is_not_trusted(self) -> None:
        fixtures = (
            ("push", [{"number": 17, "head": {"sha": "abc123"}}]),
            ("pull_request_target", [{"number": 17, "head": {"sha": "other"}}]),
        )
        for event, pull_requests in fixtures:
            with self.subTest(event=event, pull_requests=pull_requests), patch.object(
                MODULE,
                "_request",
                return_value={
                    "id": 908,
                    "name": "Probe",
                    "path": ".github/workflows/probe.yml@main",
                    "check_suite_id": 10908,
                    "head_sha": "abc123" if event != "pull_request_target" else "base456",
                    "event": event,
                    "pull_requests": pull_requests,
                },
            ):
                result = MODULE.proven_check_evidence(
                    "owner/repo",
                    "abc123",
                    "token",
                    {"check_name": "Probe", "workflow": "Probe", "workflow_path": ".github/workflows/probe.yml"},
                    check_run("Probe", 908),
                    "Probe",
                )

            self.assertEqual(result["status"], "not_run")
            self.assertIn("pull request", result["reason"].lower())

    def test_native_pull_request_run_accepts_empty_github_pull_requests_array(self) -> None:
        def request(url: str, token: str) -> dict:
            if "/actions/runs/908" in url:
                return {
                    "id": 908,
                    "name": "Probe",
                    "path": ".github/workflows/probe.yml",
                    "check_suite_id": 10908,
                    "head_sha": "abc123",
                    "event": "pull_request",
                    "pull_requests": [],
                }
            if "/contents/" in url:
                return {"sha": "trusted-blob"}
            raise AssertionError(f"unexpected request: {url}")

        with patch.object(MODULE, "_request", side_effect=request):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                {
                    "check_name": "Probe",
                    "workflow": "Probe",
                    "workflow_path": ".github/workflows/probe.yml",
                },
                check_run("Probe", 908),
                "Probe",
                trusted_base_revision="base456",
            )

        self.assertEqual(result["status"], "passed")

    def prove_artifact(
        self,
        *,
        run_id: int = 909,
        check_conclusion: str = "success",
        details_url: str | None = None,
        artifacts: list[dict] | None = None,
        document: dict | None = None,
        member: str = "proof-evidence.json",
        contract: dict | None = None,
    ) -> dict:
        selected_contract = contract or artifact_contract()
        selected_artifacts = artifacts if artifacts is not None else [run_artifact(run_id)]
        selected_document = document or artifact_document(run_id)
        with patch.object(
            MODULE,
            "_request",
            side_effect=[
                workflow_run(run_id),
                {"total_count": len(selected_artifacts), "artifacts": selected_artifacts},
            ],
        ), patch.object(
            MODULE,
            "_request_bytes",
            return_value=artifact_archive(selected_document, member),
        ):
            return MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                selected_contract,
                {
                    **check_run("Probe", run_id, conclusion=check_conclusion),
                    **({"details_url": details_url} if details_url else {}),
                    "external_id": f"custom:{run_id}:abc123",
                },
                "Custom Probe",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

    def test_scope_artifact_preserves_validated_measurements(self) -> None:
        metrics = {
            "files": 1, "added_lines": 84, "changed_lines": 84,
            "max_added_lines_per_file": 84, "binary_files": 0,
            "total_files": 2, "total_added_lines": 92, "total_changed_lines": 92,
            "excluded_files": 1, "excluded_added_lines": 8,
            "excluded_changed_lines": 8, "excluded_binary_files": 0,
        }
        thresholds = {"max_files": 12, "max_added_lines": 300,
                      "max_changed_lines": 500, "max_added_lines_per_file": 150}
        document = artifact_document(909, provider_id="repository-change-scope")
        document.update(metrics=metrics, thresholds=thresholds)
        contract = artifact_contract(provider_id="repository-change-scope")
        result = self.prove_artifact(document=document, contract=contract)
        self.assertEqual(result["change_scope"], {
            "version": 1, "metrics": metrics, "thresholds": thresholds,
        })
        for invalid in (None, {**metrics, "files": True}, {**metrics, "files": -1}):
            with self.subTest(invalid=invalid):
                document["metrics"] = invalid
                result = self.prove_artifact(document=document, contract=contract)
                self.assertEqual(result["status"], "passed")
                self.assertNotIn("change_scope", result)

    def test_pr_metadata_artifact_preserves_validated_detail(self) -> None:
        detail = {"version": 1, "title_matches": True, "required_sections": 3, "missing_sections": 0}
        document = artifact_document(909, provider_id="repository-pr-metadata")
        document["pr_metadata"] = detail
        contract = artifact_contract(provider_id="repository-pr-metadata")
        result = self.prove_artifact(document=document, contract=contract)
        self.assertEqual(result["pr_metadata"], detail)
        for invalid in (None, {**detail, "missing_sections": 1}, {**detail, "title_matches": 1}, "text"):
            with self.subTest(invalid=invalid):
                document["pr_metadata"] = invalid
                result = self.prove_artifact(document=document, contract=contract)
                self.assertEqual(result["status"], "passed")
                self.assertNotIn("pr_metadata", result)
        del document["pr_metadata"]
        self.assertNotIn("pr_metadata", self.prove_artifact(document=document, contract=contract))
        # Only the PR metadata provider may attach this detail.
        document = artifact_document(909)
        document["pr_metadata"] = detail
        self.assertNotIn("pr_metadata", self.prove_artifact(document=document))

    def test_artifact_check_uses_run_id_from_external_id_when_github_rewrites_details_url(self) -> None:
        result = self.prove_artifact(
            details_url="https://github.com/owner/repo/runs/123456",
        )

        self.assertEqual(result["status"], "passed")

    def test_artifact_backed_check_rejects_wrong_explicit_workflow_ref(self) -> None:
        with patch.object(
            MODULE,
            "_request",
            return_value=workflow_run(
                909, path=".github/workflows/probe.yml@refs/heads/attacker"
            ),
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                artifact_contract(),
                {
                    **check_run("Probe", 909),
                    "external_id": "custom:909:abc123",
                },
                "Custom Probe",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("ref", result["reason"].lower())

    def test_candidate_provider_contract_cannot_remove_artifact_proof(self) -> None:
        policy, profiles, catalog, trusted_providers = contracts()
        policy["profiles"].append("github")
        policy["overrides"]["change"]["build"] = "not_activated"
        policy["overrides"]["change"].pop("platform-secret-protection")
        candidate_providers = copy.deepcopy(trusted_providers)
        candidate_check = candidate_providers["providers"]["github-secret-protection"]["checks"]["platform-secret-protection"]
        for field in ("external_id_prefix", "artifact_name_prefix", "artifact_member"):
            candidate_check.pop(field)
        run_id = 910
        forged_check = {
            **check_run("GitHub Secret Scan", run_id),
            "external_id": f"proof:secret-protection:{run_id}:abc123",
        }
        def request(url: str, token: str) -> dict:
            if "check-runs" in url:
                if "check_name=GitHub%20Secret%20Scan" in url:
                    return {"total_count": 1, "check_runs": [forged_check]}
                return {"total_count": 0, "check_runs": []}
            if url.endswith(f"/actions/runs/{run_id}"):
                return workflow_run(
                    run_id,
                    workflow="Secret Scan",
                    path=".github/workflows/github-secret-protection.yml@refs/heads/main",
                )
            if url.endswith(f"/actions/runs/{run_id}/artifacts?name=proof-secret-protection-{run_id}&per_page=100"):
                return {"total_count": 0, "artifacts": []}
            raise AssertionError(f"unexpected request: {url}")

        with patch.object(MODULE, "_request", side_effect=request):
            evidence = MODULE.collect_checks(
                "owner/repo",
                "abc123",
                "token",
                policy,
                profiles,
                catalog,
                trusted_providers,
                "change",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

        self.assertNotIn("artifact_name_prefix", candidate_check)
        result = evidence["results"]["platform-secret-protection"]["github-secret-protection"]
        self.assertEqual(result["status"], "not_run")
        self.assertIn("artifact", result["reason"].lower())

    def test_custom_check_fields_are_display_only_and_artifact_status_is_authoritative(self) -> None:
        result = self.prove_artifact(
            check_conclusion="success",
            document=artifact_document(909, status="failed", summary="provider failed"),
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("provider failed", result["evidence"][0])

    def test_artifact_backed_pull_request_workflow_run_is_not_trusted(self) -> None:
        run_id = 909
        artifact = run_artifact(run_id, head_sha="abc123")
        attacker_run = {
            **workflow_run(run_id),
            "path": ".github/workflows/probe.yml@refs/heads/attacker",
            "head_sha": "abc123",
            "event": "pull_request",
        }
        with patch.object(
            MODULE,
            "_request",
            side_effect=[
                attacker_run,
                {"total_count": 1, "artifacts": [artifact]},
            ],
        ), patch.object(
            MODULE,
            "_request_bytes",
            return_value=artifact_archive(artifact_document(run_id)),
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                artifact_contract(),
                {
                    **check_run("Probe", run_id),
                    "external_id": f"custom:{run_id}:abc123",
                },
                "Custom Probe",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("pull_request_target", result["reason"])

    def test_artifact_contract_without_external_id_still_rejects_pull_request_run(self) -> None:
        contract = artifact_contract()
        contract.pop("external_id_prefix")
        run_id = 909
        with patch.object(
            MODULE,
            "_request",
            return_value={
                **workflow_run(run_id),
                "head_sha": "abc123",
                "event": "pull_request",
            },
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                contract,
                check_run("Probe", run_id),
                "Custom Probe",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

        self.assertEqual(result["status"], "not_run")
        self.assertIn("pull_request_target", result["reason"])

    def test_artifact_backed_neutral_check_uses_raw_failed_status(self) -> None:
        run_id = 910
        neutral_check = {
            **check_run("Probe", run_id, conclusion="neutral"),
            "external_id": f"custom:{run_id}:abc123",
        }
        with patch.object(
            MODULE,
            "_request",
            side_effect=[
                workflow_run(run_id),
                {"total_count": 1, "artifacts": [run_artifact(run_id)]},
            ],
        ), patch.object(
            MODULE,
            "_request_bytes",
            return_value=artifact_archive(
                artifact_document(run_id, status="failed", summary="scope exceeded")
            ),
        ):
            result = MODULE.proven_check_evidence(
                "owner/repo",
                "abc123",
                "token",
                artifact_contract(),
                neutral_check,
                "Custom Probe",
                trusted_base_revision="base456",
                trusted_workflow_ref="refs/heads/main",
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("scope exceeded", result["evidence"][0])

    def test_missing_wrong_expired_duplicate_or_wrong_run_artifact_is_not_trusted(self) -> None:
        cases = (
            ("missing", []),
            ("wrong name", [run_artifact(909, name="forged")]),
            ("expired", [run_artifact(909, expired=True)]),
            ("duplicate", [run_artifact(909, artifact_id=77), run_artifact(909, artifact_id=78)]),
            ("wrong run", [run_artifact(909, artifact_run_id=908)]),
        )
        for label, artifacts in cases:
            with self.subTest(label=label):
                result = self.prove_artifact(artifacts=artifacts)
                self.assertEqual(result["status"], "not_run")
                self.assertIn("artifact", result["reason"].lower())

    def test_wrong_member_revision_provider_or_status_is_not_trusted(self) -> None:
        cases = (
            ("member", artifact_document(909), "forged.json"),
            ("head", artifact_document(909, revision="other"), "proof-evidence.json"),
            ("provider", artifact_document(909, provider_id="forged"), "proof-evidence.json"),
            ("status", artifact_document(909, status="blocked"), "proof-evidence.json"),
        )
        for label, document, member in cases:
            with self.subTest(label=label):
                result = self.prove_artifact(document=document, member=member)
                self.assertEqual(result["status"], "not_run")
                self.assertIn(label, result["reason"].lower())

    def test_wrong_artifact_base_sha_base_ref_or_head_sha_is_not_trusted(self) -> None:
        mutations = (
            ("base sha", {"base_sha": "attacker"}),
            ("base ref", {"base_ref": "refs/heads/attacker"}),
            ("head sha", {"head_sha": "attacker"}),
        )
        for label, mutation in mutations:
            with self.subTest(label=label):
                result = self.prove_artifact(
                    document={**artifact_document(909), **mutation}
                )
                self.assertEqual(result["status"], "not_run")
                self.assertIn(label, result["reason"].lower())

    def test_real_artifact_success_failure_and_no_result_are_preserved(self) -> None:
        for artifact_status, expected in (
            ("passed", "passed"),
            ("failed", "failed"),
            ("not_run", "not_run"),
        ):
            with self.subTest(status=artifact_status):
                result = self.prove_artifact(
                    check_conclusion="failure" if artifact_status == "passed" else "success",
                    document=artifact_document(909, status=artifact_status, summary=f"artifact {artifact_status}"),
                )
                self.assertEqual(result["status"], expected)
                message = result.get("reason") or result["evidence"][0]
                self.assertIn(f"artifact {artifact_status}", message)

    def test_artifact_summary_with_result_url_fits_evidence_schema_limit(self) -> None:
        result = self.prove_artifact(
            document=artifact_document(909, summary="s" * 1000)
        )

        self.assertEqual(result["status"], "passed")
        self.assertLessEqual(len(result["evidence"][0]), 1000)

    def test_native_check_bounds_fully_composed_result_fields(self) -> None:
        check = check_run("n" * 400, 910, conclusion="c" * 1500)
        check["html_url"] = "https://github.com/owner/repo/runs/910/" + "u" * 2000

        result = MODULE.check_run_evidence("build", "GitHub Build", check)

        self.assertLessEqual(len(result["producer"]), 200)
        self.assertLessEqual(len(result["reason"]), 1000)
        self.assertLessEqual(len(result["evidence"][0]), 1000)

    def test_artifact_backed_not_run_bounds_fully_composed_long_url(self) -> None:
        result = self.prove_artifact(
            details_url="https://github.com/owner/repo/actions/runs/909/" + "u" * 2000,
            document=artifact_document(909, status="not_run", summary="s" * 1000),
        )

        self.assertEqual(result["status"], "not_run")
        self.assertLessEqual(len(result["producer"]), 200)
        self.assertLessEqual(len(result["reason"]), 1000)
        self.assertLessEqual(len(result["evidence"][0]), 1000)


class CheckExecutionMetadataTests(unittest.TestCase):
    def check(self) -> dict:
        return {**check_run("Build", 1), "started_at": "2026-09-26T12:00:00Z",
                "completed_at": "2026-09-26T12:01:02.900000Z"}

    def test_completed_check_retains_timing_and_conclusion(self) -> None:
        for conclusion, status in MODULE.CONCLUSIONS.items():
            with self.subTest(conclusion=conclusion):
                check = {**self.check(), "conclusion": conclusion}
                result = MODULE.check_run_evidence("build", "Build", check)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["check_execution"], {
                    "version": 1, "started_at": check["started_at"],
                    "completed_at": check["completed_at"], "duration_seconds": 62,
                    "conclusion": conclusion,
                })

    def test_unusable_optional_metadata_does_not_change_result(self) -> None:
        baseline = MODULE.check_run_evidence("build", "Build", check_run("Build", 1))
        for overrides in (
            {"started_at": None}, {"started_at": 123}, {"completed_at": "bogus"},
            {"completed_at": "2026-09-26T11:00:00Z"},
            {"started_at": "2026-09-26T12:00:00"},
            {"completed_at": "2026-09-31T12:00:00Z"},
            {"status": "in_progress"},
        ):
            with self.subTest(overrides=overrides):
                result = MODULE.check_run_evidence("build", "Build", {**self.check(), **overrides})
                self.assertEqual(result, baseline)


class SelfReportedMeasurementsTests(unittest.TestCase):
    CONTRACT = {"check_name": "Unit Tests", "workflow": "Unit Tests", "provider_id": "repository-unit-tests",
                "workflow_path": ".github/workflows/unit-tests.yml", "control_ids": ["unit-tests"],
                "measurements_artifact_prefix": "proof-measurements-", "measurements_member": "proof-measurements.json"}
    MEASUREMENTS = {"version": 1, "source": "pull-request-workflow",
                    "tests": {"total": 10, "passed": 9, "failed": 0, "skipped": 1}}

    def document(self, **overrides: object) -> dict:
        return {"version": 1, "run_id": 55, "run_attempt": 2, "repository": "owner/repo", "head_sha": "abc123",
                "control": "unit-tests", "measurements": copy.deepcopy(self.MEASUREMENTS), **overrides}

    def fetch(self, document: dict, *, listing: dict | None = None, status: str = "passed",
              contract: dict | None = None, job: dict | None = None, check: dict | None = None) -> object:
        listing = listing or {"total_count": 1, "artifacts": [
            {"id": 9, "name": "proof-measurements-55-2", "expired": False, "workflow_run": {"id": 55}}]}
        job = job or {"id": 1, "run_id": 55, "run_attempt": 2, "head_sha": "abc123"}
        requested: list[str] = []

        def request(url: str, token: str) -> dict:
            requested.append(url)
            return job if "/actions/jobs/" in url else listing

        with mock.patch.object(MODULE, "_request", side_effect=request), \
                mock.patch.object(MODULE, "_request_bytes", return_value=artifact_archive(document, "proof-measurements.json")):
            result = MODULE.self_reported_measurements(
                "owner/repo", "abc123", "token", 55, contract or self.CONTRACT, "unit-tests", status,
                check or check_run("Unit Tests", 55))
        self.requested = requested
        return result

    def test_bound_valid_measurements_are_returned(self) -> None:
        self.assertEqual(self.fetch(self.document()), self.MEASUREMENTS)
        self.assertIn("name=proof-measurements-55-2&", self.requested[1])

    def test_measurements_bind_to_the_checks_own_attempt(self) -> None:
        # A re-run keeps the run ID; an earlier attempt's artifact must not be used.
        self.assertIsNone(self.fetch(self.document(run_attempt=1)))
        stale = {"total_count": 1, "artifacts": [
            {"id": 9, "name": "proof-measurements-55-1", "expired": False, "workflow_run": {"id": 55}}]}
        self.assertIsNone(self.fetch(self.document(run_attempt=1), listing=stale))
        for job in ({"run_id": 56, "run_attempt": 2, "head_sha": "abc123"},
                    {"run_id": 55, "run_attempt": 2, "head_sha": "other"},
                    {"run_id": 55, "run_attempt": True, "head_sha": "abc123"},
                    {"run_id": 55, "run_attempt": 0, "head_sha": "abc123"}):
            with self.subTest(job=job):
                self.assertIsNone(self.fetch(self.document(), job=job))
        for url in ("https://github.com/owner/repo/actions/runs/55", "https://github.com/owner/repo/actions/runs/54/job/1"):
            with self.subTest(url=url):
                self.assertIsNone(self.fetch(self.document(), check={**check_run("Unit Tests", 55), "details_url": url}))

    def test_unbound_or_inconsistent_measurements_are_dropped(self) -> None:
        bad_tests = {**self.MEASUREMENTS, "tests": {"total": 10, "passed": 8, "failed": 1, "skipped": 1}}
        for overrides in ({"run_id": 56}, {"head_sha": "other"}, {"repository": "owner/other"},
                          {"control": "changed-code-coverage"}, {"version": 2}, {"extra": True},
                          {"measurements": bad_tests}, {"measurements": {**self.MEASUREMENTS, "source": "trusted"}}):
            with self.subTest(overrides=overrides):
                self.assertIsNone(self.fetch(self.document(**overrides)))
        self.assertEqual(self.fetch(self.document(measurements=bad_tests), status="failed"), bad_tests)

    def test_missing_expired_duplicate_or_foreign_artifacts_are_dropped(self) -> None:
        artifact = {"id": 9, "name": "proof-measurements-55-2", "expired": False, "workflow_run": {"id": 55}}
        for listing in ({"total_count": 0, "artifacts": []},
                        {"total_count": 2, "artifacts": [artifact, artifact]},
                        {"total_count": 1, "artifacts": [{**artifact, "expired": True}]},
                        {"total_count": 1, "artifacts": [{**artifact, "workflow_run": {"id": 1}}]},
                        {"total_count": 1, "artifacts": [{**artifact, "name": "proof-measurements-55"}]}):
            with self.subTest(listing=listing):
                self.assertIsNone(self.fetch(self.document(), listing=listing))

    def test_no_contract_or_non_result_status_skips_fetching(self) -> None:
        with mock.patch.object(MODULE, "_request", side_effect=AssertionError("no fetch expected")):
            contract = {key: value for key, value in self.CONTRACT.items() if not key.startswith("measurements")}
            self.assertIsNone(MODULE.self_reported_measurements(
                "owner/repo", "abc123", "token", 55, contract, "unit-tests", "passed"))
            self.assertIsNone(MODULE.self_reported_measurements(
                "owner/repo", "abc123", "token", 55, self.CONTRACT, "unit-tests", "not_run"))

    def test_download_errors_leave_the_check_result_unchanged(self) -> None:
        with mock.patch.object(MODULE, "_request", side_effect=OSError("offline")):
            self.assertIsNone(MODULE.self_reported_measurements(
                "owner/repo", "abc123", "token", 55, self.CONTRACT, "unit-tests", "passed"))

    def test_proven_check_attaches_measurements_without_changing_status(self) -> None:
        check = check_run("Unit Tests", 55)
        run = {"id": 55, "name": "Unit Tests", "path": ".github/workflows/unit-tests.yml", "event": "pull_request",
               "head_sha": "abc123", "check_suite_id": 55 + 10_000,
               "pull_requests": [{"number": 17, "head": {"sha": "abc123"}}]}
        baseline = MODULE.check_run_evidence("Unit Tests", "Repository Unit Test Command", check)
        for measurements in (self.MEASUREMENTS, None):
            with self.subTest(measurements=measurements), \
                    mock.patch.object(MODULE, "_request", return_value=run), \
                    mock.patch.object(MODULE, "trusted_paths_match_trusted_base", return_value=True), \
                    mock.patch.object(MODULE, "self_reported_measurements", return_value=measurements):
                result = MODULE.proven_check_evidence(
                    "owner/repo", "abc123", "token", self.CONTRACT, check, "Repository Unit Test Command",
                    trusted_base_revision="base456", trusted_workflow_ref="refs/heads/main")
                expected = {**baseline, "measurements": measurements} if measurements else baseline
                self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
