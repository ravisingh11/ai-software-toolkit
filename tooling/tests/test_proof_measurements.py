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

    def test_package_binds_run_and_validates_against_outcome(self) -> None:
        measurements = {"version": 1, "source": "pull-request-workflow",
                        "tests": {"total": 2, "passed": 1, "failed": 1, "skipped": 0}}
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "55", "GITHUB_REPOSITORY": "owner/repo"}):
            document = MODULE.package("unit-tests", measurements, "failure", HEAD)
            self.assertEqual(document, {"version": 1, "run_id": 55, "repository": "owner/repo",
                                        "head_sha": HEAD, "control": "unit-tests", "measurements": measurements})
            for control, outcome, head in (("unit-tests", "success", HEAD), ("unit-tests", "cancelled", HEAD),
                                           ("changed-code-coverage", "failure", HEAD), ("unit-tests", "failure", "abc")):
                with self.subTest(control=control, outcome=outcome, head=head), self.assertRaises(ValueError):
                    MODULE.package(control, measurements, outcome, head)

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
