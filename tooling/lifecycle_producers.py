#!/usr/bin/env python3
"""Optional, trusted lifecycle producers for isolated verification artifacts.

Candidate code executes only inside constrained Docker builds/containers. Tool
reports, actual bytes and observations are retained; completion is not a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone

try:
    from lifecycle_contract import strict_json
except ImportError:
    from tooling.lifecycle_contract import strict_json

ZAP_IMAGE = 'ghcr.io/zaproxy/zaproxy@sha256:5ccfff9a411743ab2615136a2edd7416bec9ce41572fa94e935df38c14adb2b6'
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
TRIVY_VERSION = '0.76.0'
TRIVY_SHA = 'e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7'
PROVIDERS = {'container-vulnerability': 'trivy-container-image', 'iac-misconfiguration': 'trivy-iac-config', 'artifact-sbom': 'trivy-artifact-sbom', 'artifact-vulnerability': 'trivy-artifact-sbom-scan', 'deployment-policy': 'repository-deployment-policy', 'dynamic-application-security': 'zap-baseline-local', 'runtime-assurance': 'repository-runtime-assurance', 'runtime-soak': 'repository-soak'}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return 'sha256:' + value.hexdigest()


def canonical_digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def safe_file(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('unsafe repository path')
    path = root / name
    if any((root / Path(name).parents[i]).is_symlink() for i in range(len(Path(name).parents))) or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('missing, linked or non-file input')
    return path


def config_load(path, root):
    cfg = json.loads(Path(path).read_text())
    keys = {'version', 'scope', 'dockerfile', 'context', 'iac_paths', 'port', 'health_path', 'health_revision_key', 'required_headers', 'negative_probes', 'soak_seconds', 'max_latency_ms', 'max_image_bytes', 'build_network'}
    if set(cfg) != keys or cfg['version'] != 1 or cfg['scope'] != 'verification' or cfg['context'] != '.' or cfg['build_network'] not in ('none', 'default'):
        raise ValueError('unsupported lifecycle configuration')
    safe_file(root, cfg['dockerfile'])
    if not isinstance(cfg['iac_paths'], list) or not cfg['iac_paths'] or len(cfg['iac_paths']) > 20:
        raise ValueError('IaC inputs required')
    for name in cfg['iac_paths']:
        safe_file(root, name)
        if not (Path(name).name == 'Dockerfile' or Path(name).suffix in {'.tf', '.yaml', '.yml', '.json'}):
            raise ValueError('unsupported IaC input')
    for key, low, high in [('port', 1024, 65535), ('soak_seconds', 10, 120), ('max_latency_ms', 1, 10000), ('max_image_bytes', 1024, 2147483648)]:
        if type(cfg[key]) is not int or not low <= cfg[key] <= high:
            raise ValueError('invalid resource budget: ' + key)
    paths = [cfg['health_path']]
    if not isinstance(cfg['negative_probes'], list) or not 1 <= len(cfg['negative_probes']) <= 10:
        raise ValueError('negative probes required')
    for probe in cfg['negative_probes']:
        if set(probe) != {'path', 'status'} or type(probe['status']) is not int or not 400 <= probe['status'] <= 499:
            raise ValueError('invalid negative probe')
        paths.append(probe['path'])
    if any(not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9/_-]*', value) for value in paths):
        raise ValueError('unsafe probe path')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', cfg['health_revision_key']):
        raise ValueError('invalid revision key')
    if not isinstance(cfg['required_headers'], dict) or not cfg['required_headers'] or len(cfg['required_headers']) > 10:
        raise ValueError('required security headers missing')
    for key, value in cfg['required_headers'].items():
        if not re.fullmatch(r'[A-Za-z-]{1,80}', key) or not isinstance(value, str) or not value or len(value) > 256 or '\n' in value or '\r' in value:
            raise ValueError('invalid security header')
    return cfg


def scan_status(report, code, field):
    if code != 0 or not isinstance(report, dict) or not isinstance(report.get('Results'), list) or not report['Results']:
        raise ValueError('scanner did not return a completed nonempty report')
    if any(report.get(key) for key in ('Errors', 'Error', 'error', 'errors')):
        raise ValueError('scanner reported incomplete execution')
    findings = 0
    for row in report['Results']:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) and row[key] for key in ('Target', 'Class', 'Type')):
            raise ValueError('incomplete scan target')
        if any(row.get(key) for key in ('Errors', 'Error', 'error', 'errors')):
            raise ValueError('scanner target reported incomplete execution')
        if field == 'Misconfigurations':
            summary = row.get('MisconfSummary', {})
            if row['Class'] != 'config' or row['Type'] not in {'dockerfile', 'terraform', 'kubernetes', 'helm', 'cloudformation', 'azure-arm'}:
                raise ValueError('Report target is not supported IaC')
            if not isinstance(summary, dict) or any(type(summary.get(key)) is not int or summary[key] < 0 for key in ('Successes', 'Failures')) or summary['Successes'] + summary['Failures'] < 1:
                raise ValueError('IaC report has no completed rule evaluations')
        elif field == 'Vulnerabilities':
            if row['Class'] not in {'os-pkgs', 'lang-pkgs'}:
                raise ValueError('Report target is not a package vulnerability scan')
        else:
            raise ValueError('Unknown scan report family')
        items = row.get(field, [])
        if not isinstance(items, list):
            raise ValueError('malformed findings')
        if field == 'Misconfigurations' and len(items) != summary['Failures']:
            raise ValueError('IaC summary does not match retained findings')
        for item in items:
            if not isinstance(item, dict) or item.get('Severity') not in {'UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}:
                raise ValueError('malformed finding')
            findings += item['Severity'] in ('HIGH', 'CRITICAL')
    return 'failed' if findings else 'passed'


def validate_sbom(report):
    if not isinstance(report, dict) or report.get('bomFormat') != 'CycloneDX' or not isinstance(report.get('components'), list) or not report['components']:
        raise ValueError('SBOM inventory is absent or empty')
    for item in report['components']:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key] for key in ('type', 'name', 'version')):
            raise ValueError('incomplete SBOM component')


def zap_inventory(stdout):
    # ZAP's local loader emits name, ID, vVERSION, release status, description.
    # Non-tab startup messages are retained in the raw file, not treated as rows.
    addons = []
    seen = set()
    for line in stdout.splitlines():
        if '\t' not in line:
            continue
        fields = line.split('\t', 4)
        if len(fields) != 5:
            raise ValueError('Malformed ZAP installed add-on inventory')
        name, addon_id, version, status, description = fields
        if not name or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', addon_id) or not re.fullmatch(r'v[0-9]+(?:\.[0-9]+)*', version) or status not in {'unknown', 'example', 'alpha', 'beta', 'weekly', 'release'} or not description or addon_id in seen:
            raise ValueError('Malformed or duplicate ZAP installed add-on')
        seen.add(addon_id)
        addons.append({'id': addon_id, 'version': version[1:], 'status': status})
    required = {'id': 'pscanrules', 'version': '76.0.0', 'status': 'release'}
    if required not in addons:
        raise ValueError('Pinned ZAP release passive rules v76 absent from local loader')
    return {'image': ZAP_IMAGE, 'scope': 'bundled release passive baseline', 'addons': sorted(addons, key=lambda item: item['id'])}


def zap_status(report, code, target):
    if code not in (0, 1, 2) or not isinstance(report, dict) or not isinstance(report.get('site'), list) or len(report['site']) != 1:
        raise ValueError('ZAP did not complete against one target')
    site = report['site'][0]
    if site.get('@name', '').rstrip('/') != target.rstrip('/') or not isinstance(site.get('alerts'), list):
        raise ValueError('ZAP target or alerts mismatch')
    for alert in site['alerts']:
        if str(alert.get('riskcode')) not in {'0', '1', '2', '3'}:
            raise ValueError('malformed ZAP finding')
    findings = any(int(item['riskcode']) >= 1 for item in site['alerts'])
    # Baseline WARN (exit 2) includes informational alerts by default.
    # A warning still needs a report alert; FAIL requires a policy finding.
    if (code == 1 and not findings) or (code == 2 and not site['alerts']):
        raise ValueError('ZAP exit and report disagree')
    return 'failed' if findings else 'passed'


class Runner:
    def __init__(self, output):
        self.output = output
        self.counter = 0

    def run(self, args, timeout=900, allowed=(0,)):
        self.counter += 1
        # Deliberately do not forward Actions tokens or application credentials.
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT') if key in os.environ}
        stdout_path = self.output / f'command-{self.counter}.stdout'
        stderr_path = self.output / f'command-{self.counter}.stderr'
        failure = None
        with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            process = subprocess.Popen(args, stdout=stdout, stderr=stderr, env=env, cwd=self.output, start_new_session=True)
            started = time.monotonic()
            while process.poll() is None:
                if stdout_path.stat().st_size + stderr_path.stat().st_size > MAX_OUTPUT_BYTES:
                    failure = 'output exceeded 8 MiB budget'
                elif time.monotonic() - started > timeout:
                    failure = 'execution exceeded time budget'
                if failure:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        # Some macOS runners deny process-group signalling even
                        # for a task-owned child; terminate that exact child.
                        if process.poll() is None:
                            process.kill()
                    process.wait()
                    break
                time.sleep(0.05)
        if stdout_path.stat().st_size + stderr_path.stat().st_size > MAX_OUTPUT_BYTES:
            failure = 'output exceeded 8 MiB budget'
        with stdout_path.open('rb') as stream:
            stdout_text = stream.read(MAX_OUTPUT_BYTES).decode('utf-8', errors='replace')
        with stderr_path.open('rb') as stream:
            stderr_text = stream.read(MAX_OUTPUT_BYTES).decode('utf-8', errors='replace')
        (self.output / f'command-{self.counter}.log').write_text((stdout_text + stderr_text)[:MAX_OUTPUT_BYTES])
        stdout_path.unlink()
        stderr_path.unlink()
        if failure or process.returncode not in allowed:
            raise ValueError(f'{args[0]} execution failed: {failure or process.returncode}; see command-{self.counter}.log')
        return subprocess.CompletedProcess(args, process.returncode, stdout_text, stderr_text)


def result(provider, status, reason, report=None):
    value = {'producer': provider, 'status': status}
    if status in ('passed', 'failed'):
        value['evidence'] = [reason]
        if report:
            value['evidence'].append(f'report:{Path(report).name} {digest(report)}')
            if provider == 'zap-baseline-local':
                for name in ('zap-addonlist.txt', 'zap-inventory.json'):
                    inventory = Path(report).parent / name
                    value['evidence'].append(f'installed-inventory:{name} {digest(inventory)}')
            metadata = Path(report).parent / 'trivy-version.json'
            if provider.startswith('trivy-') and metadata.is_file():
                value['evidence'].append(f'tool-and-database:trivy-version.json {digest(metadata)}')
    else:
        value['reason'] = reason
    return value


def preflight_source(run, root, expected_head):
    observed = run.run(['git', '-C', str(root), 'rev-parse', 'HEAD']).stdout.strip()
    if observed != expected_head:
        raise ValueError('Candidate checkout HEAD differs from requested revision')
    if run.run(['git', '-C', str(root), 'status', '--porcelain=v1', '--untracked-files=all']).stdout.strip():
        raise ValueError('Candidate checkout has modified or untracked source')
    run.run(['docker', 'buildx', 'version'])


def validate_dockerfile(path):
    stages = set()
    found = False
    for line in path.read_text().splitlines():
        if not line.strip().upper().startswith('FROM '):
            continue
        parts = line.split()
        if len(parts) not in (2, 4) or (len(parts) == 4 and parts[2].upper() != 'AS'):
            raise ValueError('Unsupported Dockerfile FROM declaration')
        image = parts[1]
        if image not in stages and not re.fullmatch(r'[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}', image):
            raise ValueError('Every external Docker base image must be digest pinned')
        if len(parts) == 4:
            stages.add(parts[3])
        found = True
    if not found:
        raise ValueError('Dockerfile contains no pinned base image')


def produce(args):
    root, output = Path(args.source).resolve(), Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cfg = config_load(args.config, root)
    run = Runner(output)
    try:
        preflight_source(run, root, args.head)
        validate_dockerfile(safe_file(root, cfg['dockerfile']))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        write(output / 'execution-error.json', {'status': 'blocked', 'reason': str(error)})
        raise
    config_sha = canonical_digest(cfg)
    docs = {key: {'version': 2, 'subject': {'type': kind, 'revision': args.head}, 'results': {}} for key, kind in [('git_commit', 'git-commit'), ('artifact', 'artifact'), ('environment', 'environment')]}
    locations = {'iac-misconfiguration': 'git_commit', 'container-vulnerability': 'artifact', 'artifact-sbom': 'artifact', 'artifact-vulnerability': 'artifact'}
    def record(control, status, reason, report=None):
        docs[locations.get(control, 'environment')]['results'][control] = {PROVIDERS[control]: result(PROVIDERS[control], status, reason, report)}
    for control in PROVIDERS:
        record(control, 'blocked', 'Producer has not completed')
    image = f'proof-lifecycle:{args.run_id}-{args.run_attempt}'
    network = f'proof-lifecycle-{args.run_id}-{args.run_attempt}'
    container = network + '-target'
    artifact = None
    snapshot = None
    try:
        # No candidate hook or shell command runs on the host. Docker build has
        # no credentials, host mounts, SSH forwarding or privileged entitlements.
        # Dependency egress is an explicit trusted-config choice; runtime is offline.
        run.run(['docker', 'buildx', 'build', '--load', '--network=' + cfg['build_network'], '--build-arg', f'PROOF_REVISION={args.head}', '--label', f'org.opencontainers.image.revision={args.head}', '-t', image, '-f', str(safe_file(root, cfg['dockerfile'])), str(root)])
        inspected = json.loads(run.run(['docker', 'image', 'inspect', image]).stdout)[0]
        if inspected['Size'] > cfg['max_image_bytes'] or inspected['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != args.head:
            raise ValueError('built image size or revision does not match')
        run.run(['docker', 'save', '--output', str(output / 'image.tar'), image])
        if (output / 'image.tar').stat().st_size > cfg['max_image_bytes']:
            raise ValueError('Saved image archive exceeds byte budget')
        artifact = {'kind': 'verification-fixture', 'digest': digest(output / 'image.tar'), 'source_revision': args.head}
        docs['artifact']['subject']['revision'] = artifact['digest']
        docs['artifact']['results']['artifact-provenance'] = {'github-artifact-attestations': result('github-artifact-attestations', 'not_run', 'Awaiting independent signature verification of image and receipt')}
        trivy = ['trivy', '--config', str(output / 'trivy.yaml'), '--cache-dir', str(output / 'trivy-cache')]
        (output / 'trivy.yaml').write_text('{}\n')
        (output / 'empty-ignore').write_text('')
        common = ['--ignorefile', str(output / 'empty-ignore'), '--exit-code', '0', '--format', 'json']
        scanner_ready = False
        version_ready = False
        try:
            version = json.loads(run.run(['trivy', 'version', '--format', 'json']).stdout)
            if version.get('Version') != TRIVY_VERSION:
                raise ValueError('Trivy version is not pinned version')
            version_ready = True
            run.run(trivy + ['image', '--download-db-only'])
            version = json.loads(run.run(trivy + ['version', '--format', 'json']).stdout)
            updated = datetime.fromisoformat(version['VulnerabilityDB']['UpdatedAt'].replace('Z', '+00:00'))
            if not 0 <= (datetime.now(timezone.utc) - updated).total_seconds() <= 172800:
                raise ValueError('vulnerability database is not current')
            version['ExecutableDigest'] = digest(shutil.which('trivy'))
            write(output / 'trivy-version.json', version)
            scanner_ready = True
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
            for control in ('container-vulnerability', 'artifact-vulnerability'):
                record(control, 'blocked', str(error))
        scans = [('container-vulnerability', ['image', '--input', str(output / 'image.tar')], 'Vulnerabilities'), ('iac-misconfiguration', ['config'], 'Misconfigurations')]
        for control, command, field in scans:
            if not version_ready or (control == 'container-vulnerability' and not scanner_ready):
                record(control, 'blocked', 'Pinned scanner or current vulnerability database is unavailable')
                continue
            try:
                report = output / f'{control}.json'
                if control == 'iac-misconfiguration':
                    # Each explicitly declared file gets a separate real scan.
                    combined = {'Results': []}
                    codes = []
                    for index, name in enumerate(cfg['iac_paths']):
                        part = output / f'iac-{index}.json'
                        completed = run.run(trivy + command + common + ['--output', str(part), str(safe_file(root, name))])
                        parsed = json.loads(part.read_text())
                        scan_status(parsed, completed.returncode, field)
                        combined['Results'].extend(parsed['Results'])
                        codes.append(completed.returncode)
                    write(report, combined)
                    status = scan_status(combined, max(codes), field)
                else:
                    completed = run.run(trivy + command + common + ['--scanners', 'vuln', '--output', str(report)])
                    status = scan_status(json.loads(report.read_text()), completed.returncode, field)
                record(control, status, 'Trivy 0.76.0 completed against declared subject; HIGH/CRITICAL findings fail', report)
            except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
                record(control, 'blocked', str(error))
        try:
            if not version_ready:
                raise ValueError('Pinned Trivy executable unavailable')
            sbom = output / 'sbom.cdx.json'
            run.run(trivy + ['image', '--input', str(output / 'image.tar'), '--format', 'cyclonedx', '--output', str(sbom)])
            validate_sbom(json.loads(sbom.read_text()))
            sbom_digest = digest(sbom)
            record('artifact-sbom', 'passed', f'Actual image {artifact["digest"]}; CycloneDX inventory {sbom_digest}', sbom)
            if scanner_ready:
                report = output / 'artifact-vulnerability.json'
                completed = run.run(trivy + ['sbom', '--scanners', 'vuln'] + common + ['--output', str(report), str(sbom)])
                if digest(sbom) != sbom_digest:
                    raise ValueError('SBOM mutated during scan')
                record('artifact-vulnerability', scan_status(json.loads(report.read_text()), completed.returncode, 'Vulnerabilities'), f'Scanned exact artifact SBOM {sbom_digest}', report)
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
            record('artifact-vulnerability', 'blocked', str(error))
            if docs['artifact']['results']['artifact-sbom']['trivy-artifact-sbom']['status'] != 'passed':
                record('artifact-sbom', 'blocked', str(error))
        run.run(['docker', 'network', 'create', '--internal', network])
        run.run(['docker', 'run', '--detach', '--name', container, '--network', network, '--network-alias', 'proof-target', '--read-only', '--user', '65532:65532', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '128', '--memory', '512m', '--cpus', '1', '--tmpfs', '/tmp:rw,noexec,nosuid,size=134217728', image])
        info = json.loads(run.run(['docker', 'inspect', container]).stdout)[0]
        net = json.loads(run.run(['docker', 'network', 'inspect', network]).stdout)[0]
        host = info['HostConfig']
        security = {'user': info['Config']['User'], 'read_only': host['ReadonlyRootfs'], 'network_internal': net['Internal'], 'privileged': host['Privileged'], 'cap_drop': host['CapDrop'], 'memory_bytes': host['Memory'], 'nano_cpus': host['NanoCpus'], 'pids_limit': host['PidsLimit'], 'no_new_privileges': any(item.startswith('no-new-privileges') for item in host['SecurityOpt'])}
        expected = {'user': '65532:65532', 'read_only': True, 'network_internal': True, 'privileged': False, 'cap_drop': ['ALL'], 'memory_bytes': 536870912, 'nano_cpus': 1000000000, 'pids_limit': 128, 'no_new_privileges': True}
        secure = security == expected and not host['Binds'] and not host['PortBindings'] and info['Image'] == inspected['Id']
        record('deployment-policy', 'passed' if secure else 'failed', 'Measured isolated verification deployment policy: ' + json.dumps(security, sort_keys=True))
        # Probe from trusted Python image on same internal network, without host
        # publication, mounts, candidate code, or secret environment variables.
        probe_image = 'python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4'
        probe_code = "import json,sys,time,urllib.request,urllib.error; c=json.loads(sys.argv[1]); ready=time.monotonic()\nwhile time.monotonic()-ready<30:\n try:\n  h=urllib.request.urlopen('http://proof-target:'+str(c['port'])+c['health_path'],timeout=2); b=json.loads(h.read(65537))\n  if h.status==200 and b.get(c['health_revision_key'])==sys.argv[2]: break\n except Exception: pass\n time.sleep(0.5)\nstart=time.monotonic(); rows=[]\nwhile time.monotonic()-start<c['soak_seconds']:\n for p,s in [(c['health_path'],200)]+[(x['path'],x['status']) for x in c['negative_probes']]:\n  t=time.monotonic(); r={'path':p,'ok':False}\n  try:\n   try: h=urllib.request.urlopen('http://proof-target:'+str(c['port'])+p,timeout=5)\n   except urllib.error.HTTPError as e: h=e\n   b=h.read(65537); r['ok']=h.status==s and all(h.headers.get(k)==v for k,v in c['required_headers'].items()); r['revision']=json.loads(b).get(c['health_revision_key']) if p==c['health_path'] else None\n   if p==c['health_path']: r['ok']=r['ok'] and r['revision']==sys.argv[2]\n  except Exception as e: r['error']=type(e).__name__\n  r['latency_ms']=(time.monotonic()-t)*1000; rows.append(r)\n time.sleep(0.2)\nprint(json.dumps({'duration_seconds':time.monotonic()-start,'rows':rows}))"
        def resources():
            stats = json.loads(run.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', container]).stdout)
            return {'cpu_percent': stats['CPUPerc'], 'memory_usage': stats['MemUsage'], 'pids': int(stats['PIDs'])}
        resource_observations = [resources()]
        time.sleep(2)
        observed = json.loads(run.run(['docker', 'run', '--rm', '--network', network, '--read-only', '--user', '65532:65532', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64', '--memory', '128m', '--cpus', '1', probe_image, 'python', '-c', probe_code, json.dumps(cfg), args.head], timeout=cfg['soak_seconds'] + 90).stdout)
        write(output / 'probes.json', observed)
        rows = observed['rows']
        probes = {'requests': len(rows), 'errors': sum(not row['ok'] for row in rows), 'max_latency_ms': max(row['latency_ms'] for row in rows), 'observed_revision': next((row.get('revision') for row in rows if row['path'] == cfg['health_path']), None)}
        soak = {key: probes[key] for key in ('requests', 'errors', 'max_latency_ms')}
        soak['duration_seconds'] = observed['duration_seconds']
        passed = bool(rows) and not probes['errors'] and probes['max_latency_ms'] <= cfg['max_latency_ms'] and probes['observed_revision'] == args.head
        record('runtime-assurance', 'passed' if passed else 'failed', 'Measured version, security headers, negative probes and latency in verification scope', output / 'probes.json')
        record('runtime-soak', 'passed' if passed and soak['duration_seconds'] >= cfg['soak_seconds'] else 'failed', f'Measured bounded verification soak duration {soak["duration_seconds"]:.3f}s; not production endurance evidence', output / 'probes.json')
        target = f'http://proof-target:{cfg["port"]}'
        snapshot = {'version': 1, 'repository': args.repository, 'head_sha': args.head, 'run_id': args.run_id, 'run_attempt': args.run_attempt, 'config_sha': config_sha, 'image_id': inspected['Id'], 'container_id': info['Id'], 'target': target + cfg['health_path'], 'security': security, 'probes': probes, 'soak': soak}
        try:
            run.run(['docker', 'pull', ZAP_IMAGE])
            zap_name = network + '-zap'
            try:
                # Keep the bounded private report mount alive until extraction.
                # A foreground baseline exits before its tmpfs can be copied.
                run.run(['docker', 'run', '-d', '--name', zap_name, '--network', network, '--user', '1000:1000', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '512', '--memory', '2g', '--cpus', '2', '--tmpfs', '/zap/wrk:rw,noexec,nosuid,size=64m,uid=1000,gid=1000,mode=0770', '--entrypoint', '/bin/sleep', ZAP_IMAGE, '900'])
                inventory_raw = output / 'zap-addonlist.txt'
                inventory_raw.write_text(run.run(['docker', 'exec', zap_name, 'zap.sh', '-cmd', '-silent', '-addonlist'], timeout=120).stdout, encoding='utf-8')
                write(output / 'zap-inventory.json', zap_inventory(inventory_raw.read_text(encoding='utf-8')))
                completed = run.run(['docker', 'exec', zap_name, 'zap-baseline.py', '-t', target + '/', '-m', '1', '-T', '5', '-J', 'zap.json', '-z', '-silent'], timeout=600, allowed=(0, 1, 2, 3))
                report = output / 'zap.json'
                report.write_text(run.run(['docker', 'exec', zap_name, 'cat', '/zap/wrk/zap.json'], timeout=30).stdout, encoding='utf-8')
                record('dynamic-application-security', zap_status(strict_json(report.read_bytes()), completed.returncode, target), 'Pinned ZAP bundled release passive baseline (installed pscanrules v76); isolated first-party verification target; all noninformational alerts fail', report)
            finally:
                run.run(['docker', 'rm', '-f', zap_name], allowed=(0, 1))
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
            record('dynamic-application-security', 'blocked', str(error))
        resource_observations.append(resources())
        final_info = json.loads(run.run(['docker', 'inspect', container]).stdout)[0]
        final_network = json.loads(run.run(['docker', 'network', 'inspect', network]).stdout)[0]
        final_state = {'running': final_info['State']['Running'], 'image_id': final_info['Image'], 'container_id': final_info['Id'], 'security_unchanged': final_info['HostConfig'] == host and final_info['Config']['User'] == security['user'] and final_network['Internal'] is True}
        snapshot['resource_observations'] = resource_observations
        snapshot['final_state'] = final_state
        if not (final_state['running'] and final_state['security_unchanged'] and final_state['image_id'] == inspected['Id'] and final_state['container_id'] == info['Id']):
            for control in ('deployment-policy', 'runtime-assurance', 'runtime-soak'):
                record(control, 'failed', 'Verification container identity or security changed during observation')
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        write(output / 'execution-error.json', {'reason': str(error)})
    finally:
        for command in (['docker', 'rm', '-f', container], ['docker', 'network', 'rm', network], ['docker', 'image', 'rm', image]):
            try:
                run.run(command, allowed=(0, 1))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
    if not artifact or not snapshot:
        write(output / 'blocked-documents.json', docs)
        raise ValueError('Artifact or environment could not be established; blocked reports retained')
    environment = {'scope': 'verification', 'snapshot_digest': canonical_digest(snapshot), 'source_revision': args.head, 'artifact_digest': artifact['digest'], 'snapshot': snapshot}
    docs['environment']['subject']['revision'] = environment['snapshot_digest']
    receipt = {'version': 1, 'repository': args.repository, 'pull_request_number': args.pr, 'head_sha': args.head, 'base_sha': args.base, 'run_id': args.run_id, 'run_attempt': args.run_attempt, 'workflow_sha': args.workflow_sha, 'config_sha': config_sha, 'artifact': artifact, 'environment': environment, 'documents': docs}
    write(output / 'unsigned-receipt.json', receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    for name in ('source', 'config', 'output', 'repository', 'head', 'base', 'workflow-sha'):
        run.add_argument('--' + name, required=True)
    for name in ('pr', 'run-id', 'run-attempt'):
        run.add_argument('--' + name, required=True, type=int)
    finalize = sub.add_parser('finalize')
    for name in ('output', 'artifact-name', 'archive-digest'):
        finalize.add_argument('--' + name, required=True)
    finalize.add_argument('--artifact-id', required=True, type=int)
    args = parser.parse_args()
    if args.command == 'run':
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository) or any(not re.fullmatch(r'[0-9a-f]{40}', getattr(args, key)) for key in ('head', 'base', 'workflow_sha')) or min(args.pr, args.run_id, args.run_attempt) < 1:
            parser.error('invalid source/run identity')
        produce(args)
    else:
        if args.artifact_id < 1 or not re.fullmatch(r'proof-lifecycle-image-[0-9]+-[0-9]+', args.artifact_name) or not re.fullmatch(r'sha256:[0-9a-f]{64}', args.archive_digest):
            parser.error('invalid image artifact metadata')
        output = Path(args.output)
        receipt = json.loads((output / 'unsigned-receipt.json').read_text())
        if digest(output / 'image.tar') != receipt['artifact']['digest']:
            raise ValueError('image changed before attestation')
        receipt['artifact'].update(artifact_id=args.artifact_id, artifact_name=args.artifact_name, archive_digest=args.archive_digest)
        write(output / 'lifecycle-receipt.json', receipt)


if __name__ == '__main__':
    main()
