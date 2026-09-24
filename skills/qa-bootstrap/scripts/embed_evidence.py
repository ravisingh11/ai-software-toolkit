#!/usr/bin/env python3
"""Replace <!-- evidence:ID --> markers in qa-results/report.md with uploaded
embeds (from uploads.json) or an artifact note."""
import json
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "qa-results")
report = root / "report.md"
if not report.exists():
    sys.exit(0)


def load(name, default):
    try:
        return json.loads((root / name).read_text())
    except (OSError, ValueError):
        return default


evidence = {e.get("id"): e for e in load("evidence.json", []) if isinstance(e, dict)}
uploads = load("uploads.json", {})


def replace(match):
    eid = match.group(1)
    if eid in uploads:
        return uploads[eid]
    name = pathlib.Path(str(evidence.get(eid, {}).get("file", eid))).name
    return f"_`{name}` is available in the job artifacts._"


text = re.sub(r"^<!-- evidence:([a-z0-9-]{1,64}) -->$", replace, report.read_text(), flags=re.M)
report.write_text(text)
