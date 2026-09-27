#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'Usage: tooling/self-check.sh [base-ref]'
  echo 'Run the installed Proof scanner against clean HEAD (default base: origin/main).'
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

export PROOF_BUILD_COMMAND='tooling/build.sh'
export PROOF_UNIT_TEST_COMMAND='tooling/test.sh'
export PROOF_CHANGED_COVERAGE_COMMAND='tooling/changed_code_coverage.sh'
export PROOF_FORMAT_LINT_COMMAND='tooling/lint.sh'
export PROOF_MIGRATION_VALIDATION_COMMAND='python3 tooling/validators/validate_no_migrations.py'
export PROOF_COVERAGE_BASE_REF="${base_revision}"
export PROOF_WORKING_DIRECTORY='.'
export PROOF_SETUP_COMMAND=''

exec python3 .proof/scan.py --base-ref "${base_revision}" \
  --policy .proof/policy.yaml \
  --profiles .proof/profiles.yaml \
  --catalog .proof/control-catalog.yaml \
  --providers .proof/providers.yaml
