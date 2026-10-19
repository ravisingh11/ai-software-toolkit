from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tooling'))
SPEC = importlib.util.spec_from_file_location('lifecycle_scorecard', ROOT / 'tooling/proof_scorecard.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def manifest():
    from lifecycle_contract import PAIRS
    head = 'a' * 40
    documents = {}
    for key, kind in [('git_commit', 'git-commit'), ('artifact', 'artifact'), ('environment', 'environment')]:
        documents[key] = {'version': 2, 'subject': {'type': kind, 'revision': head if kind == 'git-commit' else 'unavailable:' + head},
                          'results': {control: {provider: {'producer': provider, 'status': 'not_run', 'reason': 'Missing verified run'}}
                                      for control, (provider, subject) in PAIRS.items() if subject == kind}}
    return {'version': 1, 'scope': 'verification', 'provenance_verified': False,
            'context': {'repository': 'owner/repo', 'pull_request_number': 1, 'head_sha': head, 'base_sha': 'b' * 40,
                        'run_id': None, 'run_attempt': None, 'workflow_sha': None, 'reason': 'Missing verified run',
                        'artifact_kind': 'verification-fixture', 'environment_scope': 'verification'}, 'documents': documents}


class LifecycleScorecardTests(unittest.TestCase):
    def test_missing_manifest_adds_release_companions_and_preserves_original(self):
        value = manifest()
        evidence = {'version': 2, 'subject': value['documents']['git_commit']['subject'], 'results': {'build': {'builder': {'status': 'passed'}}}}
        original = copy.deepcopy(evidence)
        merged, companions = MODULE.merge_lifecycle(evidence, value, 'a' * 40)
        self.assertEqual(evidence, original)
        self.assertEqual(merged['results']['build'], original['results']['build'])
        self.assertEqual([c[3] for c in companions], ['release', 'release'])
        self.assertTrue(all(c[1] == 'unavailable:' + 'a' * 40 for c in companions))

    def test_wrong_head_duplicate_and_forged_missing_pass_are_rejected(self):
        value = manifest()
        with self.assertRaises(ValueError):
            MODULE.merge_lifecycle(value['documents']['git_commit'], value, 'b' * 40)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            MODULE.merge_lifecycle(value['documents']['git_commit'], value, 'a' * 40)
        value['documents']['artifact']['results']['artifact-sbom']['trivy-artifact-sbom'] = {'status': 'passed', 'producer': 'forged', 'evidence': ['fake']}
        with self.assertRaises(ValueError):
            MODULE.merge_lifecycle({'version': 2, 'subject': value['documents']['git_commit']['subject'], 'results': {}}, value, 'a' * 40)
