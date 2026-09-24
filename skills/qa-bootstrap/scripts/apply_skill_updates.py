#!/usr/bin/env python3
"""Append validated QA learning only inside an existing skill's learned block."""
import json
import pathlib
import re
import sys

START, END = "<!-- qa:learned:start -->", "<!-- qa:learned:end -->"


def apply(updates_path, repo_root, skills_dir):
    root = pathlib.Path(repo_root).resolve()
    prefix = pathlib.PurePosixPath(skills_dir)
    if prefix.is_absolute() or ".." in prefix.parts or not prefix.parts:
        raise ValueError("skills directory must be a relative repository path")
    allowed = re.compile(rf"{re.escape(prefix.as_posix())}/qa(?:-[a-z0-9-]+)?/SKILL\.md")
    source = pathlib.Path(updates_path)
    if not source.exists():
        return 0
    if source.is_symlink():
        raise ValueError("updates file must not be a symlink")
    updates = json.loads(source.read_text())
    if not isinstance(updates, list):
        raise ValueError("skill updates must be an array")
    applied = 0
    for update in updates[:20]:
        if not isinstance(update, dict):
            continue
        rel, content = update.get("file"), update.get("content")
        if (not isinstance(rel, str) or not allowed.fullmatch(rel)
                or not isinstance(content, str) or not content.strip()
                or len(content) > 2000 or "<!--" in content):
            continue
        path = root / rel
        if (any(part.is_symlink() for part in [path, *path.parents] if part != root)
                or root not in path.resolve().parents or not path.is_file()):
            continue
        body = path.read_text()
        content = content.strip()
        if (body.count(START) != 1 or body.count(END) != 1
                or body.index(START) > body.index(END) or content in body):
            continue
        path.write_text(body.replace(END, f"{content}\n{END}", 1))
        applied += 1
    return applied


if __name__ == "__main__":
    print(f"applied {apply(*sys.argv[1:])} update(s)")
