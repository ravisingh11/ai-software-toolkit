"""Behavior checks for the optional JUnit integrity runner."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'check_test_integrity.py'
SPEC = importlib.util.spec_from_file_location('check_test_integrity', SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class ReportTests(unittest.TestCase):
    def check(self, xml, **options):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.xml'
            report.write_text(xml, encoding='utf-8')
            return runner.inspect_report(report, **options)

    def test_pass_and_nested_suites_count_cases_once(self):
        result = self.check('<testsuites tests="2"><testsuite tests="2"><testsuite tests="1"><testcase/></testsuite><testcase/></testsuite></testsuites>')
        self.assertEqual(result, (2, 0))

    def test_node_reporter_cases_directly_under_testsuites(self):
        self.assertEqual(self.check('<testsuites><testcase name="node case"/></testsuites>'), (1, 0))

    def test_missing_empty_malformed_and_unknown_reports(self):
        with self.assertRaises(ValueError):
            runner.inspect_report(Path('/nonexistent/test-integrity/report.xml'))
        for xml in ('', '<testsuite>', '<report><testcase/></report>', '<testsuite/>'):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                self.check(xml)

    def test_all_skipped_and_failure_or_error_rejected(self):
        for content in ('<skipped/>', '<failure/>', '<error/>', '<skipped/><failure/>'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.check('<testsuite><testcase>' + content + '</testcase></testsuite>')

    def test_thresholds(self):
        xml = '<testsuite><testcase/><testcase><skipped/></testcase></testsuite>'
        self.assertEqual(self.check(xml, max_skipped_percent=50), (2, 1))
        for options in ({'max_skipped_percent': 49}, {'min_tests': 3}):
            with self.assertRaises(ValueError):
                self.check(xml, **options)

    def test_contradictory_or_malformed_counts(self):
        for attribute in ('tests="0"', 'tests="x"', 'tests="-1"', 'failures="1"', 'errors="1"', 'skipped="1"'):
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                self.check('<testsuite ' + attribute + '><testcase/></testsuite>')

    def test_misplaced_elements_are_rejected(self):
        for xml in (
            '<testsuite><properties><testcase/></properties></testsuite>',
            '<testsuite><testcase><testsuite/></testcase></testsuite>',
            '<testsuite><failure/><testcase/></testsuite>',
        ):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                self.check(xml)

    def test_invalid_thresholds(self):
        for options in ({'min_tests': 0}, {'max_skipped_percent': float('nan')}, {'max_skipped_percent': 101}):
            with self.assertRaises(ValueError):
                self.check('<testsuite><testcase/></testsuite>', **options)

    def test_entities_and_size_are_rejected(self):
        with self.assertRaises(ValueError):
            self.check('<!DOCTYPE testsuite [<!ENTITY x "payload">]><testsuite><testcase>&x;</testcase></testsuite>')
        with self.assertRaises(ValueError):
            self.check('<testsuite>' + ' ' * runner.MAX_REPORT_BYTES + '</testsuite>')


class CommandTests(unittest.TestCase):
    def invoke(self, body, *options):
        return subprocess.run([sys.executable, str(SCRIPT), *options, '--', sys.executable, '-c', body, '{report}'], text=True, capture_output=True)

    def test_command_success_and_argument_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='test integrity ') as directory:
            result = self.invoke('import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("<testsuite><testcase/></testsuite>"); assert pathlib.Path.cwd().name.startswith("test integrity ")', '--working-directory', directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 tests', result.stdout)

    def test_nonzero_command_cannot_pass(self):
        result = self.invoke('import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("<testsuite><testcase/></testsuite>"); sys.exit(3)')
        self.assertNotEqual(result.returncode, 0)

    def test_no_report_or_unrelated_stale_report_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'report.xml').write_text('<testsuite><testcase/></testsuite>')
            result = self.invoke('pass', '--working-directory', directory)
        self.assertNotEqual(result.returncode, 0)

    def test_missing_executable(self):
        with self.assertRaisesRegex(ValueError, 'could not start'):
            runner.run_tests(['/nonexistent/test-integrity/executable', '{report}'])

    def test_invalid_options_and_missing_placeholder(self):
        for args in (['--min-tests', '0'], ['--max-skipped-percent', '-1'], ['--max-skipped-percent', '101'], ['--max-skipped-percent', 'nan'], ['--max-skipped-percent', 'inf'], ['--', sys.executable, '-c', 'pass']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True)
                self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
