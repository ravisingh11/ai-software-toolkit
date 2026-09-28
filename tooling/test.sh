#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "${repo_root}"

# Run every suite, keep each summary so CI can publish self-reported test
# totals (including failures), then return the combined result.
log_dir="$(mktemp -d "${TMPDIR:-/tmp}/engineering-standards-tests.XXXXXX")"
trap 'rm -rf "${log_dir}"' EXIT
suites=(proof/tests tooling/tests tooling/validators/tests examples/python-demo)
status=0
for index in "${!suites[@]}"; do
  python3 -m unittest discover -s "${suites[${index}]}" -p 'test_*.py' 2>&1 \
    | tee "${log_dir}/suite-${index}.log" || status=1
done

if [[ -n "${PROOF_MEASUREMENTS_FILE:-}" ]]; then
  python3 tooling/proof_measurements.py unittest "${log_dir}"/suite-*.log \
    --output "${PROOF_MEASUREMENTS_FILE}" \
    || echo "Test measurements were not recorded; test results are unaffected." >&2
fi
exit "${status}"
