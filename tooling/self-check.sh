#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'Usage: tooling/self-check.sh [base-ref]'
  echo 'Run the installed Guardrails scanner against clean HEAD (default base: origin/main).'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && ( -z "$1" || "$1" == -* ) ) ]]; then
  usage >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "${repo_root}"
base_revision="$(git rev-parse --verify --end-of-options "${1:-origin/main}^{commit}")"
git rev-parse --verify 'HEAD^{commit}' >/dev/null
worktree_status="$(git status --porcelain --untracked-files=normal)"
if [[ -n "${worktree_status}" ]]; then
  echo 'Self-check requires a clean committed HEAD; commit or isolate your changes first.' >&2
  exit 1
fi

export GUARDRAILS_BUILD_COMMAND='tooling/build.sh'
export GUARDRAILS_UNIT_TEST_COMMAND='tooling/test.sh'
export GUARDRAILS_CHANGED_COVERAGE_COMMAND='tooling/changed_code_coverage.sh'
export GUARDRAILS_FORMAT_LINT_COMMAND='tooling/lint.sh'
export GUARDRAILS_MIGRATION_VALIDATION_COMMAND='python3 tooling/validators/validate_no_migrations.py'
export GUARDRAILS_COVERAGE_BASE_REF="${base_revision}"
export GUARDRAILS_WORKING_DIRECTORY='.'
export GUARDRAILS_SETUP_COMMAND=''

exec python3 .guardrails/scan.py --base-ref "${base_revision}" \
  --policy .guardrails/policy.yaml \
  --profiles .guardrails/profiles.yaml \
  --catalog .guardrails/control-catalog.yaml \
  --providers .guardrails/providers.yaml
