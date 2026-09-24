from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CoverageSummaryTests(unittest.TestCase):
    def run_coverage(self, report: str, status: int, *, summary_enabled: bool = True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tooling").mkdir()
            shutil.copy2(ROOT / "tooling/changed_code_coverage.sh", root / "tooling")
            binaries = root / "bin"
            binaries.mkdir()
            coverage = binaries / "coverage"
            coverage.write_text(
                '#!/bin/bash\nset -eu\n'
                'if [[ "$1" == "xml" ]]; then\n'
                '  printf \'%s\\n\' \'<class filename="full-test-suite/scripts/full_test_suite_runner.py"/>\' '
                '\'<class filename="full-test-suite/scripts/full_test_suite_executor.py"/>\' '
                '\'<class filename="issue-operator/scripts/gh_issue_helper.py"/>\' > "$3"\n'
                'fi\n', encoding="utf-8",
            )
            diff_cover = binaries / "diff-cover"
            diff_cover.write_text(
                '#!/bin/bash\nset -eu\n'
                'while (($#)); do\n'
                '  if [[ "$1" == "--format" ]]; then\n'
                '    printf \'%s\\n\' "$TEST_REPORT" > "${2#markdown:}"\n'
                '    shift\n'
                '  fi\n'
                '  shift\n'
                'done\n'
                'exit "$TEST_STATUS"\n', encoding="utf-8",
            )
            coverage.chmod(0o755)
            diff_cover.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{binaries}:/usr/bin:/bin",
                "GUARDRAILS_COVERAGE_BASE_REF": "base-sha",
                "GUARDRAILS_COVERAGE_TARGET": "90",
                "TEST_REPORT": report,
                "TEST_STATUS": str(status),
            }
            summary = root / "summary.md"
            if summary_enabled:
                summary.write_text("Earlier step summary\n", encoding="utf-8")
                environment["GITHUB_STEP_SUMMARY"] = str(summary)
            else:
                environment.pop("GITHUB_STEP_SUMMARY", None)
            completed = subprocess.run(
                ["bash", str(root / "tooling/changed_code_coverage.sh")],
                cwd=root, env=environment, capture_output=True, text=True,
                check=False, timeout=10,
            )
            return completed, summary.read_text() if summary.exists() else None

    def test_empty_diff_explains_no_percentage_instead_of_claiming_full_coverage(self):
        completed, summary = self.run_coverage("No lines with coverage information in this diff.", 0)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIsNotNone(summary)
        self.assertIn("Earlier step summary", summary)
        self.assertIn("no changed lines to measure", summary)
        self.assertIn("No coverage percentage applies", summary)
        self.assertNotIn("100%", summary)

    def test_passing_comparison_publishes_the_real_report_and_target(self):
        report = "# Diff Coverage\n- **Total**: 20 lines\n- **Coverage**: 95.0%"
        completed, summary = self.run_coverage(report, 0)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIsNotNone(summary)
        self.assertIn("Passed", summary)
        self.assertIn("90%", summary)
        self.assertIn(report, summary)

    def test_failed_comparison_retains_failure_and_publishes_details(self):
        report = "# Diff Coverage\n- **Total**: 20 lines\n- **Coverage**: 80.0%"
        completed, summary = self.run_coverage(report, 1)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIsNotNone(summary)
        self.assertIn("Failed", summary)
        self.assertNotIn("**Result:** Passed", summary)
        self.assertIn(report, summary)

    def test_local_run_needs_no_github_summary_file(self):
        completed, summary = self.run_coverage("# Diff Coverage", 0, summary_enabled=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIsNone(summary)
