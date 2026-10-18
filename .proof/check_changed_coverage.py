#!/usr/bin/env python3
"""Optional changed-line coverage check with repository-selected scope and target.

Supply --base, --threshold, repeatable --source repository-relative paths, and a
coverage command after -- containing {report} (a fresh Cobertura XML filename)
or {report_dir} (a fresh directory containing cobertura-coverage.xml).
Example: python3 tooling/check_changed_coverage.py --base origin/main \
    --threshold 85 --source src -- npx vitest run --coverage \
    --coverage.reporter=cobertura --coverage.reportsDirectory={report_dir}
Requires diff-cover from tooling/requirements-ci.txt. Tracked files must be clean;
commit candidate changes first. Untracked source files are rejected. This checks
local files, not trusted CI provenance. Repository owners decide whether the exit
status is advisory or blocking. Reports must include zero-hit executable lines.
For every language, the producer owns completeness of executable-line reporting
and repository-selected exclusions. This wrapper cannot infer executable lines.
The standard external Cobertura DTD declaration is accepted but never fetched;
internal subsets, entity declarations, and other DTD declarations are rejected.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)
    if result.returncode:
        raise ValueError("Git comparison failed: " + result.stderr.strip())
    return result.stdout


def safe_relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("Expected a repository-relative path: " + value)
    return path.as_posix()


def in_scope(path, sources):
    return any(source == "." or path == source or path.startswith(source + "/") for source in sources)


def changed_lines(root, base, sources):
    paths = git(root, "diff", "--name-only", "-z", "--no-renames", base, "HEAD", "--").split("\0")
    changes = {}
    for path in paths:
        if not path or not in_scope(path, sources):
            continue
        diff = git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=0",
                   base, "HEAD", "--", path)
        lines = set()
        for start, count in re.findall(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.MULTILINE):
            lines.update(range(int(start), int(start) + (int(count) if count else 1)))
        if lines:
            changes[path] = lines
        elif "Binary files " in diff:
            raise ValueError("Cannot measure binary source: " + path)
    return changes


def validate_report(report, root, cwd, changes):
    if not report.is_file() or report.is_symlink():
        raise ValueError("Coverage command did not create a regular fresh report")
    with report.open("rb") as handle:
        data = handle.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("Coverage XML exceeds 10 MiB limit")
    # Istanbul's standard declaration is metadata only. Remove it before parsing,
    # so even parser changes cannot turn it into an external resource request.
    data = re.sub(
        rb'<!DOCTYPE\s+coverage\s+SYSTEM\s+([\'"])http://cobertura\.sourceforge\.net/xml/coverage-04\.dtd\1\s*>',
        b"", data, count=1)
    if not data.strip() or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper() or b"\0" in data:
        raise ValueError("Empty or unsafe coverage XML")
    document = ET.fromstring(data)
    if document.tag != "coverage":
        raise ValueError("Expected Cobertura coverage XML")
    for node in document.iter():
        for key in ("lines-valid", "lines-covered", "branches-valid", "branches-covered"):
            if key in node.attrib and not re.fullmatch(r"\d+", node.attrib[key]):
                raise ValueError("Invalid Cobertura counter: " + key)
        for key in ("line-rate", "branch-rate"):
            if key in node.attrib:
                value = float(node.attrib[key])
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("Invalid Cobertura rate: " + key)
        for kind in ("lines", "branches"):
            if kind + "-covered" in node.attrib and kind + "-valid" in node.attrib:
                if int(node.attrib[kind + "-covered"]) > int(node.attrib[kind + "-valid"]):
                    raise ValueError("Covered counter exceeds valid counter")
    bases = {root, cwd}
    for source in document.findall("./sources/source"):
        value = (source.text or "").strip()
        candidate = Path(value)
        if not candidate.is_absolute():
            safe_relative(value or ".")
            candidate = cwd / candidate
        candidate = candidate.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("Coverage source escapes repository")
        bases.add(candidate)
    measured = {}
    for cls in document.findall("./packages/package/classes/class"):
        filename = safe_relative(cls.get("filename", ""))
        candidates = set()
        for base in bases:
            candidate = (base / filename).resolve()
            if candidate.is_file() and root in candidate.parents:
                candidates.add(candidate)
        if len(candidates) != 1:
            raise ValueError("Coverage filename is missing or ambiguous: " + filename)
        candidate = candidates.pop()
        filename = candidate.relative_to(root).as_posix()
        cls.set("filename", filename)
        entries = measured.setdefault(filename, set())
        file_length = len(candidate.read_bytes().splitlines())
        for line in cls.findall("./lines/line"):
            number, hits = line.get("number", ""), line.get("hits", "")
            if not re.fullmatch(r"[1-9]\d*", number) or not re.fullmatch(r"\d+", hits):
                raise ValueError("Invalid coverage line or hit count")
            if int(number) > file_length:
                raise ValueError("Coverage line exceeds source length: " + filename)
            entries.add(int(number))
    if not any(measured.values()):
        raise ValueError("Coverage report has no per-file line measurements")
    relevant = 0
    for filename, changed in changes.items():
        if filename not in measured:
            raise ValueError("Changed source missing from coverage: " + filename)
        relevant += len(changed & measured[filename])
    # Normalize paths so diff-cover interprets nested project reports as repo paths.
    sources_node = document.find("sources")
    if sources_node is not None:
        document.remove(sources_node)
    ET.ElementTree(document).write(report, encoding="utf-8", xml_declaration=True)
    return relevant


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--working-directory", default=".")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 100:
            raise ValueError("Threshold must be between 0 and 100")
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command or not any("{report}" in part or "{report_dir}" in part for part in command):
            raise ValueError("Supply a coverage command containing {report} or {report_dir} after --")
        cwd = Path(args.working_directory).resolve()
        root = Path(git(cwd, "rev-parse", "--show-toplevel").strip()).resolve()
        sources = [safe_relative(source) for source in args.source]
        head = git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
        base = git(root, "rev-parse", "--verify", "--end-of-options", args.base + "^{commit}").strip()
        base = git(root, "merge-base", base, head).strip()
        if git(root, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("Commit tracked changes before running this comparison")
        untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
        if any(path and in_scope(path, sources) for path in untracked):
            raise ValueError("Untracked source files are outside the committed comparison")
        changes = changed_lines(root, base, sources)
        if not changes:
            print("not_applicable: no added or modified lines in the selected source scope")
            return 0
        with tempfile.TemporaryDirectory(prefix="changed-coverage-") as directory:
            report = Path(directory) / "cobertura-coverage.xml"
            result = subprocess.run([part.replace("{report}", str(report)).replace("{report_dir}", directory) for part in command], cwd=cwd)
            if result.returncode:
                raise ValueError("Coverage command failed with exit status " + str(result.returncode))
            if git(root, "rev-parse", "HEAD").strip() != head or git(root, "status", "--porcelain", "--untracked-files=no"):
                raise ValueError("Coverage command changed the tracked comparison")
            untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
            if any(path and in_scope(path, sources) for path in untracked):
                raise ValueError("Coverage command created untracked source files")
            relevant = validate_report(report, root, cwd, changes)
            if not relevant:
                print("not_applicable: producer reports no executable changed lines; no percentage applies")
                return 0
            summary = Path(directory) / "diff-cover.json"
            result = subprocess.run(["diff-cover", str(report), "--compare-branch=" + base,
                                     "--fail-under=" + str(args.threshold), "--json-report=" + str(summary),
                                     "--include", *(glob.escape(path) for path in changes)], cwd=root)
            if result.returncode == 0:
                counts = json.loads(summary.read_text())
                if not isinstance(counts, dict) or counts.get("total_num_lines") != relevant:
                    raise ValueError("diff-cover did not measure every reported changed line in scope")
            return result.returncode if result.returncode >= 0 else 2
    except (ValueError, OSError, ET.ParseError, SyntaxError) as exc:
        print("changed coverage: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
