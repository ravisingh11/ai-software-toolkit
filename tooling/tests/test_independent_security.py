from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tooling import prepare_release_attestation as provenance
from tooling import run_trivy as trivy


class TrivyReportsTests(unittest.TestCase):
    def test_real_inventory_can_pass_but_high_findings_fail(self):
        report = {"SchemaVersion": 2, "Results": [{"Target": "requirements.txt", "Class": "lang-pkgs",
                  "Type": "pip", "Packages": [{"Name": "example"}], "Vulnerabilities": []}]}
        self.assertEqual(trivy.inspect_report(report, "dependencies")["status"], "passed")
        report["Results"][0]["Vulnerabilities"] = [{"Severity": "HIGH"}]
        self.assertEqual(trivy.inspect_report(report, "dependencies")["status"], "failed")

    def test_empty_incomplete_and_malformed_reports_cannot_pass(self):
        for report in (None, {}, {"SchemaVersion": 2, "Results": []},
                       {"SchemaVersion": 2, "Results": [], "Error": "database unavailable"},
                       {"SchemaVersion": 2, "Results": ["malformed"]},
                       {"SchemaVersion": 2, "Results": [{"Target": "x", "Class": "lang-pkgs", "Type": "pip"}]}):
            with self.subTest(report=report), self.assertRaises(ValueError):
                trivy.inspect_report(report, "dependencies")

    def test_iac_requires_completed_rules_and_matching_failures(self):
        report = {"SchemaVersion": 2, "Results": [{"Target": "Dockerfile", "Class": "config", "Type": "dockerfile",
                  "MisconfSummary": {"Successes": 2, "Failures": 1},
                  "Misconfigurations": [{"Severity": "CRITICAL", "Status": "FAIL"}]}]}
        self.assertEqual(trivy.inspect_report(report, "iac")["status"], "failed")
        report["Results"][0]["Misconfigurations"] = []
        with self.assertRaises(ValueError):
            trivy.inspect_report(report, "iac")

    def test_paths_cannot_escape_or_scan_linked_subtrees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            with self.assertRaises(ValueError):
                trivy.target_path(root, "..")
            (root / "link").symlink_to(Path(directory))
            with self.assertRaises(ValueError):
                trivy.target_path(root, ".")

    def test_scanner_results_control_exit_status_and_preserve_reports(self):
        version = {"Version": "0.76.0", "VulnerabilityDB": {"UpdatedAt": datetime.now(timezone.utc).isoformat()}}
        for high in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                source.mkdir()
                (source / "requirements.txt").write_text("example==1\n")
                output = root / "reports"
                report = {"SchemaVersion": 2, "Results": [{"Target": "requirements.txt", "Class": "lang-pkgs", "Type": "pip",
                          "Packages": [{"Name": "example"}], "Vulnerabilities": [{"Severity": "HIGH"}] if high else []}]}
                def scan(command, **kwargs):
                    self.assertNotIn("--ignore-unfixed=true", command)
                    self.assertEqual(command[command.index("--ignorefile") + 1], "")
                    Path(command[command.index("--output") + 1]).write_text(json.dumps(report))
                with mock.patch.object(trivy.subprocess, "run", side_effect=scan), \
                        mock.patch.object(trivy.subprocess, "check_output", return_value=json.dumps(version).encode()):
                    self.assertEqual(trivy.run_scan("dependencies", ".", source, output), int(high))
                self.assertEqual(json.loads((output / "summary.json").read_text())["status"], "failed" if high else "passed")
                self.assertTrue((output / "report.json").is_file())

    def test_unpinned_images_and_wrong_tool_versions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                trivy.run_scan("image", "example/app:latest", root, root / "unpinned")
            with mock.patch.object(trivy.subprocess, "check_output", return_value=b'{"Version":"different"}'), self.assertRaises(ValueError):
                trivy.run_scan("image", "example/app@sha256:" + "a" * 64, root, root / "wrong-tool")


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"exact published bytes"
        self.ref = {"type": "commit", "sha": "a" * 40}
        self.release = {"id": 123, "draft": False, "tag_name": "v1", "updated_at": "stable",
                        "assets": [{"id": 456, "name": "app.zip", "size": len(self.payload),
                                    "digest": "sha256:" + hashlib.sha256(self.payload).hexdigest(), "download_count": 0}]}
        self.release_reads = 0

    def api(self, path):
        if "/releases/tags/" in path:
            self.release_reads += 1
            result = copy.deepcopy(self.release)
            result["assets"][0]["download_count"] = self.release_reads
            return result
        if "/git/ref/" in path:
            return {"object": self.ref}
        raise AssertionError(path)

    def download(self, command, **kwargs):
        self.assertIn("Accept: application/octet-stream", command)
        kwargs["stdout"].write(self.payload)

    def test_exact_assets_and_predicate_without_false_build_claim(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(provenance, "api", side_effect=self.api), \
                mock.patch.object(provenance.subprocess, "run", side_effect=self.download):
            root = Path(directory) / "verification"
            result = provenance.prepare("owner/repo", "v1", "*.zip", root)
            self.assertEqual((root / "assets/app.zip").read_bytes(), self.payload)
            self.assertEqual(result["source_commit"], "a" * 40)
            self.assertEqual(result["kind"], "release-artifact-verification")
            self.assertIn("original build execution is not asserted", result["scope"])
            self.assertTrue((root / "predicate.json").is_file())

    def test_digest_mismatch_and_unsafe_names_never_produce_predicate(self):
        for name, digest in (("../outside", self.release["assets"][0]["digest"]), ("app.zip", "sha256:" + "b" * 64)):
            with tempfile.TemporaryDirectory() as directory, mock.patch.object(provenance, "api", side_effect=self.api), \
                    mock.patch.object(provenance.subprocess, "run", side_effect=self.download):
                self.release["assets"][0].update(name=name, digest=digest)
                root = Path(directory) / "verification"
                with self.assertRaises(ValueError):
                    provenance.prepare("owner/repo", "v1", "*", root)
                self.assertFalse((root / "predicate.json").exists())
                self.assertFalse((root / "outside").exists())

    def test_missing_assets_and_drafts_are_rejected(self):
        for pattern, draft in (("absent*", False), ("*", True)):
            self.release["draft"] = draft
            with tempfile.TemporaryDirectory() as directory, mock.patch.object(provenance, "api", side_effect=self.api):
                with self.assertRaises(ValueError):
                    provenance.prepare("owner/repo", "v1", pattern, Path(directory) / "verification")

    def test_changed_tag_is_rejected_after_download(self):
        count = 0
        def changing(path):
            nonlocal count
            if "/git/ref/" in path:
                count += 1
                return {"object": {"type": "commit", "sha": ("a" if count == 1 else "b") * 40}}
            return self.api(path)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(provenance, "api", side_effect=changing), \
                mock.patch.object(provenance.subprocess, "run", side_effect=self.download):
            root = Path(directory) / "verification"
            with self.assertRaises(ValueError):
                provenance.prepare("owner/repo", "v1", "*", root)
            self.assertFalse((root / "predicate.json").exists())


if __name__ == "__main__":
    unittest.main()
