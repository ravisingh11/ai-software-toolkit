"""Contract tests for the external provider adapter.

Each adapter is exercised against fake ``snyk`` and ``fossa`` executables that
reproduce the real CLIs' exit codes and output shapes for every outcome the
plan requires: success, findings, authentication failure, timeout, unsupported
project, partial scan, and stale or mismatched revision.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "provider_adapter.py"

FAKE_SNYK = r'''#!/usr/bin/env bash
mode="${FAKE_SNYK_MODE:-clean}"
case "$mode" in
  clean) echo '{"ok": true}'; exit 0 ;;
  findings-code) echo '{"runs": [{"results": [{"ruleId": "a"}, {"ruleId": "b"}]}]}'; exit 1 ;;
  findings-oss) echo '{"vulnerabilities": [{"id": "SNYK-1"}, {"id": "SNYK-2"}, {"id": "SNYK-3"}]}'; exit 1 ;;
  findings-plain) echo 'issues found'; exit 1 ;;
  auth) echo 'Authentication failed. Please check the API token on https://snyk.io' >&2; exit 2 ;;
  error) echo 'Something went wrong' >&2; exit 2 ;;
  unsupported) echo 'Could not detect supported target files' >&2; exit 3 ;;
  hang) sleep 5; exit 0 ;;
  *) exit 2 ;;
esac
'''

FAKE_FOSSA = r'''#!/usr/bin/env bash
sub="$1"
mode="${FAKE_FOSSA_MODE:-clean}"
if [[ "$sub" == "analyze" ]]; then
  case "$mode" in
    analyze-auth) printf '\033[91mError: \033[0mA FOSSA API key is required to run this command\n' >&2; exit 1 ;;
    analyze-error) echo 'analysis failed: unexpected error' >&2; exit 1 ;;
    analyze-notargets) echo 'No analysis targets found in directory' >&2; exit 1 ;;
    analyze-hang) sleep 5; exit 0 ;;
    *) echo "Uploaded revision $3"; echo "$@" > "${FAKE_FOSSA_LOG:-/dev/null}"; exit 0 ;;
  esac
fi
case "$mode" in
  clean) echo '{"issues": [], "count": 0}'; exit 0 ;;
  issues) echo '{"issues": [{"id": 1, "type": "policy_flag"}], "count": 1}'; exit 1 ;;
  issues-text) echo 'Test failed. Number of issues found: 2'; exit 1 ;;
  test-auth) echo 'Status: 403'; echo 'Ensure that you are using a valid FOSSA_API_KEY.'; exit 1 ;;
  test-timeout) echo 'Timed out waiting for the build to finish'; exit 1 ;;
  test-error) echo 'internal server error'; exit 1 ;;
  test-hang) sleep 5; exit 0 ;;
  *) exit 1 ;;
esac
'''


def load():
    spec = importlib.util.spec_from_file_location("provider_adapter", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdapterFixture(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "repo"
        self.target.mkdir()
        (self.target / "README.md").write_text("# x\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.head = self.git("rev-parse", "HEAD")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, body in (("snyk", FAKE_SNYK), ("fossa", FAKE_FOSSA)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def git(self, *arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=self.target, text=True, capture_output=True, check=True).stdout.strip()

    def environment(self, **extra: str) -> dict[str, str]:
        environment = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": str(self.root),
                       "SNYK_TOKEN": "t", "FOSSA_API_KEY": "k"}
        environment.update(extra)
        return environment

    def run_provider(self, provider: str, *, revision: str | None = None, timeout: int = 60, **extra: str):
        return self.module.run_provider(provider, self.target, revision=revision, arguments=[], timeout=timeout, environment=self.environment(**extra))


class SnykContractTests(AdapterFixture):
    def test_success_findings_and_counts(self):
        _, outcome = self.run_provider("snyk-code", FAKE_SNYK_MODE="clean")
        self.assertEqual(outcome.status, "passed")
        _, outcome = self.run_provider("snyk-code", FAKE_SNYK_MODE="findings-code")
        self.assertEqual((outcome.status, outcome.message), ("failed", "snyk code test: 2 findings"))
        _, outcome = self.run_provider("snyk-open-source", FAKE_SNYK_MODE="findings-oss")
        self.assertEqual((outcome.status, outcome.message), ("failed", "snyk test: 3 findings"))
        _, outcome = self.run_provider("snyk-open-source", FAKE_SNYK_MODE="findings-plain")
        self.assertEqual(outcome.message, "snyk test: findings reported")

    def test_authentication_error_unsupported_and_timeout(self):
        _, outcome = self.run_provider("snyk-code", FAKE_SNYK_MODE="auth")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "authentication-failed"))
        _, outcome = self.run_provider("snyk-code", FAKE_SNYK_MODE="error")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "execution-error"))
        _, outcome = self.run_provider("snyk-open-source", FAKE_SNYK_MODE="unsupported")
        self.assertEqual((outcome.status, outcome.code), ("not_run", "unsupported-project"))
        _, outcome = self.run_provider("snyk-open-source", timeout=1, FAKE_SNYK_MODE="hang")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "timed-out"))

    def test_preconditions(self):
        revision, outcome = self.run_provider("snyk-code", SNYK_TOKEN="")
        self.assertEqual((revision, outcome.status, outcome.code), (self.head, "blocked", "credential-missing"))
        _, outcome = self.run_provider("snyk-code", PATH=str(self.root / "nowhere"))
        self.assertEqual((outcome.status, outcome.code), ("not_run", "configuration-missing"))
        revision, outcome = self.run_provider("snyk-code", revision="0" * 40)
        self.assertEqual((revision, outcome.status, outcome.code), ("0" * 40, "not_run", "revision-mismatch"))
        revision, outcome = self.run_provider("snyk-code", revision=self.head, FAKE_SNYK_MODE="clean")
        self.assertEqual((revision, outcome.status), (self.head, "passed"))
        bare = self.root / "bare"
        bare.mkdir()
        revision, outcome = self.module.run_provider("snyk-code", bare, revision=None, arguments=[], timeout=5, environment=self.environment())
        self.assertEqual((revision, outcome.code), ("unknown", "revision-mismatch"))
        with self.assertRaises(ValueError):
            self.module.run_provider("nope", self.target, revision=None, arguments=[], timeout=5)


class FossaContractTests(AdapterFixture):
    def test_analyze_then_test_success_and_issues(self):
        log = self.root / "fossa.log"
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="clean", FAKE_FOSSA_LOG=str(log))
        self.assertEqual(outcome.status, "passed")
        self.assertIn(self.head, log.read_text(encoding="utf-8"))
        self.assertEqual(outcome.evidence, ["fossa analyze: uploaded", "fossa test: exit 0, no issues"])
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="issues")
        self.assertEqual((outcome.status, outcome.message), ("failed", "fossa test: 1 issues"))
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="issues-text")
        self.assertEqual((outcome.status, outcome.message), ("failed", "fossa test: issues reported"))

    def test_partial_scan_and_failures(self):
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="analyze-auth")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "authentication-failed"))
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="analyze-error")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "execution-error"))
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="analyze-notargets")
        self.assertEqual((outcome.status, outcome.code), ("not_run", "unsupported-project"))
        _, outcome = self.run_provider("fossa", timeout=1, FAKE_FOSSA_MODE="analyze-hang")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "timed-out"))
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="test-auth")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "authentication-failed"))
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="test-timeout")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "analysis-incomplete"))
        _, outcome = self.run_provider("fossa", FAKE_FOSSA_MODE="test-error")
        self.assertEqual((outcome.status, outcome.code), ("blocked", "execution-error"))
        outcome = self.module.fossa_outcome((0, "uploaded"), None)
        self.assertEqual((outcome.status, outcome.code), ("blocked", "analysis-incomplete"))
        outcome = self.module.fossa_outcome((0, "uploaded"), (None, ""))
        self.assertEqual((outcome.status, outcome.code), ("blocked", "analysis-incomplete"))


class FragmentAndCliTests(AdapterFixture):
    def test_fragment_shape_and_reason_codes(self):
        module = self.module
        outcome = module.Outcome("blocked", "no key", code="credential-missing")
        document = module.fragment("fossa", self.head, outcome)
        self.assertEqual(document["subject"], {"type": "git-commit", "revision": self.head})
        self.assertEqual(sorted(document["results"]), ["dependency-vulnerability", "license-compliance"])
        result = document["results"]["license-compliance"]["fossa"]
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(module.reason_code(result["reason"]), "credential-missing")
        self.assertIsNone(module.reason_code("plain text"))
        self.assertIsNone(module.reason_code(None))
        passed = module.fragment("snyk-code", self.head, module.Outcome("passed", "ok", evidence=["snyk code test: exit 0"]))
        self.assertEqual(passed["results"]["deep-sast"]["snyk-code"]["evidence"], ["snyk code test: exit 0"])
        with self.assertRaises(ValueError):
            module.Outcome("weird", "x")
        with self.assertRaises(ValueError):
            module.Outcome("blocked", "x", code="made-up")
        self.assertEqual(module.bounded("a" * 2000)[-3:], "...")
        self.assertIsNone(module.json_document("no json here"))
        self.assertEqual(module.json_document("noise {\"a\": 1}"), {"a": 1})
        self.assertEqual(module.json_document("[1, 2]"), [1, 2])
        self.assertIn("[credential-missing]", module.summary_line("fossa", outcome))
        self.assertNotIn("[", module.summary_line("snyk-code", module.Outcome("passed", "ok")))

    def test_cli_writes_fragment_and_exit_codes(self):
        evidence_dir = self.target / ".artifacts" / "guardrails" / "evidence"
        with patch.dict(os.environ, self.environment(FAKE_SNYK_MODE="clean", SNYK_CODE_ARGS="--severity-threshold=high")):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = self.module.main(["snyk-code", "--target", str(self.target)])
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertIn("Snyk Code: PASSED", stdout.getvalue())
        fragment = json.loads((evidence_dir / "snyk-code.json").read_text(encoding="utf-8"))
        self.assertEqual(fragment["results"]["deep-sast"]["snyk-code"]["status"], "passed")
        with patch.dict(os.environ, self.environment(FAKE_FOSSA_MODE="issues")):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = self.module.main(["fossa", "--target", str(self.target), "--json", "--evidence-dir", str(self.root / "ev")])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual((payload["status"], payload["reason_code"]), ("failed", None))
        self.assertTrue((self.root / "ev" / "fossa.json").is_file())
        with patch.dict(os.environ, self.environment(SNYK_TOKEN="")):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = self.module.main(["snyk-open-source", "--target", str(self.target)])
        self.assertEqual(code, 1)
        self.assertIn("[credential-missing]", stdout.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(self.module.main(["fossa", "--target", str(self.root / "missing")]), 2)
        self.assertIn("not a directory", stderr.getvalue())
        with patch.dict(os.environ, self.environment(FOSSA_ARGS="'unterminated")):
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(self.module.main(["fossa", "--target", str(self.target)]), 2)
        self.assertIn("invalid FOSSA_ARGS", stderr.getvalue())
        os.symlink(self.root / "elsewhere.json", evidence_dir / "fossa.json")
        with patch.dict(os.environ, self.environment(FAKE_FOSSA_MODE="clean")):
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(self.module.main(["fossa", "--target", str(self.target)]), 2)
        self.assertIn("symlink", stderr.getvalue())

    def test_fragment_merges_into_local_scan(self):
        """The scanner accepts adapter fragments for the exact subject and rejects stale ones."""
        scanner_spec = importlib.util.spec_from_file_location("scan_repository", ROOT / "tooling" / "scan_repository.py")
        scanner = importlib.util.module_from_spec(scanner_spec)
        scanner_spec.loader.exec_module(scanner)
        evidence_dir = self.root / "fragments"
        current = self.module.fragment("snyk-open-source", self.head, self.module.Outcome("blocked", "x", code="timed-out"))
        stale = self.module.fragment("fossa", "0" * 40, self.module.Outcome("passed", "ok"))
        self.module.write_fragment(current, evidence_dir, "snyk-open-source")
        self.module.write_fragment(stale, evidence_dir, "fossa")
        evidence = {"version": 2, "subject": {"type": "git-commit", "revision": self.head}, "results": {}}
        rejected = scanner.merge_external_evidence(evidence, evidence_dir)
        self.assertEqual(rejected, ["fossa.json"])
        self.assertEqual(evidence["results"]["dependency-vulnerability"]["snyk-open-source"]["status"], "blocked")

    def test_script_runs_as_a_process(self):
        completed = subprocess.run([sys.executable, str(SCRIPT), "snyk-code", "--target", str(self.target)],
                                   text=True, capture_output=True, env=self.environment(FAKE_SNYK_MODE="unsupported"))
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("[unsupported-project]", completed.stdout)


if __name__ == "__main__":
    unittest.main()
