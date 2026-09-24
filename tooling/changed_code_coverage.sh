#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
coverage_file="${repo_root}/.artifacts/guardrails/coverage.xml"
coverage_target="${GUARDRAILS_COVERAGE_TARGET:-90}"
coverage_data_root="$(mktemp -d "${TMPDIR:-/tmp}/engineering-standards-coverage.XXXXXX")"
export COVERAGE_FILE="${coverage_data_root}/coverage.data"
export COVERAGE_RCFILE="${repo_root}/tooling/coverage.ini"
export PYTHONPATH="${repo_root}/tooling/coverage-support${PYTHONPATH:+:${PYTHONPATH}}"
trap 'rm -rf "${coverage_data_root}"' EXIT

if [[ -z "${GUARDRAILS_COVERAGE_BASE_REF:-}" ]]; then
  echo "GUARDRAILS_COVERAGE_BASE_REF must identify the exact comparison commit." >&2
  exit 2
fi
command -v coverage >/dev/null 2>&1 || {
  echo "coverage is required; install tooling/requirements-ci.txt" >&2
  exit 2
}
command -v diff-cover >/dev/null 2>&1 || {
  echo "diff-cover is required; install tooling/requirements-ci.txt" >&2
  exit 2
}

cd "${repo_root}"
mkdir -p "$(dirname "${coverage_file}")"
coverage erase

coverage run \
  -m unittest discover -s guardrails/tests -p 'test_*.py'
coverage run \
  -m unittest discover -s tooling/tests -p 'test_*.py'
coverage run \
  -m unittest discover -s tooling/validators/tests -p 'test_*.py'
coverage run \
  -m unittest discover -s examples/python-demo -p 'test_*.py'
coverage run \
  -m unittest discover -s skills/_shared-project-ops/scripts/tests -p 'test_*.py'
coverage run \
  -m unittest discover -s skills/full-test-suite/scripts/tests -p 'test_*.py'
coverage run \
  -m unittest discover -s skills/issue-operator/scripts/tests -p 'test_*.py'
coverage run \
  -m unittest discover -s security/semgrep/tests -p 'test_*.py'
coverage combine --quiet
coverage xml -o "${coverage_file}"

for surface in \
  full-test-suite/scripts/full_test_suite_runner.py \
  full-test-suite/scripts/full_test_suite_executor.py \
  issue-operator/scripts/gh_issue_helper.py; do
  grep -Fq "filename=\"${surface}\"" "${coverage_file}" || {
    echo "Coverage data is missing the subprocess surface: ${surface}" >&2
    exit 2
  }
done

coverage_report="${coverage_data_root}/changed-code-coverage.md"
coverage_status=0
diff-cover "${coverage_file}" \
  --compare-branch="${GUARDRAILS_COVERAGE_BASE_REF}" \
  --fail-under="${coverage_target}" \
  --format "markdown:${coverage_report}" || coverage_status=$?

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    printf '\n## Coverage check\n\n'
    if [[ "${coverage_status}" -ne 0 ]]; then
      printf '**Result:** Failed. Review the comparison below and the job logs.\n\n'
    elif [[ -f "${coverage_report}" ]] && grep -Fq 'No lines with coverage information in this diff.' "${coverage_report}"; then
      printf '**Result:** Passed — no changed lines to measure.\n\n'
      printf 'The coverage report contains no measured changed lines. This can happen for documentation-only changes or excluded files. No coverage percentage applies.\n\n'
    else
      printf '**Result:** Passed. The changed-code coverage command completed successfully.\n\n'
    fi
    printf '**Target:** at least %s%% coverage of measured changed lines.\n\n' "${coverage_target}"
    printf 'The coverage command runs the repository test suites before comparing changed lines; a docs-only change does not skip those suites.\n\n'
    if [[ -s "${coverage_report}" ]]; then
      cat "${coverage_report}"
    else
      printf 'Detailed comparison unavailable. Check the job logs; no coverage percentage is reported here.\n'
    fi
  } >> "${GITHUB_STEP_SUMMARY}"
fi

exit "${coverage_status}"
