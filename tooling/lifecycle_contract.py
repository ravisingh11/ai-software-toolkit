"""Strict receipt contract shared by lifecycle producers and trusted collection.

Validation establishes structure and subject binding, not authenticity. Only the
collector may accept a receipt after independently verifying its signed bytes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

PAIRS = {
    'iac-misconfiguration': ('trivy-iac-config', 'git-commit'),
    'container-vulnerability': ('trivy-container-image', 'artifact'),
    'artifact-sbom': ('trivy-artifact-sbom', 'artifact'),
    'artifact-vulnerability': ('trivy-artifact-sbom-scan', 'artifact'),
    'artifact-provenance': ('github-artifact-attestations', 'artifact'),
    'deployment-policy': ('repository-deployment-policy', 'environment'),
    'dynamic-application-security': ('zap-baseline-local', 'environment'),
    'runtime-assurance': ('repository-runtime-assurance', 'environment'),
    'runtime-soak': ('repository-soak', 'environment'),
}
WORKFLOW_PATH = '.github/workflows/lifecycle-verification.yml'
CONFIG_PATH = '.proof/lifecycle.json'
MAX_RECEIPT_BYTES = 128_000
MAX_ARCHIVE_BYTES = 256_000
SHA = re.compile(r'[0-9a-f]{40}')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
SECURITY = dict(user='65532:65532', read_only=True, network_internal=True,
                privileged=False, cap_drop=['ALL'], memory_bytes=536870912,
                nano_cpus=1000000000, pids_limit=128, no_new_privileges=True)


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def exact(value: Any, keys: set[str], name: str) -> None:
    require(isinstance(value, dict) and set(value) == keys, f'{name} has missing or unsupported fields')


def positive(value: Any) -> bool:
    return type(value) is int and value > 0


def matches(pattern: re.Pattern, value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


def digest(value: Any) -> str:
    return 'sha256:' + hashlib.sha256(canonical_bytes(value)).hexdigest()


def strict_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite JSON number')
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    require(isinstance(value, dict), 'JSON root must be an object')
    return value


def safe_path(value: Any, allow_dot: bool = False) -> bool:
    return isinstance(value, str) and (value == '.' and allow_dot or bool(value)
        and not value.startswith('/') and '\\' not in value
        and all(part not in {'', '.', '..'} for part in value.split('/')))


def validate_config(config: dict) -> dict:
    exact(config, {'version', 'scope', 'dockerfile', 'context', 'iac_paths', 'port', 'health_path',
                   'soak_seconds', 'max_latency_ms', 'max_image_bytes', 'health_revision_key',
                   'required_headers', 'negative_probes', 'build_network'}, 'Lifecycle configuration')
    require(type(config['version']) is int and config['version'] == 1, 'Unsupported configuration version')
    require(config['scope'] == 'verification', 'Only verification scope is implemented')
    require(config['build_network'] in {'none', 'default'}, 'Unsupported build network')
    require(safe_path(config['dockerfile']) and config['context'] == '.', 'Unsafe build path')
    paths = config['iac_paths']
    require(isinstance(paths, list) and 0 < len(paths) <= 20 and all(safe_path(p) for p in paths)
            and len(set(paths)) == len(paths), 'IaC paths must be nonempty and unique')
    require(positive(config['port']) and 1024 <= config['port'] <= 65535, 'Invalid target port')
    require(isinstance(config['health_path'], str)
            and re.fullmatch(r'/[A-Za-z0-9_/-]*', config['health_path'])
            and '..' not in config['health_path'], 'Invalid health path')
    for key, minimum, limit in [('soak_seconds', 10, 120), ('max_latency_ms', 1, 10000), ('max_image_bytes', 1024, 2147483648)]:
        require(positive(config[key]) and minimum <= config[key] <= limit, f'Invalid {key}')
    require(isinstance(config['health_revision_key'], str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', config['health_revision_key']), 'Invalid revision key')
    headers = config['required_headers']
    require(isinstance(headers, dict) and 0 < len(headers) <= 10, 'Required security headers missing')
    for name, value in headers.items():
        require(isinstance(name, str) and re.fullmatch(r'[A-Za-z-]{1,80}', name)
                and isinstance(value, str) and 0 < len(value) <= 256 and '\n' not in value and '\r' not in value, 'Invalid security header')
    probes = config['negative_probes']
    require(isinstance(probes, list) and 0 < len(probes) <= 10, 'Negative probes missing')
    for probe in probes:
        exact(probe, {'path', 'status'}, 'Negative probe')
        require(isinstance(probe['path'], str) and re.fullmatch(r'/[A-Za-z0-9/_-]*', probe['path'])
                and type(probe['status']) is int and 400 <= probe['status'] <= 499, 'Invalid negative probe')
    return config


def validate_result(result: Any) -> None:
    require(isinstance(result, dict) and {'producer', 'status'} <= set(result)
            and set(result) <= {'producer', 'status', 'evidence', 'reason', 'measurements'}, 'Malformed result')
    require(isinstance(result['producer'], str) and 0 < len(result['producer'].strip()) <= 200,
            'Missing producer identity')
    require(result['status'] in {'passed', 'failed', 'blocked', 'not_run'}, 'Invalid result status')
    if 'evidence' in result:
        require(isinstance(result['evidence'], list) and 0 < len(result['evidence']) <= 20
                and all(isinstance(x, str) and 0 < len(x.strip()) <= 1000 for x in result['evidence']),
                'Invalid evidence records')
    if 'reason' in result:
        require(isinstance(result['reason'], str) and 0 < len(result['reason'].strip()) <= 1000,
                'Invalid missing evidence reason')
    require(('evidence' if result['status'] in {'passed', 'failed'} else 'reason') in result,
            'Result lacks evidence or missing reason')
    # Measurements have a separate central schema; lifecycle producers use bounded
    # evidence records until that schema defines a lifecycle-specific measurement.
    require('measurements' not in result, 'Unsupported lifecycle measurements')


def validate_document(document: Any, subject: str, revision: str) -> None:
    exact(document, {'version', 'subject', 'results'}, 'Evidence document')
    require(type(document['version']) is int and document['version'] == 2, 'Unsupported evidence version')
    require(document['subject'] == {'type': subject, 'revision': revision}, 'Evidence subject mismatch')
    expected = {control: provider for control, (provider, kind) in PAIRS.items() if kind == subject}
    exact(document['results'], set(expected), 'Evidence controls')
    for control, provider in expected.items():
        exact(document['results'][control], {provider}, 'Evidence providers')
        validate_result(document['results'][control][provider])


def validate_receipt(receipt: dict, config: dict) -> dict:
    validate_config(config)
    exact(receipt, {'version', 'repository', 'pull_request_number', 'head_sha', 'base_sha', 'run_id',
                    'run_attempt', 'workflow_sha', 'config_sha', 'artifact', 'environment', 'documents'}, 'Receipt')
    require(type(receipt['version']) is int and receipt['version'] == 1, 'Unsupported receipt version')
    require(isinstance(receipt['repository'], str)
            and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', receipt['repository']), 'Invalid repository')
    require(all(positive(receipt[key]) for key in ['pull_request_number', 'run_id', 'run_attempt']),
            'Invalid receipt identity')
    require(receipt['run_attempt'] == 1, 'Rerun evidence is not accepted')
    require(all(matches(SHA, receipt[key]) for key in ['head_sha', 'base_sha', 'workflow_sha']), 'Invalid revision')
    require(matches(DIGEST, receipt['config_sha']), 'Invalid configuration digest')
    artifact = receipt['artifact']
    exact(artifact, {'kind', 'digest', 'source_revision', 'artifact_id', 'artifact_name', 'archive_digest'}, 'Artifact')
    require(artifact['kind'] == 'verification-fixture', 'Only verification fixtures are authorized')
    require(matches(DIGEST, artifact['digest']) and matches(DIGEST, artifact['archive_digest'])
            and positive(artifact['artifact_id']), 'Invalid artifact identity')
    require(artifact['source_revision'] == receipt['head_sha'], 'Artifact source mismatch')
    require(artifact['artifact_name'] == f"proof-lifecycle-image-{receipt['run_id']}-1", 'Artifact name mismatch')
    environment = receipt['environment']
    exact(environment, {'scope', 'snapshot_digest', 'source_revision', 'artifact_digest', 'snapshot'}, 'Environment')
    require(environment['scope'] == config['scope'] == 'verification', 'Environment scope mismatch')
    require(environment['source_revision'] == receipt['head_sha']
            and environment['artifact_digest'] == artifact['digest'], 'Environment artifact/source mismatch')
    snapshot = environment['snapshot']
    exact(snapshot, {'version', 'repository', 'head_sha', 'run_id', 'run_attempt', 'config_sha', 'image_id',
                     'container_id', 'target', 'security', 'probes', 'soak', 'resource_observations',
                     'final_state'}, 'Environment snapshot')
    require(type(snapshot['version']) is int and snapshot['version'] == 1, 'Unsupported snapshot version')
    require(all(snapshot[key] == receipt[key] for key in
                ['repository', 'head_sha', 'run_id', 'run_attempt', 'config_sha']), 'Snapshot identity mismatch')
    require(matches(DIGEST, snapshot['image_id']) and isinstance(snapshot['container_id'], str)
            and re.fullmatch(r'[0-9a-f]{64}', snapshot['container_id']), 'Missing actual Docker identity')
    require(snapshot['target'] == f"http://proof-target:{config['port']}{config['health_path']}", 'Target mismatch')
    require(canonical_bytes(snapshot['security']) == canonical_bytes(SECURITY), 'Environment isolation mismatch')
    require(positive(snapshot['run_id']) and type(snapshot['run_attempt']) is int, 'Invalid snapshot run identity')
    for key, fields in [('probes', {'requests', 'errors', 'max_latency_ms', 'observed_revision'}),
                        ('soak', {'duration_seconds', 'requests', 'errors', 'max_latency_ms'})]:
        values = snapshot[key]
        exact(values, fields, key)
        for number in fields - {'observed_revision'}:
            require(type(values[number]) in {int, float} and math.isfinite(values[number]) and values[number] >= 0, 'Invalid probe measurement')
        require(type(values['requests']) is int and type(values['errors']) is int
                and values['requests'] > 0 and values['errors'] <= values['requests'], 'Empty or inconsistent probes')
    require(snapshot['probes']['observed_revision'] is None or isinstance(snapshot['probes']['observed_revision'], str), 'Invalid observed revision')
    observations = snapshot['resource_observations']
    require(isinstance(observations, list) and len(observations) == 2, 'Missing before/after resource observations')
    for observation in observations:
        exact(observation, {'cpu_percent', 'memory_usage', 'pids'}, 'Resource observation')
        require(isinstance(observation['cpu_percent'], str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?%', observation['cpu_percent'])
                and isinstance(observation['memory_usage'], str) and 0 < len(observation['memory_usage']) <= 100
                and type(observation['pids']) is int and observation['pids'] >= 0, 'Malformed resource observation')
    final_state = snapshot['final_state']
    exact(final_state, {'running', 'image_id', 'container_id', 'security_unchanged'}, 'Final environment state')
    require(type(final_state['running']) is bool and type(final_state['security_unchanged']) is bool
            and matches(DIGEST, final_state['image_id']) and isinstance(final_state['container_id'], str)
            and re.fullmatch(r'[0-9a-f]{64}', final_state['container_id']), 'Malformed final state')
    require(environment['snapshot_digest'] == digest(snapshot), 'Snapshot digest mismatch')
    exact(receipt['documents'], {'git_commit', 'artifact', 'environment'}, 'Receipt documents')
    for key, kind, revision in [('git_commit', 'git-commit', receipt['head_sha']),
                                ('artifact', 'artifact', artifact['digest']),
                                ('environment', 'environment', environment['snapshot_digest'])]:
        validate_document(receipt['documents'][key], kind, revision)
    results = receipt['documents']['environment']['results']
    stable = (final_state['running'] and final_state['security_unchanged']
              and final_state['image_id'] == snapshot['image_id'] and final_state['container_id'] == snapshot['container_id'])
    for control in ['deployment-policy', 'runtime-assurance', 'runtime-soak']:
        provider = PAIRS[control][0]
        if results[control][provider]['status'] != 'passed':
            continue
        require(stable, 'Passed environment result conflicts with final identity or isolation')
        if control in {'runtime-assurance', 'runtime-soak'}:
            measurements = snapshot['soak'] if control == 'runtime-soak' else snapshot['probes']
            require(measurements['errors'] == 0 and measurements['max_latency_ms'] <= config['max_latency_ms']
                    and snapshot['probes']['observed_revision'] == receipt['head_sha'], 'Passed result conflicts with measured probes')
        if control == 'runtime-soak':
            require(snapshot['soak']['duration_seconds'] >= config['soak_seconds']
                    and snapshot['soak']['requests'] >= max(2, math.ceil(config['soak_seconds'] / 2)), 'Passed soak lacks sustained observations')
    return receipt


def validate_companions_manifest(manifest: dict, expected_head: str) -> dict:
    """Validate a locally trusted collector output before scorecard composition."""
    exact(manifest, {'version', 'provenance_verified', 'scope', 'context', 'documents'}, 'Companion envelope')
    require(type(manifest['version']) is int and manifest['version'] == 1
            and type(manifest['provenance_verified']) is bool, 'Invalid companion version/verification')
    require(manifest['scope'] == 'verification', 'Unsupported companion scope')
    context = manifest['context']
    exact(context, {'repository', 'pull_request_number', 'head_sha', 'base_sha', 'run_id', 'run_attempt',
                    'workflow_sha', 'reason', 'artifact_kind', 'environment_scope'}, 'Companion context')
    require(matches(SHA, expected_head) and context['head_sha'] == expected_head
            and matches(SHA, context['base_sha']), 'Companion PR revision mismatch')
    require(isinstance(context['repository'], str)
            and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', context['repository'])
            and positive(context['pull_request_number']), 'Invalid companion PR identity')
    require(context['artifact_kind'] == 'verification-fixture'
            and context['environment_scope'] == 'verification', 'Companion scope mismatch')
    require(isinstance(context['reason'], str) and 0 < len(context['reason']) <= 1000, 'Missing companion reason')
    if manifest['provenance_verified']:
        require(positive(context['run_id']) and type(context['run_attempt']) is int
                and context['run_attempt'] == 1 and matches(SHA, context['workflow_sha']), 'Invalid verified run')
    else:
        require(all(context[key] is None for key in ['run_id', 'run_attempt', 'workflow_sha']), 'Unverified run identity')
    docs = manifest['documents']
    exact(docs, {'git_commit', 'artifact', 'environment'}, 'Companion documents')
    for key, kind in [('git_commit', 'git-commit'), ('artifact', 'artifact'), ('environment', 'environment')]:
        revision = expected_head if key == 'git_commit' else (
            docs[key].get('subject', {}).get('revision') if isinstance(docs[key], dict) else None)
        if key != 'git_commit':
            require(matches(DIGEST, revision) if manifest['provenance_verified']
                    else revision == f'unavailable:{expected_head}', 'Companion subject is not bound')
        validate_document(docs[key], kind, revision)
        if not manifest['provenance_verified']:
            require(all(result['status'] == 'not_run' for providers in docs[key]['results'].values()
                        for result in providers.values()), 'Unverified evidence cannot claim execution')
    return manifest
