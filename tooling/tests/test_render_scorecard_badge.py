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
                    "guardrails-badge.svg",
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
                for phrase in ("PR Size · Files &amp; LOC", "Advisory", "does not block", "Counted files", "Excluded", "Added + deleted lines"):
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
            self.assertIn("Enforced · exceeding a limit blocks", (output / "index.html").read_text())

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
                    f"{status} {count}", (output / "guardrails-badge.svg").read_text()
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

    def test_inspection_and_pages_urls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_source(root)
            inspected = MODULE.inspect_scorecard(source)
            self.assertEqual(inspected["subject_revision"], REVISION)
            self.assertEqual(inspected["status"], "GREEN")
            self.assertNotIn("controls", inspected)
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
