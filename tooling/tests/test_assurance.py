from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assurance  # noqa: E402


class AssuranceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root / "payload"
        self.payload.mkdir()
        (self.payload / "deploy-config.json").write_text('{"name":"synthetic"}\n')
        (self.payload / "worker.js").write_text("export default {};\n")
        for path in self.payload.iterdir():
            path.chmod(0o644)
        self.manifest = {"version": 1, "kind": "package-manifest",
                         "source": {"repository": "https://example.invalid/project", "revision": "a" * 40, "tree": "b" * 40},
                         "build": {"tool": "fixture", "version": "1"},
                         "configuration": {"path": "deploy-config.json", "sha256": assurance.sha256_file(self.payload / "deploy-config.json")},
                         "files": [{"path": p.name, "sha256": assurance.sha256_file(p), "size": p.stat().st_size, "mode": "0644"} for p in sorted(self.payload.iterdir())]}
        evidence = self.root / "original.json"
        evidence.write_text('{"outcome":"success"}\n')
        self.receipt = {"version": 1, "kind": "checkpoint-receipt", "checkpoint": "pr",
                        "subject": {"type": "git-commit", "revision": "a" * 40},
                        "observed_at": "2026-01-01T00:00:00Z", "context": {"invocation": "pull_request:synchronize"},
                        "dependencies": {}, "results": [{"check": "unit-tests", "provider": "repository-unit-tests", "status": "passed", "evidence": ["original.json"]}],
                        "evidence_refs": [{"path": "original.json", "sha256": assurance.sha256_file(evidence), "size": evidence.stat().st_size}]}
        self.path = self.root / "receipt.json"

    def verify(self, expected=None):
        self.path.write_text(json.dumps(self.receipt))
        return assurance.verify_receipt(self.path, expected=expected, now=datetime(2026, 2, 1, tzinfo=timezone.utc))

    def test_complete_package_and_canonical_identity(self):
        result = assurance.verify_package(self.payload, self.manifest)
        self.assertTrue(result["valid"])
        self.assertFalse(result["authenticated_build_provenance"])
        self.assertEqual(result["package_digest"], hashlib.sha256(assurance.canonical(self.manifest)).hexdigest())
        reordered = {k: self.manifest[k] for k in reversed(self.manifest)}
        self.assertEqual(assurance.package_digest(reordered), result["package_digest"])

    def test_package_changed_missing_extra_mode_and_symlink_reject(self):
        path = self.payload / "worker.js"
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        with self.assertRaises(ValueError):
            assurance.verify_package(self.payload, self.manifest)
        path.write_bytes(original)
        path.chmod(0o755)
        with self.assertRaises(ValueError):
            assurance.verify_package(self.payload, self.manifest)
        path.chmod(0o644)
        extra = self.payload / "extra"
        extra.write_text("unexpected")
        with self.assertRaises(ValueError):
            assurance.verify_package(self.payload, self.manifest)
        extra.unlink()
        path.unlink()
        with self.assertRaises(ValueError):
            assurance.verify_package(self.payload, self.manifest)
        path.symlink_to(self.root / "original.json")
        with self.assertRaises(ValueError):
            assurance.verify_package(self.payload, self.manifest)

    def test_manifest_wrong_version_size_path_duplicate_configuration(self):
        mutations = [lambda m: m.update(version=2), lambda m: m["files"][0].update(size=True),
                     lambda m: m["files"][0].update(path="../outside"), lambda m: m["files"].append(m["files"][0]),
                     lambda m: m["configuration"].update(sha256="f" * 64),
                     lambda m: m["source"].update(repository="https://secret@example.invalid/repo"),
                     lambda m: m.update(publication_authorized=True)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                manifest = copy.deepcopy(self.manifest)
                mutation(manifest)
                with self.assertRaises(ValueError):
                    assurance.verify_package(self.payload, manifest)

    def test_receipt_retains_outcomes_and_never_authenticates_or_authorizes(self):
        original = copy.deepcopy(self.receipt)
        result = self.verify()
        self.assertTrue(result["all_reported_checks_passed"])
        self.assertFalse(result["authenticated_producer"])
        self.assertFalse(result["authorization_granted"])
        self.assertEqual(result["results"], original["results"])
        self.assertEqual(self.receipt, original)
        for status in ("failed", "blocked", "not_run"):
            self.receipt["results"][0] = {"check": "unit-tests", "provider": "repository-unit-tests", "status": status,
                                          **({"evidence": ["original.json"]} if status == "failed" else {"reason": "Producer unavailable or cancelled"})}
            result = self.verify()
            self.assertFalse(result["all_reported_checks_passed"])
            self.assertEqual(result["status_counts"][status], 1)

    def test_wrong_subject_base_metadata_configuration_and_provider_invalidate(self):
        for dependency in ("source_revision", "comparison_base", "pr_metadata_revision", "configuration_digest", "provider_digest", "index_tree"):
            with self.subTest(dependency=dependency):
                size = 40 if dependency in {"source_revision", "comparison_base", "index_tree"} else 64
                self.receipt["dependencies"] = {dependency: "a" * size}
                self.assertIn("unverified-dependency:" + dependency, self.verify()["invalidation_reasons"])
                self.assertFalse(self.verify({dependency: "b" * size})["applicable"])
                self.assertTrue(self.verify({dependency: "a" * size})["applicable"])
        self.receipt["dependencies"] = {}
        self.assertIn("subject-mismatch", self.verify({"subject": {"type": "artifact", "revision": "a" * 40}})["invalidation_reasons"])

    def test_metadata_edit_does_not_invalidate_separate_commit_receipt(self):
        self.receipt["dependencies"] = {"source_revision": "a" * 40}
        self.assertTrue(self.verify({"source_revision": "a" * 40})["all_reported_checks_passed"])
        metadata = copy.deepcopy(self.receipt)
        metadata["subject"] = {"type": "pull-request", "revision": "old-metadata"}
        self.receipt = metadata
        self.assertFalse(self.verify({"subject": {"type": "pull-request", "revision": "new-metadata"}, "source_revision": "a" * 40})["applicable"])

    def test_expiry_runtime_freshness_and_future_observation(self):
        self.receipt["checkpoint"] = "runtime"
        self.receipt["subject"] = {"type": "environment", "revision": "synthetic-version"}
        self.assertIn("freshness-unverified", self.verify()["invalidation_reasons"])
        self.receipt["expires_at"] = "2026-01-02T00:00:00Z"
        self.assertIn("expired-observation", self.verify()["invalidation_reasons"])
        self.receipt["expires_at"] = "2027-01-02T00:00:00Z"
        self.receipt["observed_at"] = "2027-01-01T00:00:00Z"
        self.assertIn("observation-in-future", self.verify()["invalidation_reasons"])

    def test_missing_or_changed_evidence_and_forged_authority_reject(self):
        (self.root / "original.json").write_text("different")
        with self.assertRaises(ValueError):
            self.verify()
        self.receipt["results"][0]["authority"] = "verified"
        with self.assertRaises(ValueError):
            assurance.validate_receipt(self.receipt)

    def test_unsupported_receipt_unbound_pass_relationship_and_skill_reject(self):
        for mutate in [lambda r: r.update(version=2), lambda r: r["results"][0].update(evidence=["missing.json"]),
                       lambda r: r.update(relationships=[{"relation": "merged", "subject": {"type": "git-commit", "revision": "b" * 40}, "evidence": "missing"}]),
                       lambda r: r.update(skills=[{"name": "local-skill", "origin": "local", "execution_evidence": "missing"}])]:
            value = copy.deepcopy(self.receipt)
            mutate(value)
            with self.assertRaises(ValueError):
                assurance.validate_receipt(value)

    def test_local_unversioned_skill_and_bound_handoff_are_attribution_only(self):
        self.receipt["skills"] = [{"name": "local-procedure", "origin": "local"}]
        self.receipt["relationships"] = [{"relation": "tested", "subject": {"type": "git-commit", "revision": "a" * 40}, "evidence": "original.json"}]
        self.assertEqual(self.verify()["skill_references"], self.receipt["skills"])
        self.assertFalse(self.verify()["authenticated_producer"])

    def test_duplicate_json_and_path_escaping_reject(self):
        self.path.write_text('{"version":1,"version":2}')
        with self.assertRaises(ValueError):
            assurance.read_document(self.path)
        for path in ("../escape", "/absolute", "a/../b", "a//b", "a\\b", "C:/bad", "."):
            with self.subTest(path=path), self.assertRaises(ValueError):
                assurance.relative_path(path)


if __name__ == "__main__":
    unittest.main()
