"""Tests for the credentialed provider check publisher and the workflows that use it."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "provider_check.py"
HEAD = "a" * 40
BASE = "b" * 40
ENVIRONMENT = {
    "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_EVENT_NAME": "pull_request_target",
    "GITHUB_REPOSITORY": "owner/repo", "BASE_SHA": BASE, "BASE_REF": "refs/heads/main", "HEAD_SHA": HEAD,
}
COUNTS = {"version": 1, "source": "pull-request-workflow",
          "findings": {"total": 1, "critical": 0, "high": 1, "medium": 0, "low": 0, "unrated": 0}}


def load():
    spec = importlib.util.spec_from_file_location("provider_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fragment(status: str, *, revision: str = HEAD, provider: str = "snyk-code", **result: object) -> dict:
    body = {"producer": "Snyk Code", "status": status, **result}
    return {"version": 2, "subject": {"type": "git-commit", "revision": revision},
            "results": {"deep-sast": {provider: body}}}


class EvidenceDocumentTests(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name: str, document: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def evidence(self, **kwargs):
        return self.module.evidence_document("snyk-code", "Snyk Code", dict(ENVIRONMENT), **kwargs)

    def test_adapter_fragment_becomes_run_bound_evidence(self):
        document = self.evidence(fragment=self.write("f.json", fragment("failed", evidence=["snyk code test: 1 findings"])),
                                 control="deep-sast", measurements=self.write("m.json", COUNTS))
        self.assertEqual(document, {
            "version": 1, "run_id": 77, "run_attempt": 2, "event": "pull_request_target", "repository": "owner/repo",
            "base_sha": BASE, "base_ref": "refs/heads/main", "head_sha": HEAD, "revision": HEAD,
            "provider_id": "snyk-code", "check_name": "Snyk Code", "status": "failed",
            "summary": "snyk code test: 1 findings", "withheld": False, "control": "deep-sast", "measurements": COUNTS,
        })
        blocked = self.evidence(fragment=self.write("b.json", fragment("blocked", reason="credential-missing: SNYK_TOKEN is not set.")))
        self.assertEqual((blocked["status"], blocked["summary"]), ("blocked", "credential-missing: SNYK_TOKEN is not set."))

    def test_missing_foreign_or_malformed_results_never_pass(self):
        cases = (
            ("missing", self.root / "absent.json", "blocked", "execution-error"),
            ("not json", self.root / "x.txt", "blocked", "execution-error"),
            ("other revision", self.write("r.json", fragment("passed", revision="c" * 40, evidence=["ok"])), "not_run",
             "revision-mismatch"),
            ("other provider", self.write("p.json", fragment("passed", provider="fossa", evidence=["ok"])), "blocked",
             "execution-error"),
            ("no status", self.write("s.json", fragment("weird")), "blocked", "execution-error"),
            ("no reason", self.write("n.json", fragment("not_run")), "blocked", "execution-error"),
        )
        (self.root / "x.txt").write_text("{not json", encoding="utf-8")
        for label, path, status, code in cases:
            with self.subTest(label=label):
                document = self.evidence(fragment=path)
                self.assertEqual(document["status"], status)
                self.assertTrue(document["summary"].startswith(code), document["summary"])
        symlink = self.root / "link.json"
        symlink.symlink_to(self.write("real.json", fragment("passed", evidence=["ok"])))
        self.assertEqual(self.evidence(fragment=symlink)["status"], "blocked")

    def test_job_status_withheld_forks_and_counts_that_do_not_apply(self):
        document = self.evidence(status="passed", summary="0 findings; 0 unresolved P0/P1")
        self.assertEqual((document["status"], document["summary"]), ("passed", "0 findings; 0 unresolved P0/P1"))
        self.assertEqual(self.evidence(status="bogus", summary="x")["status"], "blocked")
        self.assertEqual(self.evidence(status="passed", summary=" ")["status"], "blocked")
        withheld = self.evidence(withheld="fork pull requests are not sent to Snyk.")
        self.assertEqual((withheld["status"], withheld["withheld"]), ("not_run", True))
        self.assertTrue(withheld["summary"].startswith("credential-withheld: "))
        counts = self.write("m.json", COUNTS)
        self.assertNotIn("measurements", self.evidence(status="blocked", summary="x", control="deep-sast", measurements=counts))
        self.assertNotIn("measurements", self.evidence(status="failed", summary="x", control="unit-tests", measurements=counts))
        self.assertNotIn("measurements", self.evidence(status="failed", summary="x", control="deep-sast",
                                                        measurements=self.root / "absent.json"))
        self.assertEqual(len(self.evidence(status="failed", summary="s" * 5000)["summary"]), 1000)

    def test_only_an_exact_pull_request_target_context_is_accepted(self):
        for key, value in (("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_RUN_ID", "x"), ("HEAD_SHA", "abc"),
                           ("BASE_SHA", ""), ("BASE_REF", "main"), ("GITHUB_REPOSITORY", "owner")):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.module.evidence_document("snyk-code", "Snyk Code", {**ENVIRONMENT, key: value}, status="passed",
                                                  summary="ok")
        with self.assertRaises(ValueError):
            self.module.evidence_document("Snyk Code", "Snyk Code", dict(ENVIRONMENT), status="passed", summary="ok")

    def test_check_payload_binds_the_run_and_head_and_never_passes_a_withheld_scan(self):
        document = self.evidence(status="failed", summary="1 findings")
        payload = self.module.check_payload(document, "https://github.com")
        self.assertEqual(payload["name"], "Snyk Code")
        self.assertEqual(payload["head_sha"], HEAD)
        self.assertEqual(payload["conclusion"], "failure")
        self.assertEqual(payload["external_id"], f"proof:snyk-code:77:{HEAD}")
        self.assertEqual(payload["details_url"], "https://github.com/owner/repo/actions/runs/77")
        self.assertIn("1 findings", payload["output"]["summary"])
        conclusions = {status: self.module.check_payload(self.evidence(status=status, summary="x"), "")["conclusion"]
                       for status in ("passed", "failed", "blocked", "not_run")}
        self.assertEqual(conclusions, {"passed": "success", "failed": "failure", "blocked": "failure", "not_run": "failure"})
        withheld = self.module.check_payload(self.evidence(withheld="fork"), "")
        self.assertEqual(withheld["conclusion"], "action_required")

    def test_prefixes_match_the_provider_contract(self):
        providers = json.loads((ROOT / "policies" / "provider-config.yaml").read_text(encoding="utf-8"))["providers"]
        for provider_id in ("snyk-code", "snyk-open-source", "fossa", "ai-engineering-adapter", "ai-qa-adapter",
                            "ai-security-adapter", "ai-repository-standards-adapter"):
            for check in providers[provider_id]["checks"].values():
                with self.subTest(provider_id=provider_id):
                    self.assertEqual(check["external_id_prefix"], self.module.external_id_prefix(provider_id))
                    self.assertEqual(check["artifact_name_prefix"], self.module.artifact_name_prefix(provider_id))
                    self.assertEqual(check["artifact_member"], "proof-evidence.json")

    def test_cli_writes_evidence_and_payload(self):
        output, payload = self.root / "out" / "proof-evidence.json", self.root / "check-run.json"
        with patch.dict(os.environ, ENVIRONMENT):
            self.assertEqual(self.module.main(["evidence", "--provider-id", "snyk-code", "--check-name", "Snyk Code",
                                               "--fragment", str(self.write("f.json", fragment("passed", evidence=["ok"]))),
                                               "--output", str(output)]), 0)
            self.assertEqual(self.module.main(["check", "--evidence", str(output), "--output", str(payload)]), 0)
        self.assertEqual(json.loads(payload.read_text(encoding="utf-8"))["conclusion"], "success")
        with patch.dict(os.environ, {**ENVIRONMENT, "GITHUB_EVENT_NAME": "push"}), \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(self.module.main(["evidence", "--provider-id", "snyk-code", "--check-name", "Snyk Code",
                                               "--status", "passed", "--summary", "ok", "--output", str(output)]), 2)
        self.assertIn("pull_request_target", stderr.getvalue())


WORKFLOWS = ("snyk.yml", "fossa.yml", "ai-pr-review.yml")


def jobs(text: str) -> dict[str, str]:
    body = text.split("\njobs:\n", 1)[1]
    return {match.group(1): match.group(0) for match in re.finditer(r"(?ms)^  ([a-z-]+):\n.*?(?=^  [a-z-]+:\n|\Z)", body)}


class CredentialedWorkflowTests(unittest.TestCase):
    """No provider credential shares a job or a runner with pull-request code."""

    def test_installed_copies_match_the_templates(self):
        for name in WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertEqual((ROOT / ".github" / "workflows" / name).read_bytes(),
                                 (ROOT / "workflows" / name).read_bytes())

    def test_workflows_run_only_from_the_default_branch(self):
        for name in WORKFLOWS:
            text = (ROOT / "workflows" / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                trigger = text.split("\non:\n", 1)[1].split("\n\n", 1)[0]
                self.assertEqual(trigger.strip(), "pull_request_target:\n    types: [opened, synchronize, reopened]")
                self.assertIn("\npermissions: {}\n", text)
                self.assertNotIn("workflow_call", text)

    def test_credentialed_jobs_read_the_head_as_data_from_the_protected_environment(self):
        providers = json.loads((ROOT / "policies" / "provider-config.yaml").read_text(encoding="utf-8"))["providers"]
        check_names = {check["check_name"] for provider in providers.values() for check in provider["checks"].values()}
        credentialed = 0
        for name in WORKFLOWS:
            for job_id, job in jobs((ROOT / "workflows" / name).read_text(encoding="utf-8")).items():
                with self.subTest(workflow=name, job=job_id):
                    job_name = re.search(r"^    name: (.+)$", job, re.MULTILINE).group(1)
                    self.assertNotIn(job_name, check_names)
                    if "secrets." not in job:
                        self.assertNotIn("candidate", job)
                        continue
                    credentialed += 1
                    self.assertIn("    environment:\n      name: proof-providers\n      deployment: false\n", job)
                    self.assertIn("      contents: read\n      checks: write\n", job)
                    self.assertEqual(len(re.findall(r"secrets\.", job)), 1)
                    self.assertIn("ref: ${{ github.sha }}\n          path: trusted\n", job)
                    self.assertIn("ref: ${{ github.event.pull_request.head.sha }}\n          path: candidate\n", job)
                    candidate = job.split("path: candidate\n", 1)[1].split("\n      - name:", 1)[0]
                    self.assertIn("persist-credentials: false", candidate)
                    for forbidden in ("PROOF_SETUP_COMMAND", "working-directory: candidate", "bash candidate",
                                      "./candidate", "uses: ./"):
                        self.assertNotIn(forbidden, job)
                    if "adapter.py" in job:
                        self.assertIn("--data-only", job)
                        self.assertIn('--target "candidate/${PROOF_WORKING_DIRECTORY}"', job)
                    provider_id = re.search(r"PROVIDER_ID: (\S+)", job).group(1)
                    check_name = re.search(r"CHECK_NAME: (.+)", job).group(1)
                    contract = next(iter(providers[provider_id]["checks"].values()))
                    self.assertEqual(contract["check_name"], check_name)
                    self.assertIn(f"name: {contract['artifact_name_prefix']}${{{{ github.run_id }}}}", job)
                    self.assertIn('gh api --method POST "repos/${GITHUB_REPOSITORY}/check-runs"', job)
                    self.assertIn("PROOF_PROVIDERS_SCAN_FORKS", job)
                    self.assertLess(job.index("- name: Upload run-bound evidence"), job.index("check-runs"))
        self.assertEqual(credentialed, 7)


if __name__ == "__main__":
    unittest.main()
