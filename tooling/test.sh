#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "${repo_root}"

python3 -m unittest discover -s proof/tests -p 'test_*.py'
python3 -m unittest discover -s tooling/tests -p 'test_*.py'
python3 -m unittest discover -s tooling/validators/tests -p 'test_*.py'
python3 -m unittest discover -s examples/python-demo -p 'test_*.py'
