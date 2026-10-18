"""Integration tests for the opt-in coverage wrapper using isolated repositories."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "check_changed_coverage.py"


class ChangedCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        (self.root / "src").mkdir()
        (self.root / "src/code.py").write_text("value = 1\n")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        (self.root / "src/code.py").write_text("value = 2\nother = 3\n")
        self.commit()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        tool = self.bin / "diff-cover"
        tool.write_text("#!/usr/bin/env python3\nimport os,sys,json\nfrom pathlib import Path\nfor arg in sys.argv:\n    if arg.startswith('--json-report='):\n        Path(arg.split('=',1)[1]).write_text(json.dumps({'total_num_lines': 2}))\nsys.exit(int(os.environ.get('DIFF_EXIT', '0')))\n")
        tool.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")

    def report(self, filename="src/code.py", lines=(1, 2), source=""):
        return ('<coverage><sources><source>' + source + '</source></sources><packages>'
                '<package><classes><class filename="' + filename + '"><lines>' +
                ''.join('<line number="%s" hits="1"/>' % n for n in lines) +
                '</lines></class></classes></package></packages></coverage>')

    def run_check(self, report=None, extra=(), code=None, diff_exit=0, real=False, placeholder="{report}"):
        if code is None:
            code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(%r)" % (
                self.report() if report is None else report)
        args = [sys.executable, str(SCRIPT), "--base", self.base, "--threshold", "90",
                "--source", "src", "--working-directory", str(self.root), *extra,
                "--", sys.executable, "-c", code, placeholder]
        return subprocess.run(args, text=True, capture_output=True,
                              env={**os.environ, "PATH": os.environ["PATH"] if real else str(self.bin) + os.pathsep + os.environ["PATH"],
                                   "DIFF_EXIT": str(diff_exit)})

    def test_valid_report_and_threshold_failure(self):
        self.assertEqual(self.run_check().returncode, 0)
        self.assertNotEqual(self.run_check(diff_exit=1).returncode, 0)

    def test_missing_empty_malformed_and_invalid_report(self):
        for report in ("", "<", "<coverage/>", self.report(lines=(0,)),
                       self.report().replace('hits="1"', 'hits="-1"'),
                       '<!DOCTYPE coverage><coverage/>'):
            with self.subTest(report=report):
                self.assertNotEqual(self.run_check(report=report).returncode, 0)
        self.assertNotEqual(self.run_check(code="pass").returncode, 0)
        self.assertNotEqual(self.run_check(code="raise SystemExit(3)").returncode, 0)

    def test_standard_cobertura_doctype_is_inert(self):
        declaration = '<!DOCTYPE coverage SYSTEM "http://cobertura.sourceforge.net/xml/coverage-04.dtd">'
        self.assertEqual(self.run_check(report=declaration + self.report()).returncode, 0)
        for declaration in (
            '<!DOCTYPE coverage SYSTEM "https://example.com/other.dtd">',
            '<!DOCTYPE coverage [<!ENTITY value "unsafe">]>',
            '<!DOCTYPE coverage SYSTEM "http://cobertura.sourceforge.net/xml/coverage-04.dtd" [<!ENTITY value "unsafe">]>',
        ):
            with self.subTest(declaration=declaration):
                self.assertNotEqual(self.run_check(report=declaration + self.report()).returncode, 0)

    def test_missing_changed_source(self):
        (self.root / "unrelated.py").write_text("value = 1\nother = 2\n")
        self.commit()
        self.assertNotEqual(self.run_check(report=self.report("unrelated.py")).returncode, 0)

    def test_oversized_report_rejected(self):
        code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b' ' * (10 * 1024 * 1024 + 1))"
        result = self.run_check(code=code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds 10 MiB", result.stderr)

    @unittest.skipUnless(shutil.which("diff-cover") and importlib.util.find_spec("coverage"),
                         "real diff-cover and coverage.py required")
    def test_coverage_python_statement_mapping_and_exclusions(self):
        (self.root / "src/code.py").write_text(
            '"""Module documentation."""\n'
            'value = (\n    1 +\n    2\n)\n'
            'def excluded():  # pragma: no cover\n    return 99\n'
            'assert value == 3\n')
        self.commit()
        with tempfile.TemporaryDirectory() as external_directory:
            external = Path(external_directory) / "interpreter_hook.py"
            external.write_text("external_hook_ran = True\n")
            code = ("import coverage, runpy, sys; "
                    "cov = coverage.Coverage(data_file=None, config_file=False, source=['src']); "
                    "cov.start(); runpy.run_path(" + repr(str(external)) + "); "
                    "runpy.run_path('src/code.py'); cov.stop(); "
                    "cov.xml_report(outfile=sys.argv[1])")
            result = self.run_check(code=code, real=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_nested_source_mapping(self):
        self.assertEqual(self.run_check(report=self.report("code.py", source=str(self.root / "src"))).returncode, 0)
        self.assertNotEqual(self.run_check(report=self.report("../src/code.py")).returncode, 0)

    def test_required_configuration(self):
        for missing in ("--threshold", "--source", "--base"):
            options = {"--base": self.base, "--source": "src", "--threshold": "90"}
            del options[missing]
            args = [sys.executable, str(SCRIPT)]
            for key, value in options.items():
                args.extend((key, value))
            result = subprocess.run(args, capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_bad_configuration_and_missing_base(self):
        for extra in (("--base", "does-not-exist"), ("--threshold", "101"),
                      ("--threshold", "nan"), ("--source", "../outside")):
            with self.subTest(extra=extra):
                self.assertNotEqual(self.run_check(extra=extra).returncode, 0)

    def test_report_directory_and_stale_file(self):
        code = "from pathlib import Path; import sys; (Path(sys.argv[1]) / 'cobertura-coverage.xml').write_text(%r)" % self.report()
        self.assertEqual(self.run_check(code=code, placeholder="{report_dir}").returncode, 0)
        (self.root / "coverage.xml").write_text(self.report())
        self.assertNotEqual(self.run_check(code="pass").returncode, 0)

    @unittest.skipUnless(shutil.which("diff-cover"), "real diff-cover not installed")
    def test_real_diff_cover_threshold(self):
        result = self.run_check(real=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        result = self.run_check(real=True, report=self.report().replace('hits="1"', 'hits="0"'))
        self.assertNotEqual(result.returncode, 0, result.stdout)

    @unittest.skipUnless(shutil.which("diff-cover"), "real diff-cover not installed")
    def test_real_diff_cover_literal_bracket_path(self):
        self.base = self.git("rev-parse", "HEAD").strip()
        (self.root / "src/[id].py").write_text("value = 1\nother = 2\n")
        self.commit()
        result = self.run_check(real=True, report=self.report(filename="src/[id].py"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_dirty_source_rejected(self):
        (self.root / "src/code.py").write_text("uncommitted = 1\n")
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_docs_and_deletion_only_not_applicable(self):
        self.base = self.git("rev-parse", "HEAD").strip()
        (self.root / "README.md").write_text("docs\n")
        self.commit()
        result = self.run_check(code="raise SystemExit(99)")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not_applicable", result.stdout)
        self.base = self.git("rev-parse", "HEAD").strip()
        (self.root / "src/code.py").unlink()
        self.commit()
        self.assertIn("not_applicable", self.run_check().stdout)


if __name__ == "__main__":
    unittest.main()
