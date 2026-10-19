#!/usr/bin/env python3
"""Import signed, exact-subject lifecycle evidence from a trusted manual workflow."""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any
from urllib.parse import quote, urlparse
import zipfile

try:
    from . import github_evidence as github
    from .lifecycle_contract import (
        CONFIG_PATH, DIGEST, MAX_ARCHIVE_BYTES, MAX_RECEIPT_BYTES, PAIRS, SHA, WORKFLOW_PATH,
        digest, matches, positive, require, strict_json, validate_companions_manifest,
        validate_config, validate_receipt,
    )
except ImportError:
    import github_evidence as github
    from lifecycle_contract import (
        CONFIG_PATH, DIGEST, MAX_ARCHIVE_BYTES, MAX_RECEIPT_BYTES, PAIRS, SHA, WORKFLOW_PATH,
        digest, matches, positive, require, strict_json, validate_companions_manifest,
        validate_config, validate_receipt,
    )

LIFECYCLE_CONTRACT = {'workflow': 'Lifecycle Verification', 'workflow_path': WORKFLOW_PATH,
                      'artifact_name_prefix': 'proof-lifecycle-evidence-',
                      'artifact_member': 'lifecycle-receipt.json'}
TRUSTED_PATHS = [WORKFLOW_PATH, CONFIG_PATH, '.dockerignore', '.proof/lifecycle_contract.py',
                 '.proof/lifecycle_producers.py', '.proof/collect_lifecycle_evidence.py']


class GitHub:
    def __init__(self, repo: str, token: str):
        self.api = f'https://api.github.com/repos/{repo}'
        self.token = token

    def get(self, path: str) -> Any:
        return github._request(self.api + path, self.token)

    def archive(self, artifact_id: int) -> bytes:
        content = github._request_bytes(f'{self.api}/actions/artifacts/{artifact_id}/zip', self.token)
        require(len(content) <= MAX_ARCHIVE_BYTES, 'Receipt archive exceeds limit')
        return content


def enumerate_records(client: GitHub, path: str, field: str) -> list[dict]:
    records, total = [], None
    for page in range(1, 11):
        data = client.get(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        require(isinstance(data, dict) and type(data.get('total_count')) is int
                and 0 <= data['total_count'] <= 1000, 'Invalid lifecycle enumeration count')
        if total is None:
            total = data['total_count']
        require(data['total_count'] == total, 'Lifecycle enumeration changed during pagination')
        batch = data.get(field)
        require(isinstance(batch, list) and len(batch) <= 100
                and all(isinstance(item, dict) and positive(item.get('id')) for item in batch),
                'Malformed lifecycle enumeration page')
        records.extend(batch)
        require(len({item['id'] for item in records}) == len(records), 'Duplicate lifecycle API identity')
        if len(batch) < 100:
            require(len(records) == total, 'Incomplete lifecycle enumeration')
            return records
    raise ValueError('Lifecycle enumeration exceeded page limit')


def receipt_bytes(archive: bytes) -> bytes:
    require(len(archive) <= MAX_ARCHIVE_BYTES, 'Oversized receipt archive')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        members = zipped.infolist()
        require(len(members) == 1, 'Receipt archive must contain exactly one file')
        member = members[0]
        mode = member.external_attr >> 16
        require(member.filename == 'lifecycle-receipt.json' and not member.is_dir()
                and not member.flag_bits & 1 and stat.S_IFMT(mode) in {0, stat.S_IFREG}
                and 0 < member.file_size <= MAX_RECEIPT_BYTES, 'Unsafe receipt archive member')
        with zipped.open(member) as stream:
            raw = stream.read(MAX_RECEIPT_BYTES + 1)
        require(len(raw) == member.file_size and len(raw) <= MAX_RECEIPT_BYTES, 'Receipt member size mismatch')
        return raw


def verify_attestation(raw: bytes, receipt: dict, repo: str, default_branch: str) -> None:
    """gh verifies the signature first; only its verified statement is inspected."""
    with tempfile.TemporaryDirectory(prefix='proof-lifecycle-') as temporary:
        target = Path(temporary) / 'lifecycle-receipt.json'
        target.write_bytes(raw)
        command = ['gh', 'attestation', 'verify', str(target), '--repo', repo,
                   '--signer-workflow', f'{repo}/{WORKFLOW_PATH}',
                   '--signer-digest', receipt['workflow_sha'], '--source-digest', receipt['workflow_sha'],
                   '--source-ref', f'refs/heads/{default_branch}', '--deny-self-hosted-runners',
                   '--predicate-type', 'https://slsa.dev/provenance/v1', '--limit', '10', '--format', 'json']
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=120, check=False)
            require(completed.returncode == 0, 'GitHub attestation signature verification failed')
            require(stdout.tell() <= 2_000_000, 'Attestation verification output exceeds limit')
            stdout.seek(0)
            verified = json.load(stdout)
    validate_attestation(verified, raw, receipt, repo, default_branch)


def validate_attestation(verified: Any, raw: bytes, receipt: dict, repo: str, default_branch: str) -> None:
    require(isinstance(verified, list) and 0 < len(verified) <= 10, 'No verified attestation')
    receipt_digest = hashlib.sha256(raw).hexdigest()
    expected_subjects = {'lifecycle-receipt.json': receipt_digest,
                         'image.tar': receipt['artifact']['digest'].removeprefix('sha256:')}
    accepted = []
    for entry in verified:
        result = entry.get('verificationResult', {}) if isinstance(entry, dict) else {}
        certificate = result.get('signature', {}).get('certificate', {})
        statement = result.get('statement', {})
        if not isinstance(certificate, dict) or not isinstance(statement, dict):
            continue
        identity = {
            'sourceRepositoryURI': f'https://github.com/{repo}',
            'sourceRepositoryDigest': receipt['workflow_sha'],
            'sourceRepositoryRef': f'refs/heads/{default_branch}',
            'buildSignerURI': f'https://github.com/{repo}/{WORKFLOW_PATH}@refs/heads/{default_branch}',
            'buildSignerDigest': receipt['workflow_sha'],
            'runInvocationURI': f"https://github.com/{repo}/actions/runs/{receipt['run_id']}/attempts/1",
            'runnerEnvironment': 'github-hosted',
        }
        if not all(certificate.get(key) == value for key, value in identity.items()):
            continue
        timestamps = result.get('verifiedTimestamps')
        require(isinstance(timestamps, list) and 0 < len(timestamps) <= 20, 'Verified observer timestamps missing')
        for timestamp in timestamps:
            require(isinstance(timestamp, dict) and timestamp.get('type') in {'Tlog', 'TimestampAuthority'}
                    and isinstance(timestamp.get('uri'), str) and urlparse(timestamp['uri']).scheme == 'https'
                    and bool(urlparse(timestamp['uri']).netloc) and isinstance(timestamp.get('timestamp'), str),
                    'Unrecognized verified observer timestamp')
            observed = datetime.fromisoformat(timestamp['timestamp'].replace('Z', '+00:00'))
            require(observed.tzinfo is not None and observed <= datetime.now(timezone.utc), 'Invalid observer timestamp')
        subjects = statement.get('subject')
        if statement.get('predicateType') != 'https://slsa.dev/provenance/v1' or not isinstance(subjects, list):
            continue
        if len(subjects) != 2 or not all(isinstance(s, dict) and set(s) == {'name', 'digest'} for s in subjects):
            continue
        # A single verified signature must bind both bytes; separate attestations
        # cannot be combined to manufacture an image/receipt association.
        if {s['name']: s['digest'] for s in subjects} == {
                name: {'sha256': value} for name, value in expected_subjects.items()}:
            accepted.append(entry)
    require(len(accepted) == 1, 'Signed receipt/image binding or certificate run identity is missing or ambiguous')


def trusted_tree(client: GitHub, revision: str, config: dict) -> list[tuple]:
    tree = client.get(f'/git/trees/{revision}?recursive=1')
    require(isinstance(tree, dict) and tree.get('truncated') is False
            and isinstance(tree.get('tree'), list), 'Trusted source tree is incomplete')
    fixture_directory = str(Path(config['dockerfile']).parent)
    paths = set(TRUSTED_PATHS + [config['dockerfile']] + config['iac_paths'])
    if fixture_directory != '.':
        paths.add(fixture_directory)
    records, seen, found = [], set(), set()
    for entry in tree['tree']:
        require(isinstance(entry, dict) and isinstance(entry.get('path'), str)
                and entry['path'] not in seen, 'Malformed or duplicate source tree path')
        path = entry['path']
        seen.add(path)
        selected = any(path == item or path.startswith(item + '/') for item in paths)
        ancestor = any(item.startswith(path + '/') for item in paths)
        if not selected and not ancestor:
            continue
        require(matches(SHA, entry.get('sha'))
                and (entry.get('type'), entry.get('mode')) in {
                    ('tree', '040000'), ('blob', '100644'), ('blob', '100755')}, 'Unsafe trusted source link/type')
        if ancestor:
            require(entry['type'] == 'tree', 'Trusted path ancestor is not a directory')
        if selected:
            records.append((path, entry['type'], entry['mode'], entry['sha']))
        if path in paths:
            found.add(path)
    require(found == paths, 'Required trusted lifecycle source is absent')
    return sorted(records)


def validate_registry(providers: dict) -> None:
    entries = providers.get('providers', {})
    # Registry format is keyed; no caller-defined IDs or loose check names are accepted.
    require(isinstance(entries, dict), 'Invalid provider registry')
    for control, (provider, _) in PAIRS.items():
        contract = entries.get(provider)
        require(isinstance(contract, dict) and contract.get('lifecycle') == LIFECYCLE_CONTRACT
                and contract.get('capabilities') == [control], 'Lifecycle provider contract differs from builtin')


def validate_pr(pr: Any, repo: str, number: int, head: str, base: str, repository_id: int, branch: str) -> None:
    require(isinstance(pr, dict) and positive(pr.get('number')) and pr['number'] == number
            and pr.get('state') == 'open' and pr.get('base', {}).get('ref') == branch
            and pr.get('head', {}).get('repo', {}).get('full_name') == repo
            and positive(pr.get('head', {}).get('repo', {}).get('id'))
            and pr['head']['repo']['id'] == repository_id
            and pr.get('head', {}).get('sha') == head and pr.get('base', {}).get('sha') == base
            and pr.get('base', {}).get('repo', {}).get('full_name') == repo
            and pr.get('base', {}).get('repo', {}).get('id') == repository_id, 'PR/head/base identity differs')


def find_run(client: GitHub, workflow_id: int, number: int, head: str) -> dict:
    runs = enumerate_records(client, f'/actions/workflows/{workflow_id}/runs?event=workflow_dispatch', 'workflow_runs')
    title = f'Lifecycle PR #{number} @{head}'
    candidates = [run for run in runs if run.get('display_title') == title]
    require(len(candidates) == 1, 'Lifecycle run is absent or ambiguous for this PR revision')
    return candidates[0]


def validate_artifact(artifact: dict, name: str, run_id: int, workflow_sha: str, maximum: int) -> None:
    require(artifact.get('name') == name and positive(artifact.get('id'))
            and artifact.get('expired') is False and positive(artifact.get('size_in_bytes'))
            and artifact['size_in_bytes'] <= maximum and matches(DIGEST, artifact.get('digest')),
            'Lifecycle artifact is malformed, expired or oversized')
    run = artifact.get('workflow_run', {})
    require(run.get('id') == run_id and run.get('head_sha') == workflow_sha,
            'Lifecycle artifact has wrong run/source association')


def selected_artifacts(client: GitHub, run_id: int) -> tuple[dict, dict]:
    artifacts = enumerate_records(client, f'/actions/runs/{run_id}/artifacts', 'artifacts')
    selected = []
    for name in [f'proof-lifecycle-evidence-{run_id}-1', f'proof-lifecycle-image-{run_id}-1']:
        matches_ = [artifact for artifact in artifacts if artifact.get('name') == name]
        require(len(matches_) == 1, 'Lifecycle artifact is missing or duplicated')
        selected.append(matches_[0])
    return selected[0], selected[1]


def missing_manifest(repo: str, number: int, head: str, base: str, reason: str) -> dict:
    docs = {}
    for key, kind in [('git_commit', 'git-commit'), ('artifact', 'artifact'), ('environment', 'environment')]:
        docs[key] = {'version': 2, 'subject': {'type': kind, 'revision': head if key == 'git_commit'
                                            else f'unavailable:{head}'}, 'results': {
            control: {provider: {'producer': provider, 'status': 'not_run', 'reason': reason}}
            for control, (provider, subject) in PAIRS.items() if subject == kind}}
    return {'version': 1, 'provenance_verified': False, 'scope': 'verification',
            'context': {'repository': repo, 'pull_request_number': number, 'head_sha': head,
                        'base_sha': base, 'run_id': None, 'run_attempt': None, 'workflow_sha': None,
                        'reason': reason, 'artifact_kind': 'verification-fixture', 'environment_scope': 'verification'},
            'documents': docs}


def collect(repo: str, number: int, head: str, base: str, workflow_ref: str, config: dict,
            providers: dict, client: GitHub, attester=verify_attestation) -> dict:
    """Return explicit missing evidence on any provenance failure; never relax trust."""
    try:
        require(matches(SHA, head) and matches(SHA, base) and positive(number), 'Invalid requested revision/PR')
        validate_config(config)
        validate_registry(providers)
        repository = client.get('')
        require(repository.get('full_name') == repo and positive(repository.get('id')), 'Repository identity mismatch')
        branch = repository.get('default_branch')
        require(isinstance(branch, str) and workflow_ref == f'refs/heads/{branch}', 'Workflow ref must be default branch')
        pr = client.get(f'/pulls/{number}')
        validate_pr(pr, repo, number, head, base, repository['id'], branch)
        workflow = client.get('/actions/workflows/' + quote(WORKFLOW_PATH, safe=''))
        require(positive(workflow.get('id')) and workflow.get('path') == WORKFLOW_PATH
                and workflow.get('name') == 'Lifecycle Verification' and workflow.get('state') == 'active',
                'Trusted lifecycle workflow metadata mismatch')
        run = find_run(client, workflow['id'], number, head)
        run_id, workflow_sha = run['id'], run.get('head_sha')
        require(matches(SHA, workflow_sha) and run.get('event') == 'workflow_dispatch'
                and run.get('path') == WORKFLOW_PATH and run.get('workflow_id') == workflow['id']
                and run.get('head_branch') == branch and type(run.get('run_attempt')) is int and run['run_attempt'] == 1
                and run.get('status') == 'completed' and run.get('conclusion') == 'success'
                and run.get('repository', {}).get('id') == repository['id']
                and run.get('repository', {}).get('full_name') == repo, 'Lifecycle run is incomplete or untrusted')
        ancestry = client.get(f'/compare/{workflow_sha}...{quote(branch, safe="")}')
        require(ancestry.get('status') in {'ahead', 'identical'}
                and ancestry.get('merge_base_commit', {}).get('sha') == workflow_sha,
                'Workflow source is not a default-branch ancestor')
        baseline = trusted_tree(client, base, config)
        require(baseline == trusted_tree(client, workflow_sha, config)
                == trusted_tree(client, head, config), 'Trusted lifecycle sources changed across base/head/workflow')
        config_blob = client.get(f'/contents/{CONFIG_PATH}?ref={workflow_sha}')
        require(config_blob.get('type') == 'file' and config_blob.get('encoding') == 'base64'
                and positive(config_blob.get('size')) and config_blob['size'] <= MAX_RECEIPT_BYTES,
                'Trusted configuration blob unavailable')
        config_raw = base64.b64decode(config_blob['content'], validate=False)
        require(len(config_raw) == config_blob['size'], 'Trusted configuration blob size differs')
        config_git_sha = hashlib.sha1(b'blob ' + str(len(config_raw)).encode() + b'\0' + config_raw).hexdigest()
        expected_config_sha = next(row[3] for row in baseline if row[0] == CONFIG_PATH)
        require(config_blob.get('sha') == config_git_sha == expected_config_sha, 'Trusted configuration blob digest differs')
        trusted_config = strict_json(config_raw)
        require(trusted_config == config, 'Collector configuration differs from trusted source')
        receipt_artifact, image_artifact = selected_artifacts(client, run_id)
        validate_artifact(receipt_artifact, f'proof-lifecycle-evidence-{run_id}-1', run_id, workflow_sha, MAX_ARCHIVE_BYTES)
        validate_artifact(image_artifact, f'proof-lifecycle-image-{run_id}-1', run_id, workflow_sha,
                          config['max_image_bytes'] + 1_000_000)
        archive = client.archive(receipt_artifact['id'])
        require('sha256:' + hashlib.sha256(archive).hexdigest() == receipt_artifact['digest'], 'Receipt archive digest mismatch')
        raw = receipt_bytes(archive)
        receipt = validate_receipt(strict_json(raw), config)
        expected = {'repository': repo, 'pull_request_number': number, 'head_sha': head, 'base_sha': base,
                    'run_id': run_id, 'run_attempt': 1, 'workflow_sha': workflow_sha, 'config_sha': digest(config)}
        require(all(receipt[key] == value for key, value in expected.items()), 'Receipt context differs from GitHub identity')
        require(receipt['artifact']['artifact_id'] == image_artifact['id']
                and receipt['artifact']['archive_digest'] == image_artifact['digest'], 'Receipt image archive binding differs')
        attester(raw, receipt, repo, branch)
        # Recheck mutable platform identities after expensive download/verification.
        require(selected_artifacts(client, run_id) == (receipt_artifact, image_artifact)
                and client.get(f'/actions/artifacts/{receipt_artifact["id"]}') == receipt_artifact
                and client.get(f'/actions/artifacts/{image_artifact["id"]}') == image_artifact,
                'Lifecycle artifacts changed during verification')
        require(find_run(client, workflow['id'], number, head) == run
                and client.get(f'/actions/runs/{run_id}') == run
                and client.get('/actions/workflows/' + quote(WORKFLOW_PATH, safe='')) == workflow,
                'Lifecycle workflow/run changed during verification')
        validate_pr(client.get(f'/pulls/{number}'), repo, number, head, base, repository['id'], branch)
        require(client.get(f'/contents/{CONFIG_PATH}?ref={workflow_sha}') == config_blob,
                'Trusted lifecycle configuration changed during verification')
        latest_repository = client.get('')
        require(all(latest_repository.get(key) == repository[key] for key in ['id', 'full_name', 'default_branch']),
                'Repository identity or default branch changed during verification')
        manifest = {'version': 1, 'provenance_verified': True, 'scope': 'verification',
                    'context': {**expected, 'reason': 'Verified signed lifecycle receipt and exact GitHub run/artifact identities',
                                'artifact_kind': 'verification-fixture', 'environment_scope': 'verification'},
                    'documents': copy.deepcopy(receipt['documents'])}
        del manifest['context']['config_sha']
        manifest['documents']['artifact']['results']['artifact-provenance']['github-artifact-attestations'] = {
            'producer': 'GitHub artifact attestations', 'status': 'passed',
            'evidence': ['Receipt and image share one verified SLSA signature']}
        url = f'https://github.com/{repo}/actions/runs/{run_id}'
        for document in manifest['documents'].values():
            for providers_ in document['results'].values():
                for result in providers_.values():
                    if result['status'] in {'passed', 'failed'}:
                        # Public evidence is derived from verified metadata, not untrusted report prose.
                        result['evidence'] = [url, 'Signed verification fixture lifecycle receipt']
        return validate_companions_manifest(manifest, head)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        reason = 'Lifecycle evidence unavailable: ' + str(error)[:850]
        return missing_manifest(repo, number, head, base, reason)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pull-request-number', type=int, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--trusted-base-revision', required=True)
    parser.add_argument('--trusted-workflow-ref', required=True)
    for name in ['providers', 'config']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        config = strict_json(args.config.read_bytes())
        providers = strict_json(args.providers.read_bytes())
        manifest = collect(args.repo, args.pull_request_number, args.revision, args.trusted_base_revision,
                           args.trusted_workflow_ref, config, providers,
                           GitHub(args.repo, os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')))
    except (ValueError, OSError) as error:
        manifest = missing_manifest(args.repo, args.pull_request_number, args.revision,
                                    args.trusted_base_revision, 'Lifecycle configuration unavailable: ' + str(error)[:800])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [('lifecycle-companions.json', manifest),
                        ('lifecycle-git-evidence.json', manifest['documents']['git_commit'])]:
        (args.output_dir / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print('Lifecycle provenance verified' if manifest['provenance_verified'] else manifest['context']['reason'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
