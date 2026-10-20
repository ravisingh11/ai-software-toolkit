"""Adversarial producer contracts; real executions are retained separately."""
import importlib.util
import pathlib
import json
from types import SimpleNamespace
from unittest import mock
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('lifecycle_producers', pathlib.Path(__file__).parents[1] / 'lifecycle_producers.py')
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)


class ProducerTests(unittest.TestCase):
    def test_package_import_retains_strict_report_validation(self):
        # Source-package imports lack the installed flat-runtime module name.
        # They must retain duplicate-key rejection through the package fallback.
        with mock.patch.dict('sys.modules', {'lifecycle_contract': None}):
            module = importlib.util.module_from_spec(SPEC)
            SPEC.loader.exec_module(module)
        with self.assertRaises(ValueError):
            module.strict_json(b'{"site":[],"site":[]}')

    def test_runner_bounds_output_time_and_does_not_forward_secrets(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            runner = producer.Runner(pathlib.Path(directory))
            with mock.patch.dict(producer.os.environ, {'GITHUB_TOKEN': 'must-not-forward'}):
                completed = runner.run([sys.executable, '-c', "import os; print(os.getenv('GITHUB_TOKEN','absent'))"])
            self.assertEqual(completed.stdout.strip(), 'absent')
            with self.assertRaises(ValueError):
                runner.run([sys.executable, '-c', 'import time; time.sleep(3)'], timeout=0.05)
            with mock.patch.object(producer, 'MAX_OUTPUT_BYTES', 1024), self.assertRaises(ValueError):
                runner.run([sys.executable, '-c', "print('x'*4096)"])
            self.assertLessEqual((pathlib.Path(directory) / 'command-3.log').stat().st_size, 1024)

    def test_partial_scanner_errors_never_pass(self):
        with self.assertRaises(ValueError):
            producer.scan_status({'Errors': ['partial'], 'Results': [{'Target': 'x', 'Class': 'os-pkgs', 'Type': 'alpine'}]}, 0, 'Vulnerabilities')
        with self.assertRaises(ValueError):
            producer.scan_status({'Results': [{'Target': 'x', 'Class': 'os-pkgs', 'Type': 'alpine', 'Errors': ['unreadable']}]}, 0, 'Vulnerabilities')

    def test_manual_workflow_separates_untrusted_execution_and_signing(self):
        import yaml
        workflow = yaml.safe_load((pathlib.Path(__file__).parents[2] / 'workflows/lifecycle-verification.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        self.assertEqual(set(triggers), {'workflow_dispatch'})
        self.assertEqual(workflow['run-name'], 'Lifecycle PR #${{ inputs.pull-request-number }} @${{ inputs.revision }}')
        self.assertEqual(set(triggers['workflow_dispatch']['inputs']), {'pull-request-number', 'revision'})
        self.assertNotIn('id-token', workflow['jobs']['produce']['permissions'])
        self.assertEqual(workflow['jobs']['attest']['permissions']['id-token'], 'write')
        signing = workflow['jobs']['attest']['steps']
        attest = next(step for step in signing if step.get('name') == 'Attest both subjects in one statement')
        self.assertEqual(attest['with']['subject-path'].split(), ['subject/image.tar', 'reports/lifecycle-receipt.json'])
        self.assertTrue(any('validate_receipt(receipt, config)' in step.get('run', '') for step in signing))
        produce = workflow['jobs']['produce']['steps']
        source = next(step for step in produce if step.get('id') == 'source')
        self.assertIn('.head.repo.full_name == $repo', source['run'])
        self.assertIn('refs/heads/$default_branch', source['run'])

    def test_cli_validates_identity_and_finalizes_only_unchanged_bytes(self):
        import sys
        run_args = ['run', '--source', '.', '--config', 'config.json', '--output', 'out', '--repository', 'owner/repo', '--head', 'a'*40, '--base', 'b'*40, '--workflow-sha', 'c'*40, '--pr', '1', '--run-id', '2', '--run-attempt', '1']
        with mock.patch.object(sys, 'argv', ['producer', *run_args]), mock.patch.object(producer, 'produce') as execute:
            producer.main()
            execute.assert_called_once()
        bad = list(run_args)
        bad[bad.index('--head')+1] = 'wrong'
        with mock.patch.object(sys, 'argv', ['producer', *bad]), mock.patch('sys.stderr'), self.assertRaises(SystemExit):
            producer.main()
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            (output / 'image.tar').write_bytes(b'image')
            producer.write(output / 'unsigned-receipt.json', {'artifact': {'digest': producer.digest(output / 'image.tar')}})
            finalize = ['producer', 'finalize', '--output', directory, '--artifact-id', '3', '--artifact-name', 'proof-lifecycle-image-2-1', '--archive-digest', 'sha256:'+'d'*64]
            with mock.patch.object(sys, 'argv', finalize):
                producer.main()
            self.assertEqual(json.loads((output / 'lifecycle-receipt.json').read_text())['artifact']['artifact_id'], 3)
            (output / 'image.tar').write_bytes(b'changed')
            with mock.patch.object(sys, 'argv', finalize), self.assertRaises(ValueError):
                producer.main()
            finalize[-1] = 'bad'
            with mock.patch.object(sys, 'argv', finalize), mock.patch('sys.stderr'), self.assertRaises(SystemExit):
                producer.main()

    def test_source_preflight_rejects_wrong_dirty_and_legacy_builds(self):
        for head, dirty, missing_buildx in [('b'*40, '', False), ('a'*40, ' M source.py', False), ('a'*40, '', True)]:
            runner = mock.Mock()
            def execute(argv):
                if 'rev-parse' in argv:
                    return SimpleNamespace(stdout=head)
                if 'status' in argv:
                    return SimpleNamespace(stdout=dirty)
                if missing_buildx:
                    raise ValueError('buildx unavailable')
                return SimpleNamespace(stdout='buildx')
            runner.run.side_effect = execute
            with self.assertRaises(ValueError):
                producer.preflight_source(runner, pathlib.Path('.'), 'a'*40)
            self.assertFalse(any('build' in call.args[0] for call in runner.run.call_args_list))

    def test_docker_base_must_be_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'Dockerfile'
            for text in ('FROM python:latest', 'FROM $BASE', 'RUN echo no-base', 'FROM python AS'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    producer.validate_dockerfile(path)
            path.write_text('FROM python@sha256:' + 'a'*64 + ' AS base\nFROM base AS build')
            producer.validate_dockerfile(path)

    def test_wrong_report_families_and_contradictory_iac_never_pass(self):
        bad = [
            ({'Results': [{'Target': 'x', 'Class': 'os-pkgs', 'Type': 'alpine', 'Vulnerabilities': [{'Severity': 'CRITICAL'}]}]}, 'Misconfigurations'),
            ({'Results': [{'Target': 'x', 'Class': 'config', 'Type': 'dockerfile'}]}, 'Vulnerabilities'),
            ({'Results': [{'Target': 'x', 'Class': 'config', 'Type': 'dockerfile', 'MisconfSummary': {'Successes': 0, 'Failures': 1}}]}, 'Misconfigurations'),
            ({'Results': [{'Target': 'x', 'Class': 'config', 'Type': 'dockerfile', 'MisconfSummary': {'Successes': 0, 'Failures': 0}}]}, 'Misconfigurations'),
        ]
        for report, family in bad:
            with self.subTest(report=report), self.assertRaises(ValueError):
                producer.scan_status(report, 0, family)
        report = {'Results': [{'Target': 'x', 'Class': 'config', 'Type': 'dockerfile', 'MisconfSummary': {'Successes': 1, 'Failures': 1}, 'Misconfigurations': [{'Severity': 'LOW'}]}]}
        self.assertEqual(producer.scan_status(report, 0, 'Misconfigurations'), 'passed')
        report['Results'][0]['Misconfigurations'][0]['Severity'] = 'HIGH'
        self.assertEqual(producer.scan_status(report, 0, 'Misconfigurations'), 'failed')

    def test_actual_trivy_076_dockerfile_report_shapes(self):
        # Structural projections of real 0.76.0 reports retained under the
        # provider-implementation/producer evidence directory. No rule counts
        # or severities are invented; unneeded descriptive strings are omitted.
        positive = {'Results': [{'Target': 'Dockerfile', 'Class': 'config', 'Type': 'dockerfile', 'MisconfSummary': {'Successes': 20, 'Failures': 0}}]}
        negative = {'Results': [{'Target': 'Dockerfile', 'Class': 'config', 'Type': 'dockerfile', 'MisconfSummary': {'Successes': 23, 'Failures': 4}, 'Misconfigurations': [
            {'ID': 'DS-0001', 'Severity': 'MEDIUM'},
            {'ID': 'DS-0002', 'Severity': 'HIGH'},
            {'ID': 'DS-0004', 'Severity': 'MEDIUM'},
            {'ID': 'DS-0026', 'Severity': 'LOW'},
        ]}]}
        self.assertEqual(producer.scan_status(positive, 0, 'Misconfigurations'), 'passed')
        self.assertEqual(producer.scan_status(negative, 0, 'Misconfigurations'), 'failed')
        negative['Results'][0]['Misconfigurations'] = []
        with self.assertRaises(ValueError):
            producer.scan_status(negative, 0, 'Misconfigurations')

    def test_empty_vulnerability_report_rejected(self):
        for report in ({}, {'Results': []}, {'Results': [{}]}):
            with self.assertRaises(ValueError):
                producer.scan_status(report, 0, 'Vulnerabilities')

    def test_findings_fail_and_tool_error_blocks(self):
        report = {'Results': [{'Target': 'image', 'Class': 'os-pkgs', 'Type': 'alpine', 'Vulnerabilities': [{'VulnerabilityID': 'CVE-1', 'Severity': 'HIGH'}]}]}
        self.assertEqual(producer.scan_status(report, 0, 'Vulnerabilities'), 'failed')
        with self.assertRaises(ValueError):
            producer.scan_status(report, 2, 'Vulnerabilities')

    def test_exit_status_cannot_hide_findings(self):
        report = {'Results': [{'Target': 'image', 'Class': 'os-pkgs', 'Type': 'alpine', 'Vulnerabilities': [{'VulnerabilityID': 'CVE-1', 'Severity': 'CRITICAL'}]}]}
        self.assertEqual(producer.scan_status(report, 0, 'Vulnerabilities'), 'failed')

    def test_sbom_requires_real_inventory(self):
        for report in ({}, {'bomFormat': 'CycloneDX', 'components': []}, {'bomFormat': 'CycloneDX', 'components': [{}]}):
            with self.assertRaises(ValueError):
                producer.validate_sbom(report)
        producer.validate_sbom({'bomFormat': 'CycloneDX', 'components': [{'type': 'library', 'name': 'python', 'version': '3.12'}]})

    def test_paths_reject_escape_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'file').write_text('ok')
            (root / 'link').symlink_to(root / 'file')
            for name in ('../outside', '/etc/passwd', 'link', '.', ''):
                with self.assertRaises(ValueError):
                    producer.safe_file(root, name)
            self.assertEqual(producer.safe_file(root, 'file'), root / 'file')

    def test_zap_inventory_requires_unique_installed_release_from_loader(self):
        row = 'Passive Scan Rules\tpscanrules\tv76.0.0\trelease\tRelease rules'
        inventory = producer.zap_inventory('Starting ZAP\n' + row + '\n')
        self.assertEqual(inventory['addons'][0]['version'], '76.0.0')
        mixed = row + ''.join(f'\nAddon\taddon{status}\tv1.2.3\t{status}\tDescription\twith tab' for status in ('unknown', 'example', 'alpha', 'beta', 'weekly'))
        self.assertEqual(len(producer.zap_inventory(mixed)['addons']), 6)
        for invalid in ('', row + '\n' + row, row.replace('v76.0.0', 'v70.0.0'), row.replace('v76.0.0', 'v76'),
                        row.replace('release', 'beta'), row.replace('release', 'RELEASE'), 'broken\tpscanrules',
                        row.replace('pscanrules', 'pscanrulesBeta')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                producer.zap_inventory(invalid)

    def test_zap_empty_wrong_target_and_bad_exit_rejected(self):
        for report, code in (({}, 0), ({'site': []}, 0), ({'site': [{'@name': 'https://example.com', 'alerts': []}]}, 0), ({'site': [{'@name': 'http://proof-target:8080', 'alerts': []}]}, 3)):
            with self.assertRaises(ValueError):
                producer.zap_status(report, code, 'http://proof-target:8080')

    def test_config_rejects_unknown_targets_and_insecure_budgets(self):
        original = __import__('json').loads((pathlib.Path(__file__).parents[2] / 'proof/defaults/lifecycle.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'examples/lifecycle').mkdir(parents=True)
            (root / 'examples/lifecycle/Dockerfile').write_text('FROM python@sha256:' + 'a'*64)
            for key, value in [('scope', 'production'), ('context', '../'), ('port', 80), ('soak_seconds', 0), ('max_latency_ms', True), ('health_path', '//evil.test'), ('health_path', '/health?redirect=https://evil'), ('required_headers', {}), ('iac_paths', []), ('negative_probes', []), ('negative_probes', [{'path': '/x', 'status': 200}]), ('health_revision_key', 'x.y'), ('required_headers', {'X': 'bad\nvalue'})]:
                cfg = dict(original, **{key: value})
                target = root / 'config.json'
                producer.write(target, cfg)
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    producer.config_load(target, root)
            producer.write(root / 'config.json', original)
            self.assertEqual(producer.config_load(root / 'config.json', root), original)

    def test_digest_is_bytes_bound_and_canonical_config_stable(self):
        self.assertEqual(producer.canonical_digest({'a': 1, 'b': 2}), producer.canonical_digest({'b': 2, 'a': 1}))
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'artifact'
            path.write_bytes(b'first')
            first = producer.digest(path)
            path.write_bytes(b'second')
            self.assertNotEqual(first, producer.digest(path))

    def test_result_does_not_convert_unavailable_to_success(self):
        result = producer.result('trivy', 'blocked', 'database unavailable')
        self.assertEqual(result, {'producer': 'trivy', 'status': 'blocked', 'reason': 'database unavailable'})

    def test_scanner_requires_well_formed_findings_and_consistent_exit(self):
        for code, findings in [(0, [{}]), (0, {}), (1, [])]:
            with self.subTest(code=code, findings=findings), self.assertRaises(ValueError):
                producer.scan_status({'Results': [{'Target': 'x', 'Class': 'os-pkgs', 'Type': 'alpine', 'Vulnerabilities': findings}]}, code, 'Vulnerabilities')
        self.assertEqual(producer.scan_status({'Results': [{'Target': 'x', 'Class': 'os-pkgs', 'Type': 'alpine'}]}, 0, 'Vulnerabilities'), 'passed')

    def exercise(self, failure=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        (root / 'examples/lifecycle').mkdir(parents=True)
        (root / 'examples/lifecycle/Dockerfile').write_text('FROM python@sha256:' + 'a'*64)
        cfg = json.loads((pathlib.Path(__file__).parents[2] / 'proof/defaults/lifecycle.json').read_text())
        producer.write(root / 'config.json', cfg)
        output = root / 'output'
        args = SimpleNamespace(source=str(root), output=str(output), config=str(root / 'config.json'), head='a'*40, base='b'*40, workflow_sha='c'*40, repository='owner/repo', pr=1, run_id=2, run_attempt=1)
        image_id = 'sha256:' + 'd'*64
        report = {'Results': [{'Target': 'image', 'Class': 'os-pkgs', 'Type': 'alpine'}]}
        zap = {'alive': False, 'report': False, 'cleaned': False}
        def command(self, argv, **kwargs):
            text, code = '', 0
            if argv[0] == 'git' and 'rev-parse' in argv:
                text = args.head
            if argv[:3] == ['docker', 'buildx', 'build'] and failure == 'build':
                raise ValueError('build failed')
            if argv[:3] == ['docker', 'image', 'inspect']:
                text = json.dumps([{'Size': 100, 'Id': image_id, 'Config': {'Labels': {'org.opencontainers.image.revision': args.head}}}])
            if argv[:2] == ['docker', 'save']:
                pathlib.Path(argv[argv.index('--output')+1]).write_bytes(b'image bytes')
            if argv[0] == 'trivy':
                if failure == 'scanner':
                    raise ValueError('scanner unavailable')
                if 'version' in argv:
                    text = json.dumps({'Version': producer.TRIVY_VERSION, 'VulnerabilityDB': {'UpdatedAt': producer.datetime.now(producer.timezone.utc).isoformat()}})
                if '--output' in argv:
                    path = pathlib.Path(argv[argv.index('--output')+1])
                    payload = report
                    if 'cyclonedx' in argv:
                        payload = {'bomFormat': 'CycloneDX', 'components': [{'type': 'library', 'name': 'python', 'version': '3.12'}]}
                    elif failure == 'findings':
                        payload = {'Results': [{'Target': 'image', 'Class': 'os-pkgs', 'Type': 'alpine', 'Vulnerabilities': [{'Severity': 'HIGH'}], 'Misconfigurations': [{'Severity': 'HIGH'}]}]}
                        code = 0
                    if 'config' in argv:
                        payload = {'Results': [{'Target': 'Dockerfile', 'Class': 'config', 'Type': 'dockerfile', 'MisconfSummary': {'Successes': 20, 'Failures': 1 if failure == 'findings' else 0}, 'Misconfigurations': [{'Severity': 'HIGH'}] if failure == 'findings' else []}]}
                    producer.write(path, payload)
            if argv[:2] == ['docker', 'inspect']:
                text = json.dumps([{'Id': 'e'*64, 'Image': image_id, 'State': {'Running': True}, 'Config': {'User': '65532:65532'}, 'HostConfig': {'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'], 'Memory': 536870912, 'NanoCpus': 1000000000, 'PidsLimit': 128, 'SecurityOpt': ['no-new-privileges'], 'Binds': None, 'PortBindings': {}}}])
            if argv[:3] == ['docker', 'network', 'inspect']:
                text = json.dumps([{'Internal': True}])
            if argv[:2] == ['docker', 'run'] and 'python' in argv:
                if failure == 'probe-execution':
                    raise ValueError('probe could not execute')
                text = json.dumps({'duration_seconds': 10.1, 'rows': [{'ok': failure != 'probe', 'path': '/health', 'revision': args.head, 'latency_ms': 1.0} for _ in range(10)]})
            if argv[:2] == ['docker', 'stats']:
                text = json.dumps({'CPUPerc': '0.0%', 'MemUsage': '1MiB / 512MiB', 'PIDs': '1'})
            if argv[:2] == ['docker', 'run'] and producer.ZAP_IMAGE in argv:
                # tmpfs reports disappear when PID 1 exits. The scanner must
                # run inside a live dedicated container until copying finishes.
                if '-d' not in argv or '--tmpfs' not in argv or '/bin/sleep' not in argv:
                    raise ValueError('ZAP requires a live container with a report mount')
                mount = argv[argv.index('--tmpfs') + 1]
                if mount != '/zap/wrk:rw,noexec,nosuid,size=64m,uid=1000,gid=1000,mode=0770':
                    raise ValueError('Unexpected ZAP report mount isolation')
                if failure == 'zap-start':
                    raise ValueError('ZAP container startup failed')
                zap['alive'] = True
            if argv[:2] == ['docker', 'exec'] and 'zap.sh' in argv:
                if argv[-3:] != ['-cmd', '-silent', '-addonlist'] or kwargs['timeout'] != 120:
                    raise ValueError('Inventory must be offline and bounded')
                if not zap['alive'] or failure == 'zap-inventory-start':
                    raise ValueError('ZAP loader startup failed')
                text = 'Passive Scan Rules\tpscanrules\tv76.0.0\trelease\tRelease rules'
                if failure == 'zap-inventory-missing':
                    text = 'Starting ZAP'
                if failure == 'zap-inventory-malformed':
                    text = 'broken\tpscanrules'
            if argv[:2] == ['docker', 'exec'] and 'zap-baseline.py' in argv:
                if argv[argv.index('-z') + 1] != '-silent':
                    raise ValueError('Baseline must not attempt online add-on changes')
                if not zap['alive'] or failure == 'zap-exec':
                    raise ValueError('ZAP cannot execute')
                if argv[argv.index('-J') + 1] != 'zap.json':
                    raise ValueError('ZAP report filename must be relative to its mount')
                zap['report'] = True
            if argv[:3] == ['docker', 'rm', '-f'] and argv[-1].endswith('-zap'):
                zap['alive'] = False
                zap['cleaned'] = True
            if argv[:2] == ['docker', 'cp']:
                raise ValueError('Docker archive copying cannot read tmpfs')
            if argv[:2] == ['docker', 'exec'] and 'cat' in argv:
                if not zap['alive'] or not zap['report']:
                    raise ValueError('ZAP tmpfs report unavailable after container exit')
                if failure == 'zap':
                    raise ValueError('ZAP report missing')
                text = json.dumps({'site': [{'@name': 'http://proof-target:8080', 'alerts': []}]})
                if failure == 'zap-empty':
                    text = ''
                if failure == 'zap-duplicate':
                    text = '{"site":[],"site":[{"@name":"http://proof-target:8080","alerts":[]}]}'
            return SimpleNamespace(stdout=text, returncode=code)
        with mock.patch.object(producer.Runner, 'run', command), mock.patch.object(producer.time, 'sleep'), mock.patch.object(producer.shutil, 'which', return_value=str(root / 'config.json')):
            if failure in ('build', 'probe-execution'):
                with self.assertRaises(ValueError):
                    producer.produce(args)
                return json.loads((output / 'blocked-documents.json').read_text())
            producer.produce(args)
        self.assertFalse(zap['alive'])
        self.assertTrue(zap['cleaned'])
        receipt = json.loads((output / 'unsigned-receipt.json').read_text())
        self.assertEqual(receipt['artifact']['digest'], producer.digest(output / 'image.tar'))
        self.assertEqual(receipt['environment']['snapshot_digest'], producer.canonical_digest(receipt['environment']['snapshot']))
        # Independently validate the collector's contract, including failed
        # provider outcomes; the synthetic upload metadata is test-only.
        contract_spec = importlib.util.spec_from_file_location('lifecycle_contract', pathlib.Path(__file__).parents[1] / 'lifecycle_contract.py')
        contract = importlib.util.module_from_spec(contract_spec)
        contract_spec.loader.exec_module(contract)
        receipt['artifact'].update(artifact_id=3, artifact_name='proof-lifecycle-image-2-1', archive_digest='sha256:' + 'f'*64)
        contract.validate_receipt(receipt, cfg)
        dast = receipt['documents']['environment']['results']['dynamic-application-security']['zap-baseline-local']
        if dast['status'] in ('passed', 'failed'):
            for name in ('zap-addonlist.txt', 'zap-inventory.json'):
                self.assertIn(f'installed-inventory:{name} {producer.digest(output / name)}', dast['evidence'])
        return receipt['documents']

    def test_full_lifecycle_records_actual_subject_bound_results(self):
        docs = self.exercise()
        for doc in docs.values():
            for control, providers in doc['results'].items():
                for result in providers.values():
                    self.assertEqual(result['status'], 'not_run' if control == 'artifact-provenance' else 'passed')

    def test_findings_stay_failed(self):
        docs = self.exercise('findings')
        self.assertEqual(docs['artifact']['results']['container-vulnerability']['trivy-container-image']['status'], 'failed')

    def test_scanner_failure_preserves_runtime_results(self):
        docs = self.exercise('scanner')
        self.assertEqual(docs['artifact']['results']['container-vulnerability']['trivy-container-image']['status'], 'blocked')
        self.assertEqual(docs['environment']['results']['runtime-assurance']['repository-runtime-assurance']['status'], 'passed')

    def test_runtime_findings_fail_both_runtime_controls(self):
        docs = self.exercise('probe')
        self.assertEqual(docs['environment']['results']['runtime-assurance']['repository-runtime-assurance']['status'], 'failed')
        self.assertEqual(docs['environment']['results']['runtime-soak']['repository-soak']['status'], 'failed')

    def test_zap_failure_does_not_hide_other_results(self):
        docs = self.exercise('zap')
        self.assertEqual(docs['environment']['results']['dynamic-application-security']['zap-baseline-local']['status'], 'blocked')
        self.assertEqual(docs['artifact']['results']['artifact-sbom']['trivy-artifact-sbom']['status'], 'passed')

    def test_zap_start_and_exec_failures_cleanup_and_remain_blocked(self):
        for failure in ('zap-start', 'zap-exec', 'zap-empty', 'zap-duplicate', 'zap-inventory-start', 'zap-inventory-missing', 'zap-inventory-malformed'):
            docs = self.exercise(failure)
            self.assertEqual(docs['environment']['results']['dynamic-application-security']['zap-baseline-local']['status'], 'blocked')

    def test_build_failure_is_explicit_not_pass(self):
        docs = self.exercise('build')
        self.assertEqual(docs['environment']['results']['runtime-assurance']['repository-runtime-assurance']['status'], 'blocked')

    def test_probe_execution_failure_retains_completed_scanner_reports(self):
        docs = self.exercise('probe-execution')
        self.assertEqual(docs['artifact']['results']['artifact-sbom']['trivy-artifact-sbom']['status'], 'passed')
        self.assertEqual(docs['environment']['results']['runtime-assurance']['repository-runtime-assurance']['status'], 'blocked')

    def test_zap_informational_warning_exit_respects_existing_risk_policy(self):
        report = {'site': [{'@name': 'http://proof-target:8080', 'alerts': [{'pluginid': '10031', 'riskcode': '0'}]}]}
        self.assertEqual(producer.zap_status(report, 2, 'http://proof-target:8080'), 'passed')
        with self.assertRaises(ValueError):
            producer.zap_status(report, 1, 'http://proof-target:8080')
        for code in (1, 2):
            report['site'][0]['alerts'] = []
            with self.subTest(code=code), self.assertRaises(ValueError):
                producer.zap_status(report, code, 'http://proof-target:8080')
        for risk in ('1', '2', '3'):
            report['site'][0]['alerts'] = [{'riskcode': '0'}, {'riskcode': risk}]
            for code in (0, 1, 2):
                with self.subTest(risk=risk, code=code):
                    self.assertEqual(producer.zap_status(report, code, 'http://proof-target:8080'), 'failed')

    def test_zap_findings_and_clean(self):
        report = {'site': [{'@name': 'http://proof-target:8080', 'alerts': [{'riskcode': '2'}]}]}
        self.assertEqual(producer.zap_status(report, 2, 'http://proof-target:8080'), 'failed')
        report['site'][0]['alerts'] = []
        self.assertEqual(producer.zap_status(report, 0, 'http://proof-target:8080'), 'passed')


if __name__ == '__main__':
    unittest.main()
