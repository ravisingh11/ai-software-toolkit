#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
bytecode_root="$(mktemp -d "${TMPDIR:-/tmp}/engineering-standards-build.XXXXXX")"
trap 'rm -rf "${bytecode_root}"' EXIT

cd "${repo_root}"
PYTHONPYCACHEPREFIX="${bytecode_root}" python3 -m compileall -q -f \
  proof \
  tooling \
  examples/python-demo

echo "Compiled the Python distribution without writing build output into the repository."
