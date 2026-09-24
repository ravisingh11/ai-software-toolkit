#!/usr/bin/env python3
"""Append QA-learned entries to the learned block of qa/qa-* skills.
Usage: apply_skill_updates.py <skill-updates.json> <repo-root> <skills-dir>
Anything else in the JSON (other files, other sections) is rejected."""
import json
import pathlib
import re
import sys

updates_path, repo_root, skills_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]).resolve(), sys.argv[3].strip("/")
START, END = "<!-- qa:learned:start -->", "<!-- qa:learned:end -->"
allowed = re.compile(rf"^{re.escape(skills_dir)}/qa(-[a-z0-9-]+)?/SKILL\.md$")

if not updates_path.exists():
    sys.exit(0)
try:
    updates = json.loads(updates_path.read_text())
except ValueError:
    sys.exit("skill-updates.json is not valid JSON")

applied = 0
for u in updates[:20] if isinstance(updates, list) else []:
    rel = str(u.get("file", "")) if isinstance(u, dict) else ""
    content = str(u.get("content", "")).strip() if isinstance(u, dict) else ""
    path = (repo_root / rel).resolve()
    if (not allowed.match(rel) or not content or len(content) > 2000
            or "<!--" in content or repo_root not in path.parents or not path.is_file()):
        print(f"skipped: {rel!r}")
        continue
    body = path.read_text()
    if START not in body or END not in body or content in body:
        print(f"skipped (no learned block or duplicate): {rel}")
        continue
    path.write_text(body.replace(END, f"{content}\n{END}", 1))
    applied += 1
print(f"applied {applied} update(s)")
