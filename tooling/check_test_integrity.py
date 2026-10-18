#!/usr/bin/env python3
"""Optionally check a repository-owned test command's fresh JUnit report.

Example: python3 tooling/check_test_integrity.py -- pytest --junitxml={report}
The caller decides whether this command is advisory or a required check.
"""
import argparse
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

MAX_REPORT_BYTES = 10 * 1024 * 1024


def validate_options(min_tests, max_skipped_percent):
    if min_tests < 1:
        raise ValueError('min-tests must be at least 1')
    if not math.isfinite(max_skipped_percent) or not 0 <= max_skipped_percent <= 100:
        raise ValueError('max-skipped-percent must be between 0 and 100')


def inspect_report(path, min_tests=1, max_skipped_percent=100):
    """Return (discovered cases, skipped cases), or reject unusable evidence."""
    validate_options(min_tests, max_skipped_percent)
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_REPORT_BYTES + 1)
    except OSError as exc:
        raise ValueError('test command did not produce a readable JUnit report') from exc
    if not data or len(data) > MAX_REPORT_BYTES:
        raise ValueError('JUnit report is empty or exceeds the 10 MiB limit')
    # Removing NULs also detects declarations in UTF-16/32 XML before parsing.
    if re.search(br'<!\s*(DOCTYPE|ENTITY)\b', data.replace(b'\x00', b''), re.IGNORECASE):
        raise ValueError('JUnit DTD and entity declarations are not supported')
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError('JUnit report is malformed XML') from exc
    if root.tag not in ('testsuite', 'testsuites'):
        raise ValueError('JUnit root must be testsuite or testsuites')
    cases = list(root.iter('testcase'))
    if not cases:
        raise ValueError('JUnit report contains zero test cases')
    for parent in root.iter():
        for child in parent:
            if child.tag in ('failure', 'error', 'skipped') and parent.tag != 'testcase':
                raise ValueError('JUnit outcomes must belong to a testcase')
            if child.tag == 'testcase' and parent.tag not in ('testsuite', 'testsuites'):
                raise ValueError('JUnit testcase must belong to a testsuite or testsuites')
            if child.tag in ('testsuite', 'testsuites') and parent.tag not in ('testsuite', 'testsuites'):
                raise ValueError('JUnit suites must be nested under suites')
    for case in cases:
        outcomes = [child.tag for child in case if child.tag in ('failure', 'error', 'skipped')]
        if 'skipped' in outcomes and (len(outcomes) != 1):
            raise ValueError('JUnit testcase has contradictory outcomes')
    for suite in root.iter():
        if suite.tag not in ('testsuite', 'testsuites'):
            continue
        descendants = list(suite.iter('testcase'))
        counts = {'tests': len(descendants)}
        for attribute, tag in (('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')):
            counts[attribute] = sum(case.find(tag) is not None for case in descendants)
        for attribute, actual in counts.items():
            declared = suite.get(attribute)
            if declared is not None and (not re.fullmatch(r'[0-9]+', declared) or int(declared) != actual):
                raise ValueError('JUnit {} count contradicts actual test cases'.format(attribute))
    failed = sum(case.find('failure') is not None or case.find('error') is not None for case in cases)
    skipped = sum(case.find('skipped') is not None for case in cases)
    if failed:
        raise ValueError('JUnit report contains {} failed or errored tests'.format(failed))
    if skipped == len(cases):
        raise ValueError('JUnit report contains only skipped tests')
    if len(cases) < min_tests:
        raise ValueError('JUnit report has {} tests, below minimum {}'.format(len(cases), min_tests))
    if skipped * 100 / len(cases) > max_skipped_percent:
        raise ValueError('JUnit skipped-test percentage exceeds {}'.format(max_skipped_percent))
    return len(cases), skipped


def run_tests(command, working_directory=None, min_tests=1, max_skipped_percent=100):
    """Run argv without a shell and inspect only this invocation's report path."""
    validate_options(min_tests, max_skipped_percent)
    if not command or not any('{report}' in argument for argument in command):
        raise ValueError('command must include a {report} placeholder for its JUnit output')
    with tempfile.TemporaryDirectory(prefix='test-integrity-') as directory:
        report = Path(directory) / 'report.xml'
        argv = [argument.replace('{report}', str(report)) for argument in command]
        try:
            result = subprocess.run(argv, cwd=working_directory, check=False)
        except OSError as exc:
            raise ValueError('could not start test command: {}'.format(exc)) from exc
        if result.returncode:
            raise ValueError('test command exited with status {}'.format(result.returncode))
        return inspect_report(report, min_tests, max_skipped_percent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--working-directory')
    parser.add_argument('--min-tests', type=int, default=1)
    parser.add_argument('--max-skipped-percent', type=float, default=100)
    parser.add_argument('command', nargs=argparse.REMAINDER, help='test command after --, containing {report}')
    args = parser.parse_args(argv)
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    try:
        total, skipped = run_tests(command, args.working_directory, args.min_tests, args.max_skipped_percent)
    except ValueError as exc:
        print('Test integrity failed: {}'.format(exc), file=sys.stderr)
        return 1
    print('Test integrity passed: {} tests, {} executed, {} skipped; fresh JUnit report checked.'.format(total, total - skipped, skipped))
    return 0


if __name__ == '__main__':
    sys.exit(main())
