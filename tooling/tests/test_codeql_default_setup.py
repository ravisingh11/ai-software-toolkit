from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError

SPEC = importlib.util.spec_from_file_location("default_setup_collector", Path(__file__).parents[1] / "github_evidence.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CodeQLDefaultSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = "owner/repo"
        self.api = f"https://api.github.com/repos/{self.repo}"
        self.contract = {"check_name": "CodeQL", "workflow": "CodeQL",
                         "workflow_path": MODULE.CODEQL_DEFAULT_PATH,
                         "provider_id": MODULE.CODEQL_DEFAULT_PROVIDER, "control_ids": ["deep-sast"]}
        self.check = {"id": 44, "name": "CodeQL", "head_sha": "head", "status": "completed",
                      "conclusion": "success", "app": {"id": 57789, "slug": "github-advanced-security"},
                      "check_suite": {"id": 55}}
        self.pr = {"number": 35, "head": {"sha": "head"}, "base": {"sha": "base", "repo": {
            "id": 7, "full_name": self.repo, "owner": {"type": "User"}}}}
        self.setup = {"state": "configured", "languages": ["actions", "javascript", "typescript", "javascript-typescript", "python"],
                      "updated_at": "2026-10-19T18:00:00Z"}
        self.run = {"id": 1, "name": "PR #35", "path": MODULE.CODEQL_DEFAULT_PATH, "event": "dynamic",
                    "head_sha": "head", "head_branch": "refs/pull/35/head", "repository": {"id": 7, "full_name": self.repo},
                    "status": "completed", "conclusion": "success", "run_attempt": 1, "workflow_id": 2,
                    "check_suite_id": 3, "run_started_at": "2026-10-19T18:16:18Z", "updated_at": "2026-10-19T18:17:31Z",
                    "pull_requests": []}
        self.workflow = {"id": 2, "name": "CodeQL", "state": "active", "path": MODULE.CODEQL_DEFAULT_PATH}
        self.jobs = []
        self.checks = []
        self.analyses = []
        for index, language in enumerate(["actions", "javascript-typescript", "python"], 10):
            name = f"Analyze ({language})"
            self.jobs.append({"id": index, "name": name, "run_id": 1, "run_attempt": 1,
                              "head_sha": "head", "status": "completed", "conclusion": "success",
                              "started_at": "2026-10-19T18:16:35Z", "completed_at": "2026-10-19T18:17:29Z"})
            self.checks.append({"id": index, "name": name, "head_sha": "head", "status": "completed", "conclusion": "success",
                                "check_suite": {"id": 3}, "app": {"id": 15368, "slug": "github-actions"}})
            self.analyses.append({"id": index + 100, "commit_sha": "head", "ref": "refs/pull/35/head", "tool": {"name": "CodeQL"},
                                  "environment": json.dumps({"language": language}), "category": f"/language:{language}",
                                  "analysis_key": MODULE.CODEQL_DEFAULT_PATH + ":analyze", "error": "", "warning": "",
                                  "created_at": "2026-10-19T18:17:19Z"})
        self.tree = {"truncated": False, "tree": []}
        self.head_tree = None
        self.properties = []
        self.refresh_checks = [self.check]

    def request(self, url: str, token: str):
        suffix = url.removeprefix(self.api)
        if suffix == "/pulls/35":
            return copy.deepcopy(self.pr)
        if suffix == "/code-scanning/default-setup":
            return copy.deepcopy(self.setup)
        if suffix == "/properties/values":
            return copy.deepcopy(self.properties)
        if suffix.startswith("/actions/runs?"):
            return {"total_count": 1, "workflow_runs": [copy.deepcopy(self.run)]}
        if suffix == "/actions/runs/1":
            return copy.deepcopy(self.run)
        if suffix == "/actions/workflows/2":
            return copy.deepcopy(self.workflow)
        if suffix.startswith("/git/trees/"):
            return copy.deepcopy(self.head_tree if self.head_tree is not None and suffix.startswith("/git/trees/head?") else self.tree)
        if suffix.startswith("/actions/runs/1/attempts/1/jobs?"):
            return {"total_count": len(self.jobs), "jobs": copy.deepcopy(self.jobs)}
        if suffix.startswith("/check-suites/3/check-runs?"):
            return {"total_count": len(self.checks), "check_runs": copy.deepcopy(self.checks)}
        if suffix.startswith("/code-scanning/analyses?"):
            return copy.deepcopy(self.analyses)
        raise AssertionError(url)

    def collect(self):
        with patch.object(MODULE, "_request", side_effect=self.request), patch.object(
            MODULE, "enumerate_check_runs", return_value=copy.deepcopy(self.refresh_checks)
        ):
            return MODULE.proven_check_evidence(self.repo, "head", "token", self.contract, self.check, "Default setup",
                                                trusted_base_revision="base", pull_request_number=35)

    def assert_unverified(self):
        result = self.collect()
        self.assertEqual(result["status"], "not_run", result)
        self.assertTrue(result["reason"])

    def test_live_shape_aliases_empty_pr_association_and_dynamic_name(self):
        self.assertEqual(self.collect()["status"], "passed")
        self.assertIn("https://github.com/owner/repo/actions/runs/1", self.collect()["evidence"][0])

    def test_aggregate_failure_preserved_after_complete_analyses(self):
        self.check["conclusion"] = "failure"
        self.assertEqual(self.collect()["status"], "failed")

    def test_wrong_aggregate_identity_is_rejected(self):
        for field, value in [("app", {"id": 1, "slug": "github-advanced-security"}), ("head_sha", "wrong"),
                             ("status", "in_progress"), ("conclusion", "skipped")]:
            with self.subTest(field=field):
                self.setUp()
                self.check[field] = value
                self.assert_unverified()

    def test_wrong_dynamic_run_identity_is_rejected(self):
        for field, value in [("path", ".github/workflows/codeql.yml"), ("event", "pull_request"), ("head_sha", "wrong"),
                             ("head_branch", "refs/pull/34/head"), ("repository", {"id": 8, "full_name": self.repo}),
                             ("run_attempt", 2), ("conclusion", "failure"), ("status", "in_progress")]:
            with self.subTest(field=field):
                self.setUp()
                self.run[field] = value
                self.assert_unverified()

    def test_pr_base_and_head_are_exact(self):
        for key in ("base", "head"):
            with self.subTest(key=key):
                self.setUp()
                self.pr[key]["sha"] = "wrong"
                self.assert_unverified()

    def test_workflow_identity_must_be_platform_dynamic(self):
        self.workflow["path"] = ".github/workflows/codeql.yml"
        self.assert_unverified()

    def test_missing_duplicate_skipped_and_spoofed_languages(self):
        for mode in ("missing", "duplicate", "skipped", "app", "suite", "id", "head"):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == "missing":
                    self.jobs.pop()
                elif mode == "duplicate":
                    self.jobs.append({**self.jobs[0], "id": 77})
                elif mode == "skipped":
                    self.jobs[0]["conclusion"] = "skipped"
                elif mode == "app":
                    self.checks[0]["app"]["id"] = 3
                elif mode == "suite":
                    self.checks[0]["check_suite"]["id"] = 77
                elif mode == "id":
                    self.checks[0]["id"] = 77
                else:
                    self.checks[0]["head_sha"] = "wrong"
                self.assert_unverified()

    def test_analyses_must_be_unique_exact_head_ref_key_category_and_job_time(self):
        for mode in ("missing", "duplicate", "sha", "ref", "key", "category", "error", "warning", "time"):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == "missing":
                    self.analyses.pop()
                elif mode == "duplicate":
                    self.analyses.append({**self.analyses[0], "id": 999})
                else:
                    field = {"sha": "commit_sha", "ref": "ref", "key": "analysis_key", "category": "category",
                             "error": "error", "warning": "warning", "time": "created_at"}[mode]
                    self.analyses[0][field] = "2026-10-19T18:16:20Z" if mode == "time" else "wrong"
                self.assert_unverified()

    def test_missing_unknown_duplicate_languages_and_config_drift(self):
        for change in ({"languages": []}, {"languages": ["php"]}, {"languages": ["python", "python"]},
                       {"state": "not-configured"}, {"updated_at": "2026-10-19T18:17:00Z"}, {"config_file": "custom.yml"}):
            with self.subTest(change=change):
                self.setUp()
                self.setup.update(change)
                self.assert_unverified()

    def test_changed_or_truncated_codeql_tree_is_unverified(self):
        self.head_tree = {"truncated": False, "tree": [{"path": ".github/codeql/config.yml", "type": "blob", "mode": "100644", "sha": "a" * 40}]}
        self.assert_unverified()
        self.head_tree = {"truncated": True, "tree": []}
        self.assert_unverified()

    def test_org_custom_codeql_properties_are_unsupported(self):
        self.pr["base"]["repo"]["owner"]["type"] = "Organization"
        self.assertEqual(self.collect()["status"], "passed")
        self.properties = [{"property_name": "github-codeql-config-file", "value": "foo.yml"}]
        self.assert_unverified()

    def test_late_aggregate_duplicates_are_unverified(self):
        self.refresh_checks.append({**self.check, "id": 45})
        self.assert_unverified()

    def test_contract_cannot_weaken_default_setup_or_change_control(self):
        self.contract["app_slug"] = "github-advanced-security"
        self.assert_unverified()
        self.contract.pop("app_slug")
        self.contract["control_ids"] = ["build"]
        self.assert_unverified()

    def test_api_failure_is_explicit_unverified(self):
        with patch.object(MODULE, "_request", side_effect=URLError("denied")):
            result = MODULE.codeql_default_evidence(self.repo, "head", "token", self.contract, self.check, "Default", "base", 35)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("could not be verified", result["reason"])

    def test_pagination_rejects_missing_count_duplicate_ids_and_overflow(self):
        for payload in ({"total_count": 2, "jobs": [{"id": 1}]},
                        {"total_count": True, "jobs": []},
                        {"total_count": 2, "jobs": [{"id": 1}, {"id": 1}]}):
            with self.subTest(payload=payload), patch.object(MODULE, "_request", return_value=payload):
                with self.assertRaises(ValueError):
                    MODULE.codeql_pages("https://api.github.com/test", "token", "jobs")
        with patch.object(MODULE, "MAX_CHECK_RUN_PAGES", 1), patch.object(MODULE, "_request", return_value=[{"id": i} for i in range(1, 101)]):
            with self.assertRaisesRegex(ValueError, "page limit"):
                MODULE.codeql_pages("https://api.github.com/test", "token")

    def test_late_run_or_configuration_change_is_unverified(self):
        for target in ("/actions/runs/1", "/code-scanning/default-setup"):
            with self.subTest(target=target):
                calls = 0

                def changing_request(url, token):
                    nonlocal calls
                    value = self.request(url, token)
                    if url == self.api + target:
                        calls += 1
                        if calls > 1:
                            value["updated_at"] = "2026-10-19T18:18:00Z"
                    return value

                with patch.object(MODULE, "_request", side_effect=changing_request), patch.object(
                    MODULE, "enumerate_check_runs", return_value=[self.check]
                ):
                    result = MODULE.codeql_default_evidence(self.repo, "head", "token", self.contract,
                                                           self.check, "Default", "base", 35)
                self.assertEqual(result["status"], "not_run")
                self.assertIn("changed during", result["reason"])

    def test_collect_passes_trusted_pr_binding_to_specialized_provider(self):
        provider = MODULE.CODEQL_DEFAULT_PROVIDER
        config = {"providers": {provider: {"display_name": "GitHub CodeQL default setup"}}}
        with patch.object(MODULE, "expected_checks", return_value={"CodeQL": self.contract}), patch.object(
            MODULE, "expected_reviews", return_value=[]
        ), patch.object(MODULE, "_request", side_effect=self.request), patch.object(
            MODULE, "enumerate_check_runs", return_value=[self.check]
        ):
            result = MODULE.collect_checks(self.repo, "head", "token", {}, {}, {}, config, "change",
                                    trusted_base_revision="base", pull_request_number=35)
        self.assertEqual(result["results"]["deep-sast"][provider]["status"], "passed")

    def test_missing_boolean_or_nonpositive_aggregate_ids_are_rejected(self):
        for target in ("check", "suite"):
            for bad_id in (None, True, False, 0, -1, "44"):
                with self.subTest(target=target, bad_id=bad_id):
                    self.setUp()
                    (self.check if target == "check" else self.check["check_suite"])["id"] = bad_id
                    self.assert_unverified()

    def test_unchanged_symlinks_submodules_and_bad_tree_entries_are_unverified(self):
        for path, kind, mode, sha in [
            (".github", "blob", "120000", "a" * 40),
            (".github", "commit", "160000", "a" * 40),
            (".github/codeql", "blob", "120000", "a" * 40),
            (".github/codeql/config.yml", "blob", "120000", "a" * 40),
            (".github/codeql/extensions", "commit", "160000", "a" * 40),
            (".github/codeql/config.yml", "blob", "100644", "short"),
            (".github/codeql/config.yml", "blob", "100600", "a" * 40),
        ]:
            with self.subTest(path=path, mode=mode, sha=sha):
                self.setUp()
                self.tree["tree"] = [{"path": path, "type": kind, "mode": mode, "sha": sha}]
                self.assert_unverified()
        self.setUp()
        entry = {"path": ".github/codeql/config.yml", "type": "blob", "mode": "100644", "sha": "a" * 40}
        self.tree["tree"] = [entry, entry]
        self.assert_unverified()

    def test_unchanged_regular_codeql_tree_and_executable_files_are_supported(self):
        self.tree["tree"] = [
            {"path": ".github", "type": "tree", "mode": "040000", "sha": "a" * 40},
            {"path": ".github/codeql", "type": "tree", "mode": "040000", "sha": "b" * 40},
            {"path": ".github/codeql/config.yml", "type": "blob", "mode": "100644", "sha": "c" * 40},
            {"path": ".github/codeql/helper", "type": "blob", "mode": "100755", "sha": "d" * 40},
        ]
        self.assertEqual(self.collect()["status"], "passed")

    def test_late_new_run_or_repository_property_is_unverified(self):
        for target in ("runs", "properties"):
            with self.subTest(target=target):
                self.setUp()
                self.pr["base"]["repo"]["owner"]["type"] = "Organization"
                calls = 0

                def changing_request(url, token):
                    nonlocal calls
                    value = self.request(url, token)
                    if ((target == "runs" and "/actions/runs?" in url)
                            or (target == "properties" and url.endswith("/properties/values"))):
                        calls += 1
                        if calls > 1:
                            if target == "runs":
                                value["workflow_runs"].append({**self.run, "id": 99})
                                value["total_count"] = 2
                            else:
                                value.append({"property_name": "github-codeql-config-file", "value": "custom.yml"})
                    return value

                with patch.object(MODULE, "_request", side_effect=changing_request), patch.object(
                    MODULE, "enumerate_check_runs", return_value=[self.check]
                ):
                    result = MODULE.codeql_default_evidence(self.repo, "head", "token", self.contract,
                                                           self.check, "Default", "base", 35)
                self.assertEqual(result["status"], "not_run")
                self.assertIn("changed during", result["reason"])

    def test_same_name_actions_advanced_check_not_selected(self):
        self.assertTrue(MODULE.check_matches_declared_app(self.check, self.contract))
        self.check["app"] = {"id": 15368, "slug": "github-actions"}
        self.assertFalse(MODULE.check_matches_declared_app(self.check, self.contract))


if __name__ == "__main__":
    unittest.main()
