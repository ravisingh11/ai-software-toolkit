from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "validate_pr_metadata.py"
SPEC = importlib.util.spec_from_file_location("validate_pr_metadata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def payload(**overrides) -> dict:
    pull_request = {
        "number": 42,
        "title": "ENG-123 Add migration proof",
        "body": "## Summary\nSafe migration.\n\n## Testing\nValidated.",
        "updated_at": "2026-08-31T12:00:00Z",
        "head": {"sha": "abc123"},
    }
    pull_request.update(overrides)
    return {"repository": {"full_name": "owner/repo"}, "pull_request": pull_request}


class PullRequestMetadataTests(unittest.TestCase):
    def test_fingerprint_changes_when_mutable_metadata_changes(self) -> None:
        first = MODULE.pull_request_revision(payload())
        second = MODULE.pull_request_revision(payload(title="ENG-124 Revised title"))

        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(first, second)

    def test_default_contract_requires_a_nonempty_title(self) -> None:
        config = {"version": 2, "title_pattern": ".+", "required_body_markers": []}

        self.assertEqual(MODULE.validate_metadata(payload(), config)["status"], "passed")
        failed = MODULE.validate_metadata(payload(title="   "), config)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("title", failed["evidence"][0].lower())

    def test_configured_title_pattern_and_body_markers_are_checked(self) -> None:
        config = {
            "version": 2,
            "title_pattern": r"^ENG-[0-9]+ ",
            "required_body_markers": ["## Summary", "## Testing"],
        }

        failed = MODULE.validate_metadata(
            payload(title="Add feature", body="## Summary\nMissing testing section"),
            config,
        )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(len(failed["evidence"]), 2)

    def test_detail_reports_counts_without_pull_request_text(self) -> None:
        config = {
            "version": 2,
            "title_pattern": r"^ENG-[0-9]+ ",
            "required_body_markers": ["## Summary", "## Testing", "## Rollback"],
        }

        passed = MODULE.validate_metadata(
            payload(body="## Summary\n## Testing\n## Rollback"), config
        )
        failed = MODULE.validate_metadata(payload(title="Add feature"), config)

        self.assertEqual(
            passed["pr_metadata"],
            {"version": 1, "title_matches": True, "required_sections": 3, "missing_sections": 0},
        )
        self.assertEqual(
            failed["pr_metadata"],
            {"version": 1, "title_matches": False, "required_sections": 3, "missing_sections": 1},
        )
        serialized = json.dumps(failed["pr_metadata"])
        for private in ("Add feature", "Summary", "Rollback", "migration"):
            self.assertNotIn(private, serialized)

    def test_write_evidence_uses_pull_request_subject(self) -> None:
        event = payload()
        revision = MODULE.pull_request_revision(event)
        result = MODULE.validate_metadata(
            event,
            {"version": 2, "title_pattern": ".+", "required_body_markers": []},
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "evidence.json"
            MODULE.write_evidence(destination, revision, result)
            evidence = json.loads(destination.read_text(encoding="utf-8"))

        self.assertEqual(
            evidence["subject"], {"type": "pull-request", "revision": revision}
        )
        self.assertEqual(
            evidence["results"]["pr-metadata"]["repository-pr-metadata"]["status"],
            "passed",
        )


if __name__ == "__main__":
    unittest.main()
