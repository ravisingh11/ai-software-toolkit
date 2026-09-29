from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "proof_measurements.py"
SPEC = importlib.util.spec_from_file_location("proof_measurements", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise AssertionError(f"cannot load module spec: {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
HEAD = "a" * 40
REPORTS = ROOT / "tooling/tests/fixtures/scanner-reports"


class MeasurementsHelperTests(unittest.TestCase):
    def write(self, directory: Path, name: str, text: str) -> Path:
        path = directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_unittest_logs_are_summed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ok = self.write(root, "a.log", "....s\n------\nRan 5 tests in 0.1s\n\nOK (skipped=1)\n")
            failed = self.write(root, "b.log", "F.E\nRan 3 tests in 0.2s\n\nFAILED (failures=1, errors=1)\n")
            plain = self.write(root, "c.log", "..\nRan 2 tests in 0.0s\n\nOK\n")
            self.assertEqual(MODULE.from_unittest_logs([ok, failed, plain])["tests"],
                             {"total": 10, "passed": 7, "failed": 2, "skipped": 1})
            expected = self.write(root, "d.log", "x.\nRan 2 tests in 0.0s\n\nOK (expected failures=1)\n")
            self.assertEqual(MODULE.from_unittest_logs([expected])["tests"],
                             {"total": 2, "passed": 1, "failed": 0, "skipped": 1})

    def test_unittest_logs_reject_missing_or_ambiguous_summaries(self) -> None:
        for text in ("no summary\n", "Ran 2 tests in 0s\n\nOK\nRan 1 test in 0s\n\nOK\n",
                     "Ran 2 tests in 0s\n\nOK (failures=1)\n", "Ran 2 tests in 0s\n\nFAILED (surprises=1)\n",
                     "Ran 1 test in 0s\n\nOK (skipped=2)\n"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    MODULE.from_unittest_logs([self.write(Path(directory), "x.log", text)])

    def test_junit_counts_failures_errors_and_skips(self) -> None:
        xml = ('<testsuites><testsuite><testcase name="a"/><testcase name="b"><failure/></testcase>'
               '<testcase name="c"><error/></testcase><testcase name="d"><skipped/></testcase></testsuite></testsuites>')
        with tempfile.TemporaryDirectory() as directory:
            report = self.write(Path(directory), "junit.xml", xml)
            self.assertEqual(MODULE.from_junit([report])["tests"],
                             {"total": 4, "passed": 1, "failed": 2, "skipped": 1})

    def test_diff_cover_report_is_converted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.write(root, "cover.json", json.dumps({"total_num_lines": 50, "total_num_violations": 4}))
            self.assertEqual(MODULE.from_diff_cover(report, 80)["coverage"],
                             {"measured_lines": 50, "covered_lines": 46, "threshold_percent": 80})
            for document in ({}, {"total_num_lines": 3, "total_num_violations": 4}, {"total_num_lines": "3", "total_num_violations": 0}):
                with self.subTest(document=document), self.assertRaises(ValueError):
                    MODULE.from_diff_cover(self.write(root, "bad.json", json.dumps(document)), 80)

    def test_review_result_is_counted_by_severity_without_publishing_text(self) -> None:
        findings = [
            {"id": "ENG-001", "severity": "P0", "status": "resolved", "summary": "secret text", "evidence": "src/private.py:1"},
            {"id": "ENG-002", "severity": "P1", "summary": "missing status is open"},
            {"id": "ENG-003", "severity": "P1", "status": None},
            {"id": "ENG-004", "severity": "P1", "status": "accepted"},
            {"id": "ENG-005", "severity": "P2", "status": "open", "blocking": True},
            {"id": "ENG-006", "severity": "P3", "status": "deferred"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.write(root, "engineering.json", json.dumps({"reviewer": "engineering", "findings": findings}))
            document = MODULE.from_review_result(result)
            # Unresolved blocking mirrors the pr-review blocking rule: P0/P1 whose status is not resolved.
            self.assertEqual(document, {"version": 1, "source": "pull-request-workflow", "review_findings": {
                "total": 6, "p0": 1, "p1": 3, "p2": 1, "p3": 1, "unresolved_blocking": 3}})
            self.assertNotIn("private", json.dumps(document))
            empty = self.write(root, "empty.json", json.dumps({"findings": []}))
            self.assertEqual(MODULE.from_review_result(empty)["review_findings"],
                             {"total": 0, "p0": 0, "p1": 0, "p2": 0, "p3": 0, "unresolved_blocking": 0})
            for bad in ([], {"findings": {}}, {"findings": ["P1"]}, {"findings": [{"severity": "p1"}]},
                        {"findings": [{"severity": "P4"}]}, {"findings": [{"status": "open"}]},
                        {"findings": [{"severity": "P2", "status": "wontfix"}]}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    MODULE.from_review_result(self.write(root, "bad.json", json.dumps(bad)))

    def test_review_findings_package_for_each_ai_review_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.write(root, "qa.json", json.dumps({"findings": [{"severity": "P1", "status": "open"}]}))
            counts, packaged = root / "counts.json", root / "packaged.json"
            self.assertEqual(MODULE.main(["review-findings", str(result), "--output", str(counts)]), 0)
            self.assertEqual(MODULE.main(["review-findings", str(root / "missing.json"), "--output", str(root / "x.json")]), 2)
            env = {"GITHUB_RUN_ID": "55", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": "owner/repo"}
            for control in ("ai-engineering-review", "ai-qa-review", "ai-security-review", "ai-repository-standards-review"):
                for outcome in ("success", "failure"):
                    with self.subTest(control=control, outcome=outcome), mock.patch.dict(os.environ, env):
                        self.assertEqual(MODULE.main(["package", "--control", control, "--input", str(counts),
                                                      "--outcome", outcome, "--head-sha", HEAD,
                                                      "--output", str(packaged)]), 0)
                        self.assertEqual(json.loads(packaged.read_text())["control"], control)

    def test_semgrep_report_is_counted_by_severity(self) -> None:
        document = MODULE.from_semgrep(REPORTS / "semgrep.json")
        self.assertEqual(document, {"version": 1, "source": "pull-request-workflow", "findings": {
            "total": 6, "critical": 1, "high": 2, "medium": 1, "low": 1, "unrated": 1}})
        # Counts only: nothing from the report's paths, rules, or messages is carried over.
        self.assertNotIn("src/", json.dumps(document))
        with tempfile.TemporaryDirectory() as directory:
            clean = self.write(Path(directory), "clean.json", json.dumps({"results": [], "errors": []}))
            self.assertEqual(MODULE.from_semgrep(clean)["findings"]["total"], 0)

    def test_semgrep_report_rejects_malformed_or_incomplete_scans(self) -> None:
        for document in ([], {"results": []}, {"results": {}, "errors": []}, {"results": [1], "errors": []},
                         {"results": [], "errors": [{"level": "error", "message": "rule parse failure"}]},
                         {"results": [], "errors": ["boom"]}):
            with self.subTest(document=document), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    MODULE.from_semgrep(self.write(Path(directory), "bad.json", json.dumps(document)))

    def test_gitleaks_findings_are_unrated(self) -> None:
        document = MODULE.from_gitleaks(REPORTS / "gitleaks.json")
        self.assertEqual(document["findings"], {"total": 3, "critical": 0, "high": 0, "medium": 0, "low": 0, "unrated": 3})
        self.assertNotIn("config/", json.dumps(document))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(MODULE.from_gitleaks(self.write(root, "clean.json", "[]"))["findings"]["total"], 0)
            for text in ("{}", "[1]", '[{"File": "x"}]', "not json"):
                with self.subTest(text=text), self.assertRaises(ValueError):
                    MODULE.from_gitleaks(self.write(root, "bad.json", text))

    def test_scanner_reports_package_for_their_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {"GITHUB_RUN_ID": "7", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": "o/r"}):
            root = Path(directory)
            for converter, report, control in (("semgrep", "semgrep.json", "custom-static-analysis"),
                                               ("gitleaks", "gitleaks.json", "secret-detection")):
                with self.subTest(converter=converter):
                    counts, packaged = root / f"{converter}-input.json", root / f"{converter}-package.json"
                    self.assertEqual(MODULE.main([converter, str(REPORTS / report), "--output", str(counts)]), 0)
                    self.assertEqual(MODULE.main(["package", "--control", control, "--input", str(counts),
                                                  "--outcome", "failure", "--head-sha", HEAD, "--output", str(packaged)]), 0)
                    self.assertEqual(json.loads(packaged.read_text())["control"], control)
                    rejected = root / f"{converter}-rejected.json"
                    self.assertEqual(MODULE.main(["package", "--control", "unit-tests", "--input", str(counts),
                                                  "--outcome", "failure", "--head-sha", HEAD, "--output", str(rejected)]), 2)
                    self.assertFalse(rejected.exists())

    def test_package_binds_run_and_validates_against_outcome(self) -> None:
        measurements = {"version": 1, "source": "pull-request-workflow",
                        "tests": {"total": 2, "passed": 1, "failed": 1, "skipped": 0}}
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "55", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_REPOSITORY": "owner/repo"}):
            document = MODULE.package("unit-tests", measurements, "failure", HEAD)
            self.assertEqual(document, {"version": 1, "run_id": 55, "run_attempt": 2, "repository": "owner/repo",
                                        "head_sha": HEAD, "control": "unit-tests", "measurements": measurements})
            for control, outcome, head in (("unit-tests", "success", HEAD), ("unit-tests", "cancelled", HEAD),
                                           ("changed-code-coverage", "failure", HEAD), ("unit-tests", "failure", "abc")):
                with self.subTest(control=control, outcome=outcome, head=head), self.assertRaises(ValueError):
                    MODULE.package(control, measurements, outcome, head)
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "55", "GITHUB_RUN_ATTEMPT": "", "GITHUB_REPOSITORY": "owner/repo"}):
            with self.assertRaises(ValueError):
                MODULE.package("unit-tests", measurements, "failure", HEAD)

    def test_cli_writes_output_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = self.write(root, "a.log", "Ran 1 test in 0s\n\nOK\n")
            output = root / "out" / "m.json"
            self.assertEqual(MODULE.main(["unittest", str(log), "--output", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text())["tests"]["total"], 1)
            missing = root / "missing.json"
            self.assertEqual(MODULE.main(["unittest", str(root / "none.log"), "--output", str(missing)]), 2)
            self.assertFalse(missing.exists())

    def test_installed_copy_matches_source(self) -> None:
        self.assertEqual(SCRIPT.read_bytes(), (ROOT / ".proof/measurements.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
