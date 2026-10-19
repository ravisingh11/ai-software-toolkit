"""Adversarial platform/attestation tests for lifecycle evidence collection."""
import base64
import copy
import hashlib
import io
import json
import stat
import unittest
from unittest.mock import patch
import zipfile

from tooling import collect_lifecycle_evidence as collector
from tooling.lifecycle_contract import PAIRS, WORKFLOW_PATH, canonical_bytes, validate_companions_manifest
from tooling.tests.test_lifecycle_contract import fixture


def archive_for(raw, name='lifecycle-receipt.json', mode=stat.S_IFREG | 0o644):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(name)
        info.external_attr = mode << 16
        archive.writestr(info, raw)
    return output.getvalue()


def attestation(receipt, raw):
    return [{'verificationResult': {
        'verifiedTimestamps': [{'type':'Tlog','uri':'https://rekor.sigstore.dev','timestamp':'2026-01-01T00:00:00Z'}],
        'signature': {'certificate': {
            'sourceRepositoryURI': 'https://github.com/owner/repo',
            'sourceRepositoryDigest': receipt['workflow_sha'], 'sourceRepositoryRef': 'refs/heads/main',
            'buildSignerURI': f'https://github.com/owner/repo/{WORKFLOW_PATH}@refs/heads/main',
            'buildSignerDigest': receipt['workflow_sha'], 'runnerEnvironment': 'github-hosted',
            'runInvocationURI': 'https://github.com/owner/repo/actions/runs/12/attempts/1'}},
        'statement': {'predicateType': 'https://slsa.dev/provenance/v1', 'subject': [
            {'name': 'lifecycle-receipt.json', 'digest': {'sha256': hashlib.sha256(raw).hexdigest()}},
            {'name': 'image.tar', 'digest': {'sha256': receipt['artifact']['digest'][7:]}}]}}}]


class FakeGitHub:
    def __init__(self):
        self.receipt, self.config = fixture()
        self.receipt['documents']['artifact']['results']['artifact-provenance']['github-artifact-attestations'] = {
            'producer': 'GitHub artifact attestations', 'status': 'not_run', 'reason': 'Awaiting signature validation'}
        self.raw = canonical_bytes(self.receipt)
        self.archive_bytes = archive_for(self.raw)
        self.repository = {'id': 4, 'full_name': 'owner/repo', 'default_branch': 'main'}
        self.pr = {'number': 3, 'state': 'open', 'head': {'sha': 'a' * 40, 'repo': copy.deepcopy(self.repository)},
                   'base': {'sha': 'b' * 40, 'ref': 'main', 'repo': copy.deepcopy(self.repository)}}
        self.workflow = {'id': 6, 'name': 'Lifecycle Verification', 'path': WORKFLOW_PATH, 'state': 'active'}
        self.run = {'id': 12, 'display_title': 'Lifecycle PR #3 @' + 'a' * 40, 'head_sha': 'c' * 40,
                    'event': 'workflow_dispatch', 'path': WORKFLOW_PATH, 'workflow_id': 6,
                    'head_branch': 'main', 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
                    'repository': self.repository}
        self.runs = [self.run]
        self.artifacts = [
            {'id': 24, 'name': 'proof-lifecycle-evidence-12-1', 'expired': False,
             'size_in_bytes': len(self.archive_bytes), 'digest': 'sha256:' + hashlib.sha256(self.archive_bytes).hexdigest(),
             'workflow_run': {'id': 12, 'head_sha': 'c' * 40}},
            {'id': 25, 'name': 'proof-lifecycle-image-12-1', 'expired': False,
             'size_in_bytes': 5000, 'digest': 'sha256:' + '9' * 64,
             'workflow_run': {'id': 12, 'head_sha': 'c' * 40}}]
        self.trees = {}
        paths = set(collector.TRUSTED_PATHS + [self.config['dockerfile']] + self.config['iac_paths'])
        paths.add('examples/lifecycle')
        for revision in ['a' * 40, 'b' * 40, 'c' * 40]:
            config_raw = canonical_bytes(self.config)
            config_git_sha = hashlib.sha1(b'blob ' + str(len(config_raw)).encode() + b'\0' + config_raw).hexdigest()
            self.trees[revision] = {'truncated': False, 'tree': [
                {'path': path, 'sha': config_git_sha if path == collector.CONFIG_PATH else '8' * 40, 'type': 'tree' if path == 'examples/lifecycle' else 'blob',
                 'mode': '040000' if path == 'examples/lifecycle' else '100644'} for path in sorted(paths)]}
        self.provider_registry = {'providers': {provider: {'capabilities': [control], 'lifecycle': collector.LIFECYCLE_CONTRACT}
                                              for control, (provider, _) in PAIRS.items()}}
        self.archive_reads = 0
        self.after_download = None

    def archive(self, identity):
        if identity != 24:
            raise AssertionError('Collector attempted to download large image')
        self.archive_reads += 1
        if self.after_download:
            self.after_download(self)
        return self.archive_bytes

    def get(self, path):
        if path == '':
            return copy.deepcopy(self.repository)
        if path == '/pulls/3':
            return copy.deepcopy(self.pr)
        if path.startswith('/actions/workflows/') and not '/runs?' in path:
            return copy.deepcopy(self.workflow)
        if path.startswith('/actions/workflows/6/runs?'):
            return {'total_count': len(self.runs), 'workflow_runs': copy.deepcopy(self.runs)}
        if path.startswith('/compare/'):
            return {'status': 'ahead', 'merge_base_commit': {'sha': 'c' * 40}}
        if path.startswith('/git/trees/'):
            return copy.deepcopy(self.trees[path.split('/')[3].split('?')[0]])
        if path.startswith('/contents/'):
            raw = canonical_bytes(self.config)
            return {'type': 'file', 'encoding': 'base64', 'size': len(raw), 'content': base64.b64encode(raw).decode(),
                    'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
        if path.startswith('/actions/runs/12/artifacts?'):
            return {'total_count': len(self.artifacts), 'artifacts': copy.deepcopy(self.artifacts)}
        if path.startswith('/actions/artifacts/'):
            return copy.deepcopy(next(a for a in self.artifacts if a['id'] == int(path.split('/')[-1])))
        if path == '/actions/runs/12':
            return copy.deepcopy(self.run)
        raise AssertionError('Unexpected API: ' + path)

    def collect(self, attester=None):
        if attester is None:
            attester = lambda raw, receipt, repo, branch: collector.validate_attestation(
                attestation(receipt, raw), raw, receipt, repo, branch)
        return collector.collect('owner/repo', 3, 'a' * 40, 'b' * 40, 'refs/heads/main',
                                 self.config, self.provider_registry, self, attester)


class CollectorTests(unittest.TestCase):
    def test_valid_collection_is_subject_bound_and_signature_upgrades_only_provenance(self):
        client = FakeGitHub()
        result = client.collect()
        self.assertTrue(result['provenance_verified'], result['context']['reason'])
        self.assertEqual(client.archive_reads, 1)
        validate_companions_manifest(result, 'a' * 40)
        self.assertEqual(result['documents']['artifact']['results']['artifact-provenance']
                         ['github-artifact-attestations']['status'], 'passed')

    def test_stale_ambiguous_or_changed_platform_evidence_never_passes(self):
        mutations = [
            lambda c: c.pr['head'].update(sha='0' * 40),
            lambda c: c.pr.update(number=True),
            lambda c: c.pr.update(state='closed'),
            lambda c: c.pr['head']['repo'].update(full_name='fork/repo'),
            lambda c: c.pr['head']['repo'].update(id=99),
            lambda c: c.pr['head']['repo'].update(id=True),
            lambda c: c.pr['base'].update(ref='feature'),
            lambda c: c.pr['base'].update(sha='0' * 40),
            lambda c: c.run.update(head_sha='0' * 40),
            lambda c: c.run.update(run_attempt=2),
            lambda c: c.run.update(event='pull_request'),
            lambda c: c.run.update(head_branch='feature'),
            lambda c: c.run.update(conclusion='failure'),
            lambda c: c.runs.append({**c.run, 'id': 13}),
            lambda c: c.artifacts[0].update(expired=True),
            lambda c: c.artifacts[1].update(digest='sha256:' + '1' * 64),
            lambda c: c.artifacts[0].update(size_in_bytes=999999),
            lambda c: c.artifacts.append({**c.artifacts[0], 'id': 99}),
            lambda c: c.artifacts[1]['workflow_run'].update(id=13),
            lambda c: c.trees['a' * 40]['tree'][0].update(sha='0' * 40),
            lambda c: c.trees['b' * 40].update(truncated=True),
            lambda c: c.trees['c' * 40]['tree'][0].update(mode='120000'),
            lambda c: c.provider_registry['providers']['trivy-container-image'].update(lifecycle={}),
            lambda c: setattr(c, 'after_download', lambda d: d.artifacts[0].update(expired=True)),
            lambda c: setattr(c, 'after_download', lambda d: d.run.update(run_attempt=2)),
            lambda c: setattr(c, 'after_download', lambda d: d.pr['head'].update(sha='0' * 40)),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                client = FakeGitHub()
                mutate(client)
                result = client.collect()
                self.assertFalse(result['provenance_verified'])
                validate_companions_manifest(result, 'a' * 40)
                self.assertEqual(result['documents']['artifact']['subject']['revision'], 'unavailable:' + 'a' * 40)

    def test_api_denial_and_signature_failure_remain_visible(self):
        client = FakeGitHub()
        with patch.object(client, 'get', side_effect=OSError('API denied')):
            result = client.collect()
        self.assertIn('API denied', result['context']['reason'])
        def reject(*args):
            raise ValueError('Signature invalid')
        self.assertIn('Signature invalid', FakeGitHub().collect(reject)['context']['reason'])

    def test_archive_rejects_extra_symlink_traversal_and_oversize(self):
        for archive in [archive_for(b'{}', '../lifecycle-receipt.json'),
                        archive_for(b'{}', mode=stat.S_IFLNK | 0o777),
                        archive_for(b'x' * (collector.MAX_RECEIPT_BYTES + 1)), b'x' * (collector.MAX_ARCHIVE_BYTES + 1)]:
            with self.assertRaises((ValueError, zipfile.BadZipFile)):
                collector.receipt_bytes(archive)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zipped:
            zipped.writestr('lifecycle-receipt.json', '{}')
            zipped.writestr('raw-report.json', '{}')
        with self.assertRaises(ValueError):
            collector.receipt_bytes(buf.getvalue())

    def test_signature_must_jointly_bind_both_subjects_and_certified_run(self):
        receipt, _ = fixture()
        raw = canonical_bytes(receipt)
        valid = attestation(receipt, raw)
        collector.validate_attestation(valid, raw, receipt, 'owner/repo', 'main')
        mutations = [
            lambda value: value[0]['verificationResult']['signature']['certificate'].update(runInvocationURI='wrong-run'),
            lambda value: value[0]['verificationResult']['signature']['certificate'].update(sourceRepositoryDigest=receipt['head_sha']),
            lambda value: value[0]['verificationResult']['signature']['certificate'].update(runnerEnvironment='self-hosted'),
            lambda value: value[0]['verificationResult']['statement']['subject'].pop(),
            lambda value: value[0]['verificationResult']['statement']['subject'][1]['digest'].update(sha256='0' * 64),
            lambda value: value.append(copy.deepcopy(value[0])),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(valid)
            mutate(changed)
            with self.assertRaises(ValueError):
                collector.validate_attestation(changed, raw, receipt, 'owner/repo', 'main')
        separate = copy.deepcopy(valid) + copy.deepcopy(valid)
        separate[0]['verificationResult']['statement']['subject'].pop()
        separate[1]['verificationResult']['statement']['subject'].pop(0)
        with self.assertRaises(ValueError):
            collector.validate_attestation(separate, raw, receipt, 'owner/repo', 'main')

    def test_missing_manifest_cannot_smuggle_pass_or_change_subject(self):
        result = collector.missing_manifest('owner/repo', 3, 'a' * 40, 'b' * 40, 'No run')
        result['documents']['artifact']['results']['artifact-provenance']['github-artifact-attestations'].update(
            status='passed', evidence=['fake'])
        with self.assertRaises(ValueError):
            validate_companions_manifest(result, 'a' * 40)

    def test_gh_verification_uses_workflow_source_not_candidate_head(self):
        receipt, _ = fixture()
        raw = canonical_bytes(receipt)
        def run(command, stdout, stderr, **kwargs):
            self.assertEqual(command[command.index('--source-digest') + 1], receipt['workflow_sha'])
            self.assertEqual(command[command.index('--signer-digest') + 1], receipt['workflow_sha'])
            self.assertIn('--deny-self-hosted-runners', command)
            stdout.write(json.dumps(attestation(receipt, raw)).encode())
            class Result:
                returncode = 0
            return Result()
        with patch.object(collector.subprocess, 'run', side_effect=run):
            collector.verify_attestation(raw, receipt, 'owner/repo', 'main')


class BoundaryTests(unittest.TestCase):
    def test_paginated_enumeration_rejects_churn_incomplete_and_duplicates(self):
        client = FakeGitHub()
        records = [{'id': i + 1} for i in range(100)]
        for pages in [[{'total_count': 101, 'items': records}, {'total_count': 102, 'items': [{'id': 101}]}],
                      [{'total_count': 101, 'items': records}, {'total_count': 101, 'items': [{'id': 100}]}],
                      [{'total_count': 2, 'items': [{'id': 1}]}]]:
            with patch.object(client, 'get', side_effect=pages), self.assertRaises(ValueError):
                collector.enumerate_records(client, '/test', 'items')
        pages = [{'total_count': 1000, 'items': [{'id': page * 100 + i + 1} for i in range(100)]}
                 for page in range(10)]
        with patch.object(client, 'get', side_effect=pages), self.assertRaises(ValueError):
            collector.enumerate_records(client, '/test', 'items')

    def test_api_wrapper_and_archive_bound(self):
        client = collector.GitHub('owner/repo', 'token')
        with patch.object(collector.github, '_request', return_value={'id': 1}) as request:
            self.assertEqual(client.get('/test'), {'id': 1})
            request.assert_called_once_with('https://api.github.com/repos/owner/repo/test', 'token')
        with patch.object(collector.github, '_request_bytes', return_value=b'zip'):
            self.assertEqual(client.archive(2), b'zip')
        with patch.object(collector.github, '_request_bytes', return_value=b'x' * (collector.MAX_ARCHIVE_BYTES + 1)):
            with self.assertRaises(ValueError):
                client.archive(2)

    def test_command_line_writes_missing_and_verified_envelopes(self):
        import contextlib
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeGitHub()
            config = root / 'config.json'
            providers = root / 'providers.json'
            config.write_text(json.dumps(client.config))
            providers.write_text(json.dumps(client.provider_registry))
            args = ['collect', '--repo', 'owner/repo', '--pull-request-number', '3', '--revision', 'a' * 40,
                    '--trusted-base-revision', 'b' * 40, '--trusted-workflow-ref', 'refs/heads/main',
                    '--config', str(config), '--providers', str(providers), '--output-dir', str(root / 'output')]
            with patch('sys.argv', args), patch.object(collector, 'collect', return_value=client.collect()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 0)
            result = json.loads((root / 'output/lifecycle-companions.json').read_text())
            self.assertTrue(result['provenance_verified'])
            config.unlink()
            with patch('sys.argv', args), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 0)
            result = json.loads((root / 'output/lifecycle-companions.json').read_text())
            self.assertFalse(result['provenance_verified'])
            self.assertEqual(json.loads((root / 'output/lifecycle-git-evidence.json').read_text()),
                             result['documents']['git_commit'])

    def test_signature_malformed_entries_cannot_mask_valid_binding(self):
        receipt, _ = fixture()
        raw = canonical_bytes(receipt)
        for entry in [{}, {'verificationResult': {'signature': {'certificate': []}}},
                      {'verificationResult': {'signature': {'certificate': attestation(receipt, raw)[0]['verificationResult']['signature']['certificate']},
                                              'statement': {'predicateType': 'wrong', 'subject': []}}}]:
            with self.assertRaises(ValueError):
                collector.validate_attestation([entry], raw, receipt, 'owner/repo', 'main')

    def test_trusted_path_ancestors_and_unrelated_files(self):
        client = FakeGitHub()
        for tree in client.trees.values():
            tree['tree'].extend([{'path': '.proof', 'sha': '7' * 40, 'type': 'tree', 'mode': '040000'},
                                 {'path': 'README.md', 'sha': '6' * 40, 'type': 'blob', 'mode': '100644'}])
        self.assertTrue(client.collect()['provenance_verified'])
        client.trees['a' * 40]['tree'][-2]['mode'] = '120000'
        self.assertFalse(client.collect()['provenance_verified'])


class TimestampTests(unittest.TestCase):
    def test_unsigned_currenttime_or_missing_timestamps_rejected(self):
        receipt, _ = fixture()
        raw = canonical_bytes(receipt)
        for timestamps in [[], None, [{'type': 'CurrentTime', 'uri': '', 'timestamp': '2026-01-01T00:00:00Z'}],
                           [{'type': 'Tlog', 'uri': 'http://unsafe', 'timestamp': '2026-01-01T00:00:00Z'}],
                           [{'type': 'Tlog', 'uri': 'https://rekor.sigstore.dev', 'timestamp': '2026-01-01'}],
                           [{'type': 'Tlog', 'uri': 'https://rekor.sigstore.dev', 'timestamp': '2999-01-01T00:00:00Z'}]]:
            verified = attestation(receipt, raw)
            verified[0]['verificationResult']['verifiedTimestamps'] = timestamps
            with self.assertRaises(ValueError):
                collector.validate_attestation(verified, raw, receipt, 'owner/repo', 'main')


class BuildExclusionTests(unittest.TestCase):
    def test_modified_or_missing_dockerignore_cannot_reuse_trusted_build(self):
        for missing in [False, True]:
            client = FakeGitHub()
            tree = client.trees['a' * 40]['tree']
            item = next(row for row in tree if row['path'] == '.dockerignore')
            if missing:
                tree.remove(item)
            else:
                item['sha'] = '0' * 40
            result = client.collect()
            self.assertFalse(result['provenance_verified'])
            self.assertEqual(client.archive_reads, 0)
