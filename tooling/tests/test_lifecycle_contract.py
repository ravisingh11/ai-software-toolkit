"""Negative tests for the independently validated lifecycle boundary."""
import copy
import hashlib
import unittest

from tooling.lifecycle_contract import PAIRS, canonical_bytes, validate_receipt


def fixture():
    head, base, workflow = 'a' * 40, 'b' * 40, 'c' * 40
    config = dict(version=1, scope='verification', build_network='none', dockerfile='examples/lifecycle/Dockerfile',
                  context='.', iac_paths=['examples/lifecycle/Dockerfile'], port=8080,
                  health_path='/health', soak_seconds=10, max_latency_ms=2000,
                  max_image_bytes=2147483648, health_revision_key='revision',
                  required_headers={'X-Content-Type-Options': 'nosniff'},
                  negative_probes=[{'path': '/missing', 'status': 404}])
    config_sha = 'sha256:' + hashlib.sha256(canonical_bytes(config)).hexdigest()
    snapshot = dict(version=1, repository='owner/repo', head_sha=head, run_id=12,
                    run_attempt=1, config_sha=config_sha, image_id='sha256:' + 'd' * 64,
                    container_id='e' * 64, target='http://proof-target:8080/health',
                    security=dict(user='65532:65532', read_only=True, network_internal=True,
                                  privileged=False, cap_drop=['ALL'], memory_bytes=536870912,
                                  nano_cpus=1000000000, pids_limit=128, no_new_privileges=True),
                    probes=dict(requests=1, errors=0, max_latency_ms=10, observed_revision=head),
                    soak=dict(duration_seconds=10, requests=10, errors=0, max_latency_ms=10),
                    resource_observations=[dict(cpu_percent='1.00%',memory_usage='4MiB / 512MiB',pids=1)] * 2,
                    final_state=dict(running=True,image_id='sha256:'+'d'*64,container_id='e'*64,security_unchanged=True))
    digest = 'sha256:' + 'f' * 64
    snapshot_digest = 'sha256:' + hashlib.sha256(canonical_bytes(snapshot)).hexdigest()
    docs = {}
    for key, subject, revision in [('git_commit', 'git-commit', head), ('artifact', 'artifact', digest),
                                   ('environment', 'environment', snapshot_digest)]:
        docs[key] = dict(version=2, subject=dict(type=subject, revision=revision), results={
            control: {provider: dict(producer=provider, status='passed', evidence=['actual report'])}
            for control, (provider, kind) in PAIRS.items() if kind == subject})
    receipt = dict(version=1, repository='owner/repo', pull_request_number=3, head_sha=head,
                   base_sha=base, run_id=12, run_attempt=1, workflow_sha=workflow,
                   config_sha=config_sha, artifact=dict(kind='verification-fixture', digest=digest,
                   source_revision=head, artifact_id=25, artifact_name='proof-lifecycle-image-12-1',
                   archive_digest='sha256:' + '9' * 64), environment=dict(scope='verification',
                   snapshot_digest=snapshot_digest, source_revision=head, artifact_digest=digest,
                   snapshot=snapshot), documents=docs)
    return receipt, config


class ReceiptTests(unittest.TestCase):
    def test_accepts_complete_bound_documents(self):
        receipt, config = fixture()
        self.assertEqual(validate_receipt(receipt, config), receipt)

    def test_rejects_substitution_and_unknown_fields(self):
        receipt, config = fixture()
        mutations = [lambda r: r.update(extra=True), lambda r: r.update(run_attempt=2),
                     lambda r: r.update(run_id=True), lambda r: r['artifact'].update(kind='release'),
                     lambda r: r['environment'].update(scope='production'),
                     lambda r: r['environment'].update(artifact_digest='sha256:' + '0' * 64),
                     lambda r: r['environment']['snapshot'].update(head_sha='0' * 40),
                     lambda r: r['documents']['artifact']['subject'].update(revision=r['head_sha']),
                     lambda r: r['documents']['artifact']['results'].update({'iac-misconfiguration': {
                         'trivy-iac-config': dict(producer='wrong subject', status='passed', evidence=['x'])}}),
                     lambda r: r['documents']['artifact']['results']['artifact-sbom'].update(evil={}),
                     lambda r: r['documents']['git_commit']['results'].clear(),
                     lambda r: r['environment']['snapshot']['security'].update(privileged=True)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = copy.deepcopy(receipt)
                mutate(changed)
                with self.assertRaises(ValueError):
                    validate_receipt(changed, config)

    def test_failure_is_valid_evidence_but_empty_success_is_not(self):
        receipt, config = fixture()
        result = receipt['documents']['artifact']['results']['artifact-sbom']['trivy-artifact-sbom']
        result.update(status='failed')
        validate_receipt(receipt, config)
        result['evidence'] = []
        with self.assertRaises(ValueError):
            validate_receipt(receipt, config)


class ConfigurationTests(unittest.TestCase):
    def test_duplicate_and_nonfinite_json_rejected(self):
        from tooling.lifecycle_contract import strict_json
        for raw in [b'{"key":1,"key":2}', b'{"key":NaN}', b'[]']:
            with self.assertRaises(ValueError):
                strict_json(raw)

    def test_config_rejects_unsafe_targets_and_incomplete_runtime_expectations(self):
        from tooling.lifecycle_contract import validate_config
        _, config = fixture()
        for field, value in [('dockerfile', '../secret'), ('context', '/tmp'), ('iac_paths', []),
                             ('scope', 'production'), ('build_network', 'host'), ('port', True), ('health_path', '//../admin'),
                             ('required_headers', {}), ('required_headers', {'Bad\nHeader': 'x'}),
                             ('negative_probes', []), ('negative_probes', [{'path': 'http://evil', 'status': 200}]),
                             ('health_revision_key', '../revision')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_config({**config, field: value})


class ObservationTests(unittest.TestCase):
    def test_measurements_cannot_claim_pass_despite_observed_failure(self):
        from tooling.lifecycle_contract import digest
        receipt, config = fixture()
        mutations = [lambda s: s['probes'].update(errors=1),
                     lambda s: s['probes'].update(observed_revision='0' * 40),
                     lambda s: s['soak'].update(max_latency_ms=config['max_latency_ms'] + 1),
                     lambda s: s['soak'].update(requests=1),
                     lambda s: s['soak'].update(duration_seconds=1),
                     lambda s: s['probes'].update(max_latency_ms=float('inf')),
                     lambda s: s['final_state'].update(running=False),
                     lambda s: s['final_state'].update(image_id='sha256:' + '0' * 64)]
        for mutation in mutations:
            changed = copy.deepcopy(receipt)
            mutation(changed['environment']['snapshot'])
            # Nonfinite observations cannot even be canonically hashed.
            try:
                changed['environment']['snapshot_digest'] = digest(changed['environment']['snapshot'])
            except ValueError:
                pass
            changed['documents']['environment']['subject']['revision'] = changed['environment']['snapshot_digest']
            with self.assertRaises(ValueError):
                validate_receipt(changed, config)

    def test_honest_failed_runtime_observations_are_preserved(self):
        from tooling.lifecycle_contract import digest
        receipt, config = fixture()
        receipt['environment']['snapshot']['probes']['observed_revision'] = None
        receipt['environment']['snapshot']['probes']['errors'] = 1
        receipt['environment']['snapshot']['soak']['duration_seconds'] = 1
        receipt['environment']['snapshot_digest'] = digest(receipt['environment']['snapshot'])
        receipt['documents']['environment']['subject']['revision'] = receipt['environment']['snapshot_digest']
        for control in ['runtime-assurance', 'runtime-soak']:
            receipt['documents']['environment']['results'][control][PAIRS[control][0]]['status'] = 'failed'
        validate_receipt(receipt, config)
