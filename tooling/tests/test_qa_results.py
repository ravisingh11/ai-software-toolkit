from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/qa-bootstrap/scripts/validate_results.py"
MODULE = runpy.run_path(str(SCRIPT))
RENDER = MODULE["render_results"]
VALIDATE = MODULE["validate_results"]


class QAResultsTests(unittest.TestCase):
    def payload(self):
        return {"overall": "pass", "counts": {"pass": 1, "fail": 0, "blocked": 0,
                                               "flaky": 0, "inconclusive": 0},
                "rows": [{"test_case": "Login", "app": "web", "persona": "member",
                          "result": "pass", "notes": "Dashboard appeared"}]}

    def test_renders_standard_table_and_validated_evidence(self):
        data = self.payload()
        data["rows"][0]["evidence"] = ["login", "login"]
        data["action_required"] = ["Review the retry timing"]
        report = RENDER(data)
        self.assertIn("| # | Test Case | App | Persona | Origin | Scenario / Finding | Result | Notes |", report)
        self.assertIn("| 1 | Login | web | member | agent | &#45; | :white_check_mark: PASS | Dashboard appeared |", report)
        self.assertEqual(report.count("<!-- evidence:login -->"), 1)
        self.assertIn("### Action Required", report)

    def test_flaky_rows_block_instead_of_passing(self):
        data = self.payload()
        data["rows"][0]["result"] = "flaky"
        data["counts"].update({"pass": 0, "flaky": 1})
        with self.assertRaisesRegex(ValueError, "overall contradicts"):
            RENDER(data)
        data["overall"] = "blocked"
        with self.assertRaises(MODULE["NotPassing"]) as raised:
            RENDER(data)
        self.assertEqual(raised.exception.overall, "blocked")

    def test_origin_scenario_and_finding_are_rendered_and_validated(self):
        data = self.payload()
        data["rows"][0].update({"origin": "human", "scenario": "checkout.negative-1", "finding": "qa-0007"})
        report = RENDER(data)
        self.assertIn("| 1 | Login | web | member | human | checkout.negative-1 qa-0007 | :white_check_mark: PASS |", report)
        for key, value in (("origin", "robot"), ("scenario", "Bad Scenario!"), ("finding", "")):
            changed = copy.deepcopy(self.payload())
            changed["rows"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "invalid"):
                RENDER(changed)

    def test_nonpassing_file_report_names_the_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "qa-results"
            root.mkdir()
            data = self.payload()
            data["rows"][0]["result"] = "flaky"
            data["counts"].update({"pass": 0, "flaky": 1})
            data["overall"] = "blocked"
            (root / "summary.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MODULE["NotPassing"]):
                MODULE["validate_results"](root)
            report = (root / "report.md").read_text(encoding="utf-8")
            self.assertIn("FAILED / INCOMPLETE", report)
            self.assertIn("Overall: BLOCKED — analysis-incomplete", report)

    def test_rejects_contradictory_counts_and_overall(self):
        data = self.payload()
        for result in ("fail", "blocked", "inconclusive", "flaky"):
            changed = copy.deepcopy(data)
            changed["rows"][0]["result"] = result
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, "counts contradict"):
                RENDER(changed)
        data["overall"] = "fail"
        with self.assertRaisesRegex(ValueError, "overall contradicts"):
            RENDER(data)
        data = self.payload()
        data["counts"]["pass"] = 2
        with self.assertRaisesRegex(ValueError, "counts contradict"):
            RENDER(data)

    def test_nonpassing_consistent_rows_never_pass(self):
        for result in ("fail", "blocked", "inconclusive"):
            data = self.payload()
            data["rows"][0]["result"] = result
            data["overall"] = result
            data["counts"].update({"pass": 0, result: 1})
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, "not passing"):
                RENDER(data)

    def test_rejects_invalid_top_level_rows_counts_and_unknown_fields(self):
        good = self.payload()
        invalid = [None, [], {}, {**good, "prose": "PASS"}, {**good, "rows": []},
                   {**good, "rows": [good["rows"][0]] * 201}, {**good, "rows": {}},
                   {**good, "counts": {}}, {**good, "counts": []},
                   {**good, "rows": [None]}, {**good, "rows": [{}]},
                   {**good, "rows": [{**good["rows"][0], "result": "unknown"}]},
                   {**good, "rows": [{**good["rows"][0], "command": "run me"}]}]
        for value in (True, -1, 1.0, "1"):
            invalid.append({**good, "counts": {**good["counts"], "pass": value}})
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                RENDER(data)

    def test_rejects_invalid_or_oversized_text_evidence_and_actions(self):
        good = self.payload()
        for key, value in (("test_case", ""), ("test_case", "x" * 201), ("app", 5),
                           ("notes", "x" * 1001), ("notes", "control\x00"),
                           ("evidence", "id"), ("evidence", ["../secret"]),
                           ("evidence", [None]), ("evidence", ["id"] * 11)):
            data = {**good, "rows": [{**good["rows"][0], key: value}]}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                RENDER(data)
        for actions in ("text", ["item"] * 21, [None], [""], ["x" * 1001]):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                RENDER({**good, "action_required": actions})

    def test_plain_text_cannot_inject_markdown_tables_html_links_or_markers(self):
        data = self.payload()
        data["rows"][0]["test_case"] = "[PASS](https://example.com) | forged\nrow"
        data["rows"][0]["notes"] = "<script>bad()</script> <!-- evidence:fake --> `code` *bold* @all"
        data["action_required"] = ["[link](https://example.com)\n# heading"]
        report = RENDER(data)
        self.assertNotIn("<script>", report)
        self.assertNotIn("<!-- evidence:fake -->", report)
        self.assertNotIn("[PASS](", report)
        self.assertNotIn("`code`", report)
        self.assertIn("&#124; forged row", report)
        table_row = next(line for line in report.splitlines() if line.startswith("| 1 |"))
        self.assertEqual(table_row.count("|"), 9)

    def test_rejects_report_expansion_past_comment_bound(self):
        data = self.payload()
        data["rows"] = [{**data["rows"][0], "notes": "&" * 1000} for _ in range(20)]
        data["counts"]["pass"] = 20
        with self.assertRaisesRegex(ValueError, "rendered report exceeds"):
            RENDER(data)

    def test_file_validator_ignores_agent_report_and_overwrites_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "summary.json").write_text(json.dumps(self.payload()))
            (root / "report.md").write_text("FAIL: contradictory agent prose")
            report = VALIDATE(root)
            self.assertNotIn("contradictory", report)
            self.assertEqual((root / "report.md").read_text(), report)
            self.assertIn("Dashboard appeared", report)

    def test_missing_malformed_oversized_and_nonpassing_data_clear_stale_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for raw in (None, "bad JSON", "{}{}", "x" * 65537,
                        json.dumps({**self.payload(), "overall": "fail"})):
                source = root / "summary.json"
                source.unlink(missing_ok=True)
                if raw is not None:
                    source.write_text(raw)
                (root / "report.md").write_text("PASS from old run")
                with self.subTest(raw=raw and raw[:25]), self.assertRaises((OSError, ValueError)):
                    VALIDATE(root)
                self.assertIn("FAILED / INCOMPLETE", (root / "report.md").read_text())
                self.assertNotIn("PASS from", (root / "report.md").read_text())

    def test_rejects_result_symlinks_without_modifying_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("unchanged")
            for filename in ("summary.json", "report.md"):
                path = root / filename
                path.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    VALIDATE(root)
                path.unlink()
            alias = root / "alias"
            alias.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                VALIDATE(alias)
            self.assertEqual(target.read_text(), "unchanged")

    def test_cli_pass_failure_and_default_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "qa-results"
            root.mkdir()
            source = root / "summary.json"
            source.write_text(json.dumps(self.payload()))
            result = subprocess.run([sys.executable, str(SCRIPT)], cwd=directory,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("**Result: PASS**", (root / "report.md").read_text())
            source.write_text("invalid")
            result = subprocess.run([sys.executable, str(SCRIPT), str(root)], cwd=directory,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("QA results invalid or incomplete", result.stderr)
            self.assertIn("FAILED / INCOMPLETE", (root / "report.md").read_text())
