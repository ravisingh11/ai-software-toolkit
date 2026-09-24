#!/usr/bin/env python3
"""Validate structured QA rows and render the only authoritative Markdown report."""
from collections import Counter
import html
import json
from pathlib import Path
import re
import sys

STATUSES = ("pass", "fail", "blocked", "flaky", "inconclusive")
FAILURE_REPORT = "## QA Report\n\n**Result: FAILED / INCOMPLETE.** No validated passing result is available.\n"


def plain(value, limit, *, required=False):
    if (not isinstance(value, str) or len(value) > limit
            or (required and not value.strip())
            or any(ord(char) < 32 and char not in "\n\r\t" for char in value)):
        raise ValueError("invalid or oversized result text")
    escaped = html.escape(" ".join(value.split()), quote=True)
    return re.sub(r"[\\`*_[\]{}()#!|~@]", lambda match: f"&#{ord(match[0])};", escaped)


def render_results(payload):
    if (not isinstance(payload, dict) or not {"overall", "counts", "rows"} <= payload.keys()
            or payload.keys() - {"overall", "counts", "rows", "action_required"}):
        raise ValueError("summary must contain structured rows, counts, and overall")
    rows, counts = payload["rows"], payload["counts"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("summary must contain 1 to 200 result rows")
    if (not isinstance(counts, dict) or set(counts) != set(STATUSES)
            or any(type(value) is not int or value < 0 for value in counts.values())):
        raise ValueError("counts must contain nonnegative integers for every status")
    measured = Counter()
    lines, evidence_ids = [], []
    for index, row in enumerate(rows, 1):
        required = {"test_case", "app", "persona", "result", "notes"}
        if (not isinstance(row, dict) or not required <= row.keys()
                or row.keys() - required - {"evidence"} or row["result"] not in STATUSES):
            raise ValueError("invalid result row schema or status")
        measured[row["result"]] += 1
        fields = [plain(row[key], limit, required=True) for key, limit in
                  (("test_case", 200), ("app", 80), ("persona", 80))]
        notes = plain(row["notes"], 1000)
        evidence = row.get("evidence", [])
        if (not isinstance(evidence, list) or len(evidence) > 10
                or any(not isinstance(item, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", item)
                       for item in evidence)):
            raise ValueError("invalid evidence references")
        evidence_ids.extend(item for item in evidence if item not in evidence_ids)
        result = {"pass": ":white_check_mark: PASS", "flaky": ":warning: FLAKY"}.get(row["result"], row["result"].upper())
        lines.append(f"| {index} | {' | '.join(fields)} | {result} | {notes} |")
    if any(counts[status] != measured[status] for status in STATUSES):
        raise ValueError("counts contradict result rows")
    overall = next((status for status in ("fail", "blocked", "inconclusive") if measured[status]), "pass")
    if payload["overall"] != overall:
        raise ValueError("overall contradicts result rows")
    actions = payload.get("action_required", [])
    if not isinstance(actions, list) or len(actions) > 20:
        raise ValueError("invalid action-required list")
    actions = [plain(action, 1000, required=True) for action in actions]
    if overall != "pass":
        raise ValueError("QA results are not passing")
    report = ("## QA Report\n\n**Result: PASS**\n\n"
              "| # | Test Case | App | Persona | Result | Notes |\n"
              "| --- | --- | --- | --- | --- | --- |\n" + "\n".join(lines) + "\n")
    if actions:
        report += "\n### Action Required\n\n" + "\n".join(f"- {action}" for action in actions) + "\n"
    if evidence_ids:
        report += "\n<details>\n<summary>Evidence</summary>\n\n"
        report += "\n\n".join(f"<!-- evidence:{item} -->" for item in evidence_ids) + "\n\n</details>\n"
    if len(report.encode("utf-8")) > 60000:
        raise ValueError("rendered report exceeds size limit")
    return report


def validate_results(root):
    root = Path(root)
    source, report = root / "summary.json", root / "report.md"
    if root.is_symlink() or source.is_symlink() or report.is_symlink():
        raise ValueError("result paths must not be symlinks")
    root.mkdir(parents=True, exist_ok=True)
    # Never preserve or read an agent-authored optimistic report after a failure.
    report.write_text(FAILURE_REPORT, encoding="utf-8")
    if source.stat().st_size > 65536:
        raise ValueError("summary exceeds size limit")
    rendered = render_results(json.loads(source.read_text(encoding="utf-8")))
    report.write_text(rendered, encoding="utf-8")
    return rendered


if __name__ == "__main__":
    try:
        validate_results(sys.argv[1] if len(sys.argv) > 1 else "qa-results")
    except (OSError, ValueError) as error:
        sys.exit(f"QA results invalid or incomplete: {error}")
