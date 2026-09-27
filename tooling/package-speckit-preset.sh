#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
preset_dir="$repo_root/tooling/speckit/engineering-standards"
version="$(python3 - "$preset_dir/preset.yml" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'(?m)^  version: "([^"]+)"$', text)
if not match:
    raise SystemExit("Could not find preset version")
print(match.group(1))
PY
)"
dist_dir="$repo_root/dist"
zip_path="$dist_dir/spec-kit-preset-engineering-standards-v${version}.zip"

command -v zip >/dev/null 2>&1 || {
  printf 'ERROR: required command not found: zip\n' >&2
  exit 1
}

mkdir -p "$dist_dir"
rm -f "$zip_path"

(
  cd "$preset_dir"
  zip -qr "$zip_path" preset.yml README.md templates commands
)

printf '%s\n' "$zip_path"
