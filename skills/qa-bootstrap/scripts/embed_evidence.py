#!/usr/bin/env python3
"""Replace report evidence markers using validated uploads or artifact notes."""
import json
import pathlib
import re
import sys


def embed(root):
    root = pathlib.Path(root)
    report = root / "report.md"
    if root.is_symlink() or report.is_symlink():
        raise ValueError("report paths must not be symlinks")
    if not report.exists():
        return

    def load(name, default):
        path = root / name
        if path.is_symlink():
            raise ValueError("evidence metadata must not be a symlink")
        try:
            result = json.loads(path.read_text())
        except (OSError, ValueError):
            return default
        return result if isinstance(result, type(default)) else default

    evidence = {e.get("id"): e for e in load("evidence.json", [])
                if isinstance(e, dict) and isinstance(e.get("id"), str)}
    uploads = load("uploads.json", {})

    def replace(match):
        eid = match.group(1)
        upload = uploads.get(eid)
        if isinstance(upload, str) and upload:
            return upload
        filename = evidence.get(eid, {}).get("file")
        name = pathlib.Path(str(filename or eid)).name
        name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
        directory = root / "evidence"
        if isinstance(filename, str) and pathlib.Path(filename).name == filename:
            artifact = directory / filename
            if (not directory.is_symlink() and not artifact.is_symlink()
                    and artifact.is_file() and artifact.stat().st_size > 0):
                return f"_`{name}` is available in the job artifacts._"
        return f"_Evidence `{name}` is unavailable; no nonempty artifact was found._"

    report.write_text(re.sub(r"^<!-- evidence:([a-z0-9-]{1,64}) -->$", replace,
                             report.read_text(), flags=re.M))


if __name__ == "__main__":
    embed(sys.argv[1] if len(sys.argv) > 1 else "qa-results")
