from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / 'workflows' / name).read_text())


class LifecycleWorkflowIntegrationTests(unittest.TestCase):
    def collector(self):
        return next(step for step in workflow('proof-scorecard.yml')['jobs']['scorecard']['steps']
                    if step.get('name') == 'Collect optional artifact and verification-environment evidence')

    def test_collection_requires_explicit_lifecycle_stage_as_well_as_opt_in(self):
        self.assertEqual(self.collector()['if'], "${{ github.event.pull_request != null && vars.PROOF_LIFECYCLE_ENABLED == 'true' && vars.PROOF_SCORECARD_STAGE == 'lifecycle' }}")
        self.assertEqual(workflow('proof-scorecard.yml')['permissions']['attestations'], 'read')

    def execute_collector(self, directory, script=None):
        root = Path(directory)
        collector = root / '.proof-trusted/.proof/collect_lifecycle_evidence.py'
        collector.parent.mkdir(parents=True)
        if script:
            collector.write_text(script)
        environment = {**os.environ, 'GH_TOKEN': 'unused-test-token',
                       'GITHUB_REPOSITORY': 'owner/repo', 'REVISION': 'a' * 40,
                       'BASE_REVISION': 'b' * 40, 'BASE_REF': 'main', 'PULL_REQUEST_NUMBER': '12',
                       'GITHUB_ENV': str(root / 'env'), 'GITHUB_STEP_SUMMARY': str(root / 'summary')}
        return subprocess.run(['bash', '-c', self.collector()['run']], cwd=root,
                              env=environment, capture_output=True, text=True)

    def test_old_trusted_runtime_does_not_execute_a_candidate_substitute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / '.proof-candidate/.proof/collect_lifecycle_evidence.py'
            candidate.parent.mkdir(parents=True)
            candidate.write_text("raise SystemExit('candidate must never execute')\n")
            completed = self.execute_collector(directory)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse((root / 'env').exists())
            self.assertIn('does not yet support', (root / 'summary').read_text())

    def test_trusted_collector_receives_exact_bindings_without_token_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            script = "import json,pathlib,sys\npathlib.Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\n"
            completed = self.execute_collector(directory, script)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            root = Path(directory)
            args = json.loads((root / 'arguments.json').read_text())
            values = dict(zip(args[::2], args[1::2]))
            self.assertEqual(values['--revision'], 'a' * 40)
            self.assertEqual(values['--trusted-base-revision'], 'b' * 40)
            self.assertEqual(values['--repo'], 'owner/repo')
            self.assertEqual(values['--pull-request-number'], '12')
            self.assertEqual(values['--trusted-workflow-ref'], 'refs/heads/main')
            self.assertEqual(values['--config'], '.proof-trusted/.proof/lifecycle.json')
            self.assertNotIn('unused-test-token', ' '.join(args))
            self.assertIn('PROOF_LIFECYCLE_EVIDENCE=', (root / 'env').read_text())

    def test_failed_trusted_collection_cannot_mark_a_manifest_available(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.execute_collector(directory, 'raise SystemExit(2)\n')
            self.assertEqual(completed.returncode, 2)
            self.assertFalse((Path(directory) / 'env').exists())

    def test_producer_workflow_is_manual_and_separates_signing_permissions(self):
        actual = workflow('lifecycle-verification.yml')
        triggers = actual.get('on', actual.get(True))
        self.assertEqual(set(triggers), {'workflow_dispatch'})
        self.assertEqual(actual['run-name'], 'Lifecycle PR #${{ inputs.pull-request-number }} @${{ inputs.revision }}')
        produce = actual['jobs']['produce']
        attest = actual['jobs']['attest']
        self.assertNotIn('id-token', produce['permissions'])
        self.assertNotIn('attestations', produce['permissions'])
        self.assertEqual(attest['permissions']['id-token'], 'write')
        self.assertEqual(attest['permissions']['attestations'], 'write')
        for step in attest['steps']:
            self.assertNotIn('docker run', step.get('run', ''))
            self.assertNotIn('candidate/', step.get('run', ''))


if __name__ == '__main__':
    unittest.main()
