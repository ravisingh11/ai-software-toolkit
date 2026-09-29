from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "render_scorecard_badge.py"
SPEC = importlib.util.spec_from_file_location("render_scorecard_badge", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise AssertionError(f"cannot load module spec: {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


REVISION = "a" * 40
RUN_URL = "https://github.com/owner/repo/actions/runs/12345/attempts/2"
CREATED_AT = "2026-09-08T12:00:00Z"


def scorecard(
    *,
    status: str = "GREEN",
    decision: str = "allow",
    enforced: tuple[int, int] = (10, 10),
    advisory: tuple[int, int] = (4, 4),
    revision: str = REVISION,
) -> dict[str, Any]:
    return {
        "version": 2,
        "status": status,
        "decision": decision,
        "policy": "test-policy",
        "operation": "change",
        "subject": {"type": "git-commit", "revision": revision},
        "enforced": {"passed": enforced[0], "total": enforced[1], "percent": 100.0},
        "advisory": {"passed": advisory[0], "total": advisory[1], "percent": 100.0},
        "controls": [{"id": "private-control", "provider": "secret-provider"}],
        "findings": [{"message": "private-finding"}],
        "evidence": ["https://checks.example/private"],
        "reason": "private-reason",
    }


class RendererTests(unittest.TestCase):
    def write_source(self, root: Path, card: dict[str, Any] | None = None) -> Path:
        source = root / "source"
        source.mkdir()
        (source / "scorecard-20260908-120000Z.json").write_text(
            json.dumps(card or scorecard()) + "\n", encoding="utf-8"
        )
        (source / "scorecard-20260908-120000Z.md").write_text(
            "PRIVATE SOURCE MARKDOWN\n", encoding="utf-8"
        )
        return source

    def render(self, source: Path, output: Path, **overrides: Any) -> dict[str, Any]:
        values = {
            "repository": "owner/repo",
            "run_id": 12345,
            "run_attempt": 2,
            "run_url": RUN_URL,
            "source_run_created_at": CREATED_AT,
            "expected_revision": REVISION,
        }
        values.update(overrides)
        return MODULE.render_badge(source, output, **values)

    def test_green_output_is_bounded_and_contains_public_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            output = root / "published"

            metadata = self.render(source, output)

            digest = hashlib.sha256(REVISION.encode()).hexdigest()
            self.assertEqual(metadata["message"], "GREEN 14/14")
            self.assertEqual(metadata["source_run_id"], 12345)
            self.assertEqual(metadata["source_run_attempt"], 2)
            self.assertEqual(metadata["source_run_created_at"], CREATED_AT)
            self.assertEqual(metadata["subject_digest"], f"sha256:{digest}")
            names = {path.name for path in output.iterdir()}
            self.assertEqual(
                names,
                {
                    "proof-badge.svg",
                    "scorecard.json",
                    "scorecard.md",
                    "index.html",
                },
            )
            for path in output.iterdir():
                text = path.read_text(encoding="utf-8")
                for expected in (
                    "Latest PR Scorecard",
                    "GREEN",
                    "14/14",
                    "change",
                    "owner/repo",
                    "12345",
                    "2",
                    CREATED_AT,
                    digest,
                ):
                    self.assertIn(expected, text, path.name)
                for private in (
                    REVISION,
                    "private-control",
                    "private-finding",
                    "secret-provider",
                    "private-reason",
                    "checks.example",
                    "PRIVATE SOURCE MARKDOWN",
                ):
                    self.assertNotIn(private, text, path.name)
            page = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('<span class="brand-name">AI Software Toolkit</span>', page)
            self.assertNotIn('<span class="brand-name">Proof</span>', page)

    def breakdown_card(self) -> dict[str, Any]:
        card = scorecard(status="ORANGE", enforced=(1, 1), advisory=(1, 4))
        card["controls"] = [
            {"id": f"private-{index}", "effective_mode": mode, "evidence_status": status}
            for index, (mode, status) in enumerate([
                ("enforced", "passed"), ("advisory", "passed"),
                ("advisory", "failed"), ("advisory", "blocked"), ("advisory", "no_result"),
                ("not_activated", "not_activated"),
            ])
        ]
        return card

    def test_breakdown_preserves_distinct_results_and_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "published"
            metadata = self.render(self.write_source(root, self.breakdown_card()), output)
            self.assertEqual(metadata["result_breakdown"]["overall"], {
                "passed": 2, "failed": 1, "blocked": 1, "unverified": 1,
            })
            self.assertEqual(metadata["result_breakdown"]["enforced"], {
                "passed": 1, "failed": 0, "blocked": 0, "unverified": 0,
            })
            for filename in ("index.html", "scorecard.md"):
                text = (output / filename).read_text()
                for expected in ("Unverified", "Blocked", "mergeability or release readiness",
                                 "current PR head", "Test totals", MODULE._SIZE_GUIDANCE):
                    self.assertIn(expected, text)
                self.assertNotIn("private-", text)

    def test_incomplete_or_inconsistent_breakdown_is_unavailable(self) -> None:
        for mutation in ("missing", "empty", "duplicate", "unknown", "mode", "passed", "malformed"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                card = self.breakdown_card()
                if mutation == "missing":
                    del card["controls"]
                elif mutation == "empty":
                    card["controls"] = []
                elif mutation == "duplicate":
                    card["controls"][1]["id"] = card["controls"][0]["id"]
                elif mutation == "unknown":
                    card["controls"][2]["evidence_status"] = "skipped"
                elif mutation == "mode":
                    card["controls"][2]["effective_mode"] = []
                elif mutation == "passed":
                    card["controls"][2]["evidence_status"] = "passed"
                else:
                    card["controls"][2] = None
                root = Path(directory)
                metadata = self.render(self.write_source(root, card), root / "published")
                self.assertEqual(metadata["result_breakdown"], {"availability": "unavailable"})
                self.assertEqual(metadata["passed"], 2)
                self.assertIn("Result breakdown unavailable", (root / "published/index.html").read_text())

    def scope_card(self, *, exceeded: bool = False) -> dict[str, Any]:
        card = scorecard(status="ORANGE" if exceeded else "GREEN", advisory=(3 if exceeded else 4, 4))
        metrics = {"files": 2, "added_lines": 84, "changed_lines": 90,
                   "max_added_lines_per_file": 70, "binary_files": 0,
                   "total_files": 3, "total_added_lines": 92, "total_changed_lines": 100,
                   "excluded_files": 1, "excluded_added_lines": 8,
                   "excluded_changed_lines": 10, "excluded_binary_files": 0}
        card["controls"].append({"id": "change-scope", "effective_mode": "advisory",
            "authoritative_provider": {"id": "repository-change-scope"},
            "evidence_status": "failed" if exceeded else "passed",
            "authoritative_result": {"status": "failed" if exceeded else "passed",
                "change_scope": {"version": 1, "metrics": metrics,
                    "thresholds": {"max_files": 1 if exceeded else 12, "max_added_lines": 300,
                        "max_changed_lines": 500, "max_added_lines_per_file": 150},
                    "filenames": ["private-file.py"]}}})
        return card

    def test_scope_table_uses_validated_aggregate_metrics(self) -> None:
        for exceeded in (False, True):
            with self.subTest(exceeded=exceeded), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "published"
                metadata = self.render(self.write_source(root, self.scope_card(exceeded=exceeded)), output)
                self.assertEqual(metadata["change_scope"]["availability"], "available")
                page = (output / "index.html").read_text()
                for phrase in ("Files &amp; lines of code", "Advisory", "does not block", "Counted files", "Excluded", "Added + deleted lines"):
                    self.assertIn(phrase, page)
                self.assertIn("Above limit" if exceeded else "Within limit", page)
                for path in output.iterdir():
                    self.assertNotIn("private-file.py", path.read_text())

    def test_older_scope_evidence_is_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "published"
            metadata = self.render(self.write_source(root), output)
            self.assertEqual(metadata["change_scope"]["availability"], "unavailable")
            self.assertIn("Measurements unavailable", (output / "index.html").read_text())

    def test_enforced_scope_labels_blocking_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            card = self.scope_card(exceeded=True)
            card.update(status="RED", decision="block", enforced={"passed": 9, "total": 10}, advisory={"passed": 4, "total": 4})
            card["controls"][-1]["effective_mode"] = "enforced"
            output = root / "published"
            self.render(self.write_source(root, card), output)
            page = (output / "index.html").read_text()
            self.assertIn("Exceeding a limit blocks the policy decision.", page)
            self.assertNotIn("warns only", page)

    def test_untrusted_or_missing_producer_does_not_publish_metrics(self) -> None:
        for field, value in (("authoritative_provider", {"id": "other"}), ("evidence_status", "no_result"), ("effective_mode", "not_activated")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                card = self.scope_card()
                card["controls"][-1][field] = value
                metadata = self.render(self.write_source(root, card), root / "published")
                self.assertEqual(metadata["change_scope"], {"availability": "unavailable"})

    def test_invalid_scope_metrics_are_unavailable(self) -> None:
        for field, value in (("files", True), ("added_lines", -1), ("total_files", 4), ("changed_lines", 1), ("excluded_binary_files", 1)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                card = self.scope_card()
                card["controls"][-1]["authoritative_result"]["change_scope"]["metrics"][field] = value
                metadata = self.render(self.write_source(root, card), root / "published")
                self.assertEqual(metadata["change_scope"], {"availability": "unavailable"})

    def test_orange_and_red_semantics_render(self) -> None:
        cases = (
            (scorecard(status="ORANGE", advisory=(3, 4)), "ORANGE", "13/14"),
            (
                scorecard(status="RED", decision="block", enforced=(9, 10)),
                "RED",
                "13/14",
            ),
        )
        for index, (card, status, count) in enumerate(cases):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                output = root / f"published-{index}"
                metadata = self.render(self.write_source(root, card), output)
                self.assertEqual(metadata["status"], status)
                self.assertIn(
                    f"{status} {count}", (output / "proof-badge.svg").read_text()
                )

    def test_invalid_scorecard_semantics_fail_without_output(self) -> None:
        invalid_cards = []
        for field, value in (
            ("version", 1),
            ("operation", "release"),
            ("status", "GRAY"),
            ("decision", "maybe"),
        ):
            card = scorecard()
            card[field] = value
            invalid_cards.append(card)
        invalid_cards.extend(
            [
                scorecard(status="GREEN", advisory=(3, 4)),
                scorecard(status="ORANGE"),
                scorecard(status="RED", decision="block"),
                scorecard(status="RED", enforced=(9, 10)),
                scorecard(status="GREEN", decision="block"),
                scorecard(status="RED", decision="allow", enforced=(9, 10)),
                scorecard(enforced=(True, 10)),
                scorecard(enforced=(11, 10)),
                scorecard(enforced=(0, 0), advisory=(0, 0)),
            ]
        )
        card = scorecard()
        card["subject"]["type"] = "artifact"
        invalid_cards.append(card)
        card = scorecard(revision="A" * 40)
        invalid_cards.append(card)
        for field in ("status", "decision"):
            for value in ([], {}, 1, None):
                card = scorecard()
                card[field] = value
                invalid_cards.append(card)

        for index, card in enumerate(invalid_cards):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "published"
                with self.assertRaises(ValueError):
                    self.render(self.write_source(root, card), output)
                self.assertFalse(output.exists())

    def test_invalid_runtime_binding_fails_without_output(self) -> None:
        invalid = (
            {"run_id": 0},
            {"run_attempt": 0},
            {"run_attempt": True},
            {"repository": "owner"},
            {"source_run_created_at": "2026-09-08"},
            {"run_url": "http://github.com/owner/repo/actions/runs/12345/attempts/2"},
            {"run_url": "https://github.com/other/repo/actions/runs/12345/attempts/2"},
            {"run_url": "https://github.com/owner/repo/actions/runs/999/attempts/2"},
            {"expected_revision": "b" * 40},
        )
        for overrides in invalid:
            with (
                self.subTest(overrides=overrides),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                output = root / "published"
                with self.assertRaises(ValueError):
                    self.render(self.write_source(root), output, **overrides)
                self.assertFalse(output.exists())

    def test_invalid_source_layout_is_rejected(self) -> None:
        mutations = (
            "missing_json",
            "duplicate_json",
            "missing_markdown",
            "nested",
            "symlink",
            "large",
        )
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                source = self.write_source(root)
                json_path = next(source.glob("*.json"))
                markdown_path = next(source.glob("*.md"))
                if mutation == "missing_json":
                    json_path.unlink()
                elif mutation == "duplicate_json":
                    (source / "scorecard-20260908-120001Z.json").write_text(
                        json_path.read_text()
                    )
                elif mutation == "missing_markdown":
                    markdown_path.unlink()
                elif mutation == "nested":
                    (source / "nested").mkdir()
                elif mutation == "symlink":
                    markdown_path.unlink()
                    os.symlink(root / "outside.md", markdown_path)
                elif mutation == "large":
                    markdown_path.write_bytes(b"x" * (MODULE.MAX_MEMBER_BYTES + 1))
                with self.assertRaises(ValueError):
                    self.render(source, root / "published")

    def test_aggregate_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            for index in range(17):
                (source / f"extra-{index}.txt").write_bytes(
                    b"x" * MODULE.MAX_MEMBER_BYTES
                )
            with self.assertRaises(ValueError):
                self.render(source, root / "published")

    def test_execution_details_are_bounded_and_status_consistent(self) -> None:
        execution = {"version": 1, "started_at": "2026-09-27T01:00:00Z",
                     "completed_at": "2026-09-27T01:00:12Z", "duration_seconds": 12,
                     "conclusion": "success"}
        row = {"evidence_status": "passed", "authoritative_result": {"status": "passed", "check_execution": execution}}
        details = MODULE._execution_details(row)
        self.assertEqual(details["duration_seconds"], 12)
        self.assertEqual(details["availability"], "available")
        for mutation in ({"version": True}, {"duration_seconds": True}, {"duration_seconds": 11},
                         {"duration_seconds": -1}, {"conclusion": "failure"}, {"conclusion": []},
                         {"completed_at": "2026-09-27T01:00:12.123456789Z"}, {"completed_at": "invalid"}, {"started_at": "2026-09-27T02:00:00Z"},
                         {"started_at": "2026-09-27T01:00:00+00:99"}, {"started_at": None},
                         {"unexpected": "PRIVATE"}):
            with self.subTest(mutation=mutation):
                changed = {**row, "authoritative_result": {"status": "passed", "check_execution": {**execution, **mutation}}}
                self.assertEqual(MODULE._execution_details(changed), {"availability": "unavailable"})
        contradictory = {**row, "authoritative_result": {"status": "failed", "check_execution": execution}}
        self.assertEqual(MODULE._execution_details(contradictory), {"availability": "unavailable"})
        card = scorecard(enforced=(1, 1), advisory=(0, 0))
        card["controls"] = [{**row, "id": "build", "effective_mode": "enforced"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertIn("12s (12 seconds)", page)
            self.assertIn("Ran for <strong>12s</strong>", page)
            self.assertIn("2026-09-27T01:00:12Z", page)
            self.assertNotIn("Passing evidence reported for this snapshot", page)
            self.assertIn("Counts not reported", page)
            self.assertIn("This report does not include tests passed, failed, skipped, total.", page)

    def test_unknown_rows_are_not_described_as_excluded(self) -> None:
        card = scorecard()
        card["controls"] = [{"id": "build", "effective_mode": "enforced", "evidence_status": "passed"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertNotIn("excluded from the active-control totals", page)
            self.assertIn("whether they count toward the totals is unknown", page)

    def test_totals_are_reconciled_with_the_listed_checks(self) -> None:
        ids = [row[0] for row in MODULE.PUBLIC_CONTROLS]
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(2, 3))
        card["controls"] = [
            {"id": "build", "effective_mode": "advisory", "evidence_status": "passed"},
            {"id": "unit-tests", "effective_mode": "advisory", "evidence_status": "passed"},
            {"id": "deep-sast", "effective_mode": "advisory", "evidence_status": "failed"},
            *({"id": control_id, "effective_mode": "not_activated", "evidence_status": "not_activated"}
              for control_id in ids if control_id not in {"build", "unit-tests", "deep-sast", "runtime-soak"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            inactive = len(ids) - 4
            self.assertIn(f"The totals count 3 active checks. Of the {len(ids)} built-in checks listed below, "
                          f"3 are active, {inactive} are not activated and 1 is not reported. "
                          "Only active checks count toward the totals.", page)
            self.assertLess(page.index('class="metrics-note"'), page.index('id="results-title"'))

    def test_pull_request_checks_are_labeled_as_checked_separately(self) -> None:
        card = scorecard(status="GREEN", enforced=(0, 0), advisory=(1, 1))
        card["controls"] = [
            {"id": "build", "effective_mode": "advisory", "evidence_status": "passed"},
            {"id": "pr-metadata", "effective_mode": "not_activated", "evidence_status": "not_activated",
             "inactive_reason": "other_subject", "evidence_subject": "pull-request"},
            # Only the allowlisted pull-request subject gets the separate label.
            {"id": "deep-sast", "effective_mode": "not_activated", "evidence_status": "not_activated",
             "inactive_reason": "other_subject", "evidence_subject": "<script>"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["pr-metadata"]["separate_subject"], "pull-request")
            self.assertEqual(rows["pr-metadata"]["status"], "not_activated")
            self.assertIsNone(rows["deep-sast"]["separate_subject"])
            page = (root / "output/index.html").read_text()
            card_html = page[page.index('id="check-pr-metadata"'):]
            card_html = card_html[:card_html.index("</article>")]
            self.assertIn("Checked on the PR", card_html)
            self.assertIn("the pull request itself", card_html)
            self.assertNotIn("Not activated", card_html)
            self.assertNotIn("<script>", page)
            self.assertIn("1 is checked on the pull request", page)
            self.assertIn("Checks marked Checked on the PR run against the pull request", page)
            markdown = (root / "output/scorecard.md").read_text()
            self.assertIn("| PR Metadata | `pr-metadata` | Not activated | Checked on the PR |", markdown)

    def test_reconciliation_mentions_custom_and_unmatched_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, self.breakdown_card()), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertIn("5 custom checks also count but are not listed by name.", page)
            self.assertNotIn("private-", page)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertIn("Individual results could not be matched to these totals", page)
            self.assertNotIn("Only active checks count", page)

    def test_durations_are_human_readable(self) -> None:
        for seconds, expected in ((0, "0s"), (59, "59s"), (60, "1m 0s"), (743, "12m 23s"), (3723, "1h 2m 3s")):
            self.assertEqual(MODULE._duration(seconds), expected)

    def test_decision_meaning_reflects_enforcement(self) -> None:
        cases = (
            (scorecard(), "ALLOW means the enforced controls are satisfied", False),
            (scorecard(status="ORANGE", enforced=(0, 0), advisory=(3, 4)), "not gated by any control", True),
            (scorecard(status="RED", decision="block", enforced=(9, 10)), "BLOCK means at least one enforced control", False),
        )
        for card, expected, ungated in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.render(self.write_source(root, card), root / "output")
                page = (root / "output/index.html").read_text()
                markdown = (root / "output/scorecard.md").read_text()
                self.assertIn(expected, page)
                self.assertIn(expected, markdown)
                self.assertEqual("Advisory only" in page, ungated)
                if card["decision"] == "block":
                    self.assertNotIn("ALLOW means", page)

    def test_attention_counts_unnamed_custom_controls(self) -> None:
        card = self.breakdown_card()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            page = (root / "output/index.html").read_text()
            self.assertIn("3 custom controls without a passing result", page)
            self.assertNotIn("private-", page)
        card = scorecard()
        card["controls"] = [{"id": "build", "effective_mode": "enforced", "evidence_status": "passed"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.render(self.write_source(root, card), root / "output")
            self.assertNotIn('id="attention-title"', (root / "output/index.html").read_text())

    def measured_card(self, tests: dict[str, Any] | None = None, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
        card = scorecard(status="GREEN", enforced=(0, 0), advisory=(2, 2))
        tests = tests or {"total": 415, "passed": 412, "failed": 0, "skipped": 3}
        coverage = coverage or {"measured_lines": 200, "covered_lines": 182, "threshold_percent": 90}
        card["controls"] = [
            {"id": control_id, "effective_mode": "advisory", "evidence_status": "passed",
             "authoritative_result": {"status": "passed", "measurements": {
                 "version": 1, "source": "pull-request-workflow", kind: values}}}
            for control_id, kind, values in (("unit-tests", "tests", tests), ("changed-code-coverage", "coverage", coverage))
        ]
        return card

    def test_self_reported_measurements_are_labeled_and_replace_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, self.measured_card()), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual(rows["unit-tests"]["measurements"]["tests"]["passed"], 412)
            self.assertEqual(rows["build"]["measurements"], {"availability": "unavailable"})
            page = (root / "output/index.html").read_text()
            markdown = (root / "output/scorecard.md").read_text()
            for text in (page, markdown):
                self.assertIn("412 passed · 0 failed · 3 skipped (415 tests)", text)
                self.assertIn("182 of 200 changed lines covered (91.0%) · target 90%", text)
                self.assertIn("not independently verified", text)
            self.assertNotIn("does not include tests passed", page)
            self.assertIn("does not include queries run, vulnerabilities by severity.", page)
            self.assertIn("Test totals, coverage, and validator counts, where shown, are self-reported", page)

    def test_validator_measurements_are_summarized(self) -> None:
        card = scorecard(status="ORANGE", enforced=(0, 0), advisory=(2, 3))
        values = (("repository-validation", "passed", "contracts", {"total": 4, "passed": 4, "failed": 0, "not_run": 0}),
                  ("documentation-validation", "failed", "documentation",
                   {"markdown_files": 171, "links_checked": 912, "broken_links": 2, "mapping_failures": 0}),
                  ("repository-ground-truth", "passed", "documents", {"declared": 6, "found": 6, "missing": 0}))
        card["controls"] = [
            {"id": control_id, "effective_mode": "advisory", "evidence_status": status,
             "authoritative_result": {"status": status, "measurements": {
                 "version": 1, "source": "pull-request-workflow", kind: numbers}}}
            for control_id, status, kind, numbers in values
        ]
        rows = {row["id"]: row for row in MODULE._control_details(card)}
        summaries = {control_id: MODULE._measurement_summary(rows[control_id]["measurements"]) for control_id, *_ in values}
        self.assertEqual(summaries, {
            "repository-validation": "4 passed · 0 failed · 0 not run (4 contract groups)",
            "documentation-validation": "171 Markdown files · 912 local links checked · 2 broken · 0 documentation mapping failures",
            "repository-ground-truth": "6 of 6 declared documents found · 0 missing",
        })

    def test_contradictory_validator_measurements_are_unavailable(self) -> None:
        consistent = MODULE._measurements_consistent
        self.assertFalse(consistent("contracts", {"total": 4, "passed": 3, "failed": 0, "not_run": 1}, "passed"))
        self.assertFalse(consistent("contracts", {"total": 4, "passed": 4, "failed": 0, "not_run": 0}, "failed"))
        self.assertFalse(consistent("documentation", {"markdown_files": 1, "links_checked": 1, "broken_links": 2,
                                                      "mapping_failures": 0}, "failed"))
        self.assertFalse(consistent("documentation", {"markdown_files": 1, "links_checked": 1, "broken_links": 0,
                                                      "mapping_failures": 0}, "failed"))
        self.assertFalse(consistent("documents", {"declared": 6, "found": 5, "missing": 1}, "passed"))
        self.assertFalse(consistent("documents", {"declared": 6, "found": 6, "missing": 1}, "failed"))
        self.assertTrue(consistent("documents", {"declared": 6, "found": 5, "missing": 1}, "failed"))

    def test_coverage_percent_is_floored_and_empty_diffs_are_explicit(self) -> None:
        summary = MODULE._measurement_summary
        self.assertIn("(89.9%)", summary({"availability": "available", "coverage": {
            "measured_lines": 1000, "covered_lines": 899, "threshold_percent": 80}}))
        self.assertEqual(summary({"availability": "available", "coverage": {
            "measured_lines": 0, "covered_lines": 0, "threshold_percent": 80}}), "No measurable changed lines · target 80%")

    def test_invalid_or_contradictory_measurements_are_unavailable(self) -> None:
        for tests, coverage in (
            ({"total": 3, "passed": 2, "failed": 1, "skipped": 0}, None),
            ({"total": 9, "passed": 2, "failed": 0, "skipped": 0}, None),
            (None, {"measured_lines": 10, "covered_lines": 11, "threshold_percent": 90}),
            (None, {"measured_lines": 10, "covered_lines": 5, "threshold_percent": 90}),
        ):
            with self.subTest(tests=tests, coverage=coverage):
                card = self.measured_card(tests, coverage)
                rows = {row["id"]: row for row in MODULE._control_details(card)}
                target = "unit-tests" if tests else "changed-code-coverage"
                self.assertEqual(rows[target]["measurements"], {"availability": "unavailable"})
        card = self.measured_card()
        card["controls"][0]["authoritative_result"]["measurements"]["source"] = "trusted"
        card["controls"][1]["authoritative_result"]["status"] = "failed"
        rows = {row["id"]: row for row in MODULE._control_details(card)}
        self.assertEqual(rows["unit-tests"]["measurements"], {"availability": "unavailable"})
        self.assertEqual(rows["changed-code-coverage"]["measurements"], {"availability": "unavailable"})

    def test_public_catalog_matches_canonical_controls(self) -> None:
        catalog = json.loads((ROOT / "policies/control-catalog.yaml").read_text())["controls"]
        expected = [(row["id"], "PR Size" if row["id"] == "change-scope" else row["name"], row["purpose"]) for row in catalog]
        self.assertEqual([row[:3] for row in MODULE.PUBLIC_CONTROLS], expected)
        self.assertEqual(set(MODULE._CHECK_ASSESSMENTS), {row["id"] for row in catalog})
        self.assertEqual(SCRIPT.read_bytes(), (ROOT / ".proof/render_scorecard_badge.py").read_bytes())

    def test_individual_checks_preserve_results_without_private_fields(self) -> None:
        card = self.breakdown_card()
        ids = ["build", "unit-tests", "change-scope", "deep-sast", "functional-qa", "runtime-soak"]
        for row, control_id in zip(card["controls"], ids):
            row.update(id=control_id, name="PRIVATE TITLE <script>", reason="PRIVATE REASON",
                       provider="PRIVATE PROVIDER", evidence_url="https://private.example")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.render(self.write_source(root, card), root / "output")
            rows = {row["id"]: row for row in metadata["controls"]}
            self.assertEqual([rows[key]["status"] for key in ids],
                             ["passed", "passed", "failed", "blocked", "no_result", "not_activated"])
            self.assertEqual(rows["artifact-sbom"]["status"], "not_reported")
            for filename in ("index.html", "scorecard.md", "scorecard.json"):
                text = (root / "output" / filename).read_text()
                self.assertIn("PR Size", text)
                for private in ("PRIVATE TITLE", "PRIVATE REASON", "PRIVATE PROVIDER", "private.example"):
                    self.assertNotIn(private, text)
            page = (root / "output/index.html").read_text()
            self.assertEqual(page.count('<article class="check-detail '), len(MODULE.PUBLIC_CONTROLS))
            for label in ("Passed", "Failed", "Blocked", "Unverified", "Not activated", "Not reported"):
                self.assertIn(label, page)
            self.assertIn('href="#size-title"', page)
            self.assertEqual(page.count('scope="rowgroup"'), 4)
            self.assertEqual(page.count('Back to checks ↑'), len(MODULE.PUBLIC_CONTROLS))
            self.assertLess(page.index('</table></div></section><section class="checks"'), page.index('id="check-build"'))
            for control_id, name, *_ in MODULE.PUBLIC_CONTROLS:
                target = "size-title" if control_id == "change-scope" else f"check-{control_id}"
                self.assertIn(f'href="#{target}"', page)
                self.assertEqual(page.count(f'id="{target}"'), 1)
            self.assertIn('<th scope="col">Check</th><th scope="col">Result</th><th scope="col" class="mode-cell">Mode</th>', page)
            self.assertNotIn("Details ↓", page)
            # Checks needing attention lead the page, most severe first, before the totals.
            attention = page[page.index('id="attention-title"'):page.index('<div class="metrics">')]
            self.assertLess(attention.index('href="#size-title"'), attention.index('href="#check-deep-sast"'))
            self.assertLess(attention.index('href="#check-deep-sast"'), attention.index('href="#check-functional-qa"'))
            self.assertNotIn('href="#check-build"', attention)
            # Detail cards: attention first, then passes; inactive checks are grouped last.
            self.assertLess(page.index('id="check-deep-sast"'), page.index('id="check-build"'))
            self.assertLess(page.index('id="check-build"'), page.index('id="inactive-title"'))
            self.assertLess(page.index('id="inactive-title"'), page.index('id="check-runtime-soak"'))
            self.assertIn("Checked elsewhere, not activated, or not reported <span>(", page)
            self.assertIn("Not activated checks are excluded from the active-control totals.", page)
            self.assertIn("whether they count toward the totals is unknown", page)
            self.assertNotIn("excluded from the totals above", page)
            # PR Size measurements are a subsection of its card, not a nested titled panel.
            scope_card = page[page.index('id="check-change-scope"'):page.index('id="check-deep-sast"')]
            self.assertIn('<h4 id="size-title"', scope_card)
            self.assertNotIn("<h2", scope_card)
            self.assertEqual(scope_card.count("Advisory"), 1)
            # Each check shows its canonical catalog ID, in the table row and in its detail heading.
            self.assertIn('<a href="#check-build">Build</a> <code class="check-id">build</code>', page)
            self.assertIn('<h3>Build <code class="check-id">build</code></h3>', page)
            markdown = (root / "output/scorecard.md").read_text()
            self.assertIn("| Check | ID | Mode | Result | Purpose |", markdown)
            self.assertIn("| Build | `build` |", markdown)
            self.assertIn('aria-label="Source report for Build"', page)
            self.assertNotIn('aria-label="Source report for Artifact SBOM"', page)

    def test_inconsistent_rows_do_not_publish_individual_passes(self) -> None:
        card = scorecard()
        card["controls"] = [{"id": "build", "effective_mode": "enforced", "evidence_status": "passed"}]
        for rows in (card["controls"], card["controls"] * 2, None):
            card["controls"] = rows
            self.assertTrue(all(row["status"] == "not_reported" for row in MODULE._control_details(card)))

    def test_unknown_control_names_remain_private(self) -> None:
        card = scorecard(enforced=(1, 1), advisory=(0, 0))
        card["controls"] = [{"id": "private-customer-control", "effective_mode": "enforced", "evidence_status": "passed"}]
        projected = MODULE._control_details(card)
        self.assertNotIn("private-customer-control", json.dumps(projected))
        self.assertTrue(all(row["status"] == "not_reported" for row in projected))

    def test_inspection_and_pages_urls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            inspected = MODULE.inspect_scorecard(source)
            self.assertEqual(inspected["subject_revision"], REVISION)
            self.assertEqual(inspected["status"], "GREEN")
            self.assertTrue(all(row["status"] == "not_reported" for row in inspected["controls"]))
            self.assertEqual(
                MODULE.pages_base_url("owner/repo"), "https://owner.github.io/repo/"
            )
            self.assertEqual(
                MODULE.pages_base_url("owner/owner.github.io"),
                "https://owner.github.io/",
            )

    def test_cli_inspection_and_fail_closed_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            inspection = root / "inspection.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--inspect-output",
                    str(inspection),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(inspection.read_text())["subject_revision"], REVISION
            )

            failed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--output-dir",
                    str(root / "out"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("ERROR", failed.stderr)

    def test_cli_normalizes_unhashable_enum_types_to_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root, {**scorecard(), "status": []})
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--inspect-output",
                    str(root / "inspection.json"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("ERROR", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_backup_cleanup_failure_does_not_undo_committed_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "published"
            output.mkdir()
            (output / "old.txt").write_text("old", encoding="utf-8")
            temporary = root / "temporary"
            temporary.mkdir()
            (temporary / "new.txt").write_text("new", encoding="utf-8")

            with mock.patch.object(
                MODULE.shutil, "rmtree", side_effect=OSError("cleanup failed")
            ):
                MODULE._replace_directory(temporary, output)

            self.assertEqual((output / "new.txt").read_text(encoding="utf-8"), "new")
            self.assertFalse((output / "old.txt").exists())

    def test_deep_json_is_normalized_to_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            json_path = next(source.glob("*.json"))
            json_path.write_text(
                '{"nested":' * 1_500 + "null" + "}" * 1_500, encoding="utf-8"
            )
            output = root / "published"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_text("unchanged", encoding="utf-8")

            with self.assertRaises(ValueError):
                self.render(source, output)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--inspect-output",
                    str(root / "inspection.json"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("ERROR", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_timestamp_overflow_is_normalized_to_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            output = root / "published"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            invalid_timestamp = "0001-01-01T00:00:00+23:59"

            with self.assertRaises(ValueError):
                self.render(source, output, source_run_created_at=invalid_timestamp)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--output-dir",
                    str(output),
                    "--repository",
                    "owner/repo",
                    "--run-id",
                    "12345",
                    "--run-attempt",
                    "2",
                    "--run-url",
                    RUN_URL,
                    "--source-run-created-at",
                    invalid_timestamp,
                    "--expected-revision",
                    REVISION,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("ERROR", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_output_filesystem_failure_is_a_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            parent_file = root / "not-a-directory"
            parent_file.write_text("file", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--output-dir",
                    str(parent_file / "published"),
                    "--repository",
                    "owner/repo",
                    "--run-id",
                    "12345",
                    "--run-attempt",
                    "2",
                    "--run-url",
                    RUN_URL,
                    "--source-run-created-at",
                    CREATED_AT,
                    "--expected-revision",
                    REVISION,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 3)
            self.assertIn("ERROR runtime", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_existing_output_file_is_a_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            output = root / "published"
            output.write_text("consumer file", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-dir",
                    str(source),
                    "--output-dir",
                    str(output),
                    "--repository",
                    "owner/repo",
                    "--run-id",
                    "12345",
                    "--run-attempt",
                    "2",
                    "--run-url",
                    RUN_URL,
                    "--source-run-created-at",
                    CREATED_AT,
                    "--expected-revision",
                    REVISION,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 3)
            self.assertIn("ERROR runtime", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
