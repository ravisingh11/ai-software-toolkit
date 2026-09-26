from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))

from ai_toolkit import report  # noqa: E402


def control(identifier: str, status: str, mode: str = "advisory", reason: str | None = None) -> dict:
    result = {"producer": "p", "status": status}
    if reason:
        result["reason"] = reason
    return {
        "id": identifier,
        "name": identifier,
        "effective_mode": mode,
        "authoritative_provider": {"id": "prov", "display_name": "Provider"},
        "authoritative_evidence_status": status,
        "authoritative_result": None if status == "missing" else result,
        "readiness": "GREEN" if status == "passed" else "ORANGE",
        "supplemental": [],
    }


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve()

    def git(self, *arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=self.target, text=True, capture_output=True, check=True).stdout.strip()

    def commit(self) -> str:
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.target / "README.md").write_text("# x\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        return self.git("rev-parse", "HEAD")

    def write_evidence(self, revision: str, results: dict) -> None:
        path = self.target / ".artifacts" / "guardrails" / "evidence.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 2, "subject": {"type": "git-commit", "revision": revision}, "results": results}), encoding="utf-8")

    def test_grouping_and_next_actions(self):
        card = {
            "status": "ORANGE", "decision": "allow", "policy": "baseline", "operation": "change",
            "subject": {"type": "git-commit", "revision": "abc"},
            "controls": [
                control("unit-tests", "passed"),
                control("deep-sast", "failed"),
                control("mystery", "failed"),
                control("secret-detection", "blocked", reason="timed out"),
                control("build", "no_result", reason="GUARDRAILS_BUILD_COMMAND is not configured; this capability has NO RESULT."),
                control("format-and-lint", "not_run", reason="Local evidence requires a clean worktree before providers run."),
                control("deep-sast-2", "no_result", reason="provider produced nothing."),
                control("license-compliance", "missing"),
                {**control("runtime-soak", "missing"), "effective_mode": "not_activated"},
            ],
            "findings": [{"kind": "subject_mismatch", "message": "evidence subject mismatch"}],
        }
        groups = report.group_controls(card)
        self.assertEqual([row["id"] for row in groups["passed"]], ["unit-tests"])
        self.assertEqual([row["id"] for row in groups["failed"]], ["deep-sast", "mystery"])
        self.assertEqual(len(groups["unverified"]), 5)
        self.assertEqual([row["id"] for row in groups["not_activated"]], ["runtime-soak"])
        self.assertIn("fix-security-finding", report.next_action(card["controls"][1]))
        self.assertIn("Investigate the Provider result", report.next_action(card["controls"][2]))
        self.assertIn("could not complete: timed out", report.next_action(card["controls"][3]))
        self.assertIn("Configure the command", report.next_action(card["controls"][4]))
        self.assertIn("Commit or stash", report.next_action(card["controls"][5]))
        self.assertIn("produced no result: provider produced nothing.", report.next_action(card["controls"][6]))
        self.assertIn("No evidence from Provider", report.next_action(card["controls"][7]))
        self.assertEqual(report.next_action({"id": "x", "authoritative_evidence_status": "weird"}), "No action.")
        rendered = report.render_check(card, evidence_path="e.json", report_path="r.md")
        self.assertIn("What ran and passed (1)", rendered)
        self.assertIn("What failed (2)", rendered)
        self.assertIn("What remains unverified (5)", rendered)
        self.assertIn("Not activated (1): runtime-soak", rendered)
        self.assertIn("Subject mismatch", rendered)
        self.assertIn("Evidence: e.json", rendered)
        empty = report.render_check({"controls": [], "findings": []})
        self.assertEqual(empty.count("(none)"), 3)

    def test_verified_rows_require_bound_evidence(self):
        revision = self.commit()
        doctor_report = {"checks": [
            {"id": "runtime", "status": "configured", "message": "", "next_step": ""},
            {"id": "local.command.build", "status": "action_needed", "message": "", "next_step": "Export GUARDRAILS_BUILD_COMMAND"},
            {"id": "workflow.build", "status": "configured", "message": "", "next_step": ""},
            {"id": "producer.deep-sast", "status": "unverified", "message": "", "next_step": ""},
            {"id": "workflow.deep-sast", "status": "configured", "message": "", "next_step": ""},
            {"id": "local.command.unit-tests", "status": "configured", "message": "", "next_step": ""},
            {"id": "local.tool.gitleaks", "status": "unverified", "message": "", "next_step": ""},
        ]}
        self.assertIsNone(report.latest_evidence(self.target))
        rows = {row["capability"]: row for row in report.verified_rows(self.target, doctor_report)}
        self.assertEqual(set(rows), {"build", "deep-sast", "unit-tests"})
        self.assertEqual(rows["build"]["state"], "installed")
        self.assertIn("GUARDRAILS_BUILD_COMMAND", rows["build"]["next_step"])
        self.assertEqual(rows["deep-sast"]["state"], "configured")
        self.write_evidence("0" * 40, {"unit-tests": {"prov": {"status": "passed"}}})
        rows = {row["capability"]: row for row in report.verified_rows(self.target, doctor_report)}
        self.assertEqual(rows["unit-tests"]["state"], "configured")
        self.write_evidence(revision, {"unit-tests": {"prov": {"status": "failed"}}, "deep-sast": {"prov": {"status": "not_run"}}})
        rows = {row["capability"]: row for row in report.verified_rows(self.target, doctor_report)}
        self.assertEqual(rows["unit-tests"]["state"], "verified")
        self.assertEqual(rows["unit-tests"]["observed"], "failed")
        self.assertEqual(rows["deep-sast"]["state"], "configured")
        rendered = report.render_doctor(self.target, doctor_report, list(rows.values()), {"guardrails": {"state": "installed", "message": "ok", "next_step": "none"}})
        self.assertIn("bound to HEAD", rendered)
        self.assertIn("verified: 1", rendered)
        self.assertIn("Next: none", rendered)
        missing_runtime = {"checks": [{"id": "local.command.build", "status": "action_needed", "message": "", "next_step": ""}]}
        rows = report.verified_rows(self.target, missing_runtime)
        self.assertEqual(rows[0]["state"], "missing")

    def test_render_doctor_reports_unbound_or_absent_evidence(self):
        rendered = report.render_doctor(self.target, {"checks": []}, [], {})
        self.assertIn("no local evidence found", rendered)
        self.commit()
        self.write_evidence("f" * 40, {})
        rendered = report.render_doctor(self.target, {"checks": []}, [], {})
        self.assertIn("not HEAD", rendered)
        (self.target / ".artifacts" / "guardrails" / "evidence.json").write_text("nope", encoding="utf-8")
        self.assertIsNone(report.latest_evidence(self.target))


if __name__ == "__main__":
    unittest.main()


class ReasonCodeTests(unittest.TestCase):
    def test_reason_codes_drive_next_actions(self):
        for code in report.REASON_ACTIONS:
            row = control("deep-sast", "blocked", reason=f"{code}: detail text")
            action = report.next_action(row)
            self.assertTrue(action.startswith(f"[{code}]"), action)
            self.assertIn("detail text", action)
        self.assertIsNone(report.reason_code("no code here"))
        self.assertIsNone(report.reason_code(None))
        self.assertEqual(report.reason_code("timed-out: x"), "timed-out")

    def test_adapter_codes_match_report_codes(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("provider_adapter", ROOT / "tooling" / "provider_adapter.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        self.assertEqual(set(adapter.REASON_CODES), set(report.REASON_ACTIONS))
