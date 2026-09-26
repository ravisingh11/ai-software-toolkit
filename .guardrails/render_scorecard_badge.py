#!/usr/bin/env python3
# Guardrails v2 installer-owned runtime.
"""Validate a Guardrails scorecard and render a bounded public status site."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


VALID_STATUSES = {"GREEN": "#2da44e", "ORANGE": "#bf8700", "RED": "#cf222e"}
VALID_DECISIONS = {"allow", "block"}
MAX_MEMBER_BYTES = 64_000
MAX_SOURCE_BYTES = 1_000_000
REVISION_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
RFC3339_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)


def _integer(value: Any, field: str, *, positive: bool = False) -> int:
    if type(value) is not int:  # bool is intentionally excluded
        raise ValueError(f"{field} must be an integer")
    if value < (1 if positive else 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{field} must be {qualifier}")
    return value


def _timestamp(value: str, field: str) -> str:
    if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        normalized = parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise ValueError(f"{field} must be an RFC 3339 timestamp") from error
    rendered = normalized.isoformat(
        timespec="microseconds" if normalized.microsecond else "seconds"
    )
    return rendered.replace("+00:00", "Z")


def _repository(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or not REPOSITORY_PATTERN.fullmatch(value):
        raise ValueError("repository must use OWNER/REPOSITORY format")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ValueError("repository must use OWNER/REPOSITORY format")
    return owner, name


def pages_base_url(repository: str) -> str:
    owner, name = _repository(repository)
    owner_domain = owner.lower()
    if name.lower() == f"{owner_domain}.github.io":
        return f"https://{owner_domain}.github.io/"
    return f"https://{owner_domain}.github.io/{name}/"


def _validate_run_url(
    repository: str, run_id: int, run_attempt: int, run_url: str
) -> str:
    _repository(repository)
    if not isinstance(run_url, str):
        raise ValueError("run_url must be an HTTPS GitHub Actions run-attempt URL")
    parsed = urlsplit(run_url)
    expected_path = f"/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("run_url must match the repository, run ID, and run attempt")
    return run_url


def _bounded_source(source_dir: Path) -> tuple[Path, Path]:
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("source directory must be a real directory")
    entries = list(source_dir.iterdir())
    total_bytes = 0
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise ValueError(
                f"source contains a nested, special, or symlinked entry: {entry.name}"
            )
        size = entry.stat().st_size
        if size > MAX_MEMBER_BYTES:
            raise ValueError(
                f"source member exceeds {MAX_MEMBER_BYTES} bytes: {entry.name}"
            )
        total_bytes += size
        if total_bytes > MAX_SOURCE_BYTES:
            raise ValueError(f"source exceeds {MAX_SOURCE_BYTES} aggregate bytes")
    json_files = sorted(source_dir.glob("scorecard-*.json"))
    if len(json_files) != 1:
        raise ValueError("source must contain exactly one scorecard JSON file")
    json_path = json_files[0]
    markdown_path = json_path.with_suffix(".md")
    if not markdown_path.is_file() or markdown_path.is_symlink():
        raise ValueError("scorecard JSON must have one paired Markdown report")
    if {entry.name for entry in entries} != {json_path.name, markdown_path.name}:
        raise ValueError(
            "source must contain only the paired scorecard JSON and Markdown files"
        )
    return json_path, markdown_path


def _counts(document: dict[str, Any], mode: str) -> dict[str, int]:
    value = document.get(mode)
    if not isinstance(value, dict):
        raise ValueError(f"{mode} must be an object")
    passed = _integer(value.get("passed"), f"{mode}.passed")
    total = _integer(value.get("total"), f"{mode}.total")
    if passed > total:
        raise ValueError(f"{mode}.passed cannot exceed {mode}.total")
    return {"passed": passed, "total": total}


_SCOPE_ROWS = (
    ("files", "max_files", "Counted files"),
    ("added_lines", "max_added_lines", "Added lines"),
    ("changed_lines", "max_changed_lines", "Added + deleted lines"),
    ("max_added_lines_per_file", "max_added_lines_per_file", "Most added lines in one file"),
)
_SCOPE_METRICS = (
    "files", "added_lines", "changed_lines", "max_added_lines_per_file",
    "binary_files", "total_files", "total_added_lines", "total_changed_lines",
    "excluded_files", "excluded_added_lines", "excluded_changed_lines",
    "excluded_binary_files",
)


def _change_scope(document: dict[str, Any]) -> dict[str, Any]:
    # Optional measurements cannot invalidate an otherwise valid scorecard.
    # Malformed data is never rendered as a passing or zero-sized change.
    try:
        return _validated_change_scope(document)
    except (ValueError, TypeError, KeyError):
        return {"availability": "unavailable"}


def _validated_change_scope(document: dict[str, Any]) -> dict[str, Any]:
    """Project only bounded aggregate measurements from the selected producer."""
    unavailable = {"availability": "unavailable"}
    controls = document.get("controls", [])
    if not isinstance(controls, list):
        return unavailable
    rows = [row for row in controls if isinstance(row, dict) and row.get("id") == "change-scope"]
    if not rows:
        return unavailable
    if len(rows) != 1:
        raise ValueError("duplicate change-scope controls")
    row = rows[0]
    provider = row.get("authoritative_provider") or {}
    result = row.get("authoritative_result") or {}
    mode = row.get("effective_mode")
    if (not isinstance(provider, dict) or provider.get("id") != "repository-change-scope"
            or mode not in {"advisory", "enforced"}
            or not isinstance(result, dict)
            or row.get("evidence_status") not in {"passed", "failed"}):
        return unavailable
    scope = result.get("change_scope")
    if scope is None:
        return unavailable
    if not isinstance(scope, dict) or type(scope.get("version")) is not int or scope["version"] != 1:
        raise ValueError("change_scope must use version 1")
    raw_metrics, raw_limits = scope.get("metrics"), scope.get("thresholds")
    if not isinstance(raw_metrics, dict) or not isinstance(raw_limits, dict):
        raise ValueError("change_scope requires metrics and thresholds")
    metrics = {key: _integer(raw_metrics.get(key), f"change_scope.{key}") for key in _SCOPE_METRICS}
    limits = {key: _integer(raw_limits.get(key), f"change_scope.{key}", positive=True) for _, key, _ in _SCOPE_ROWS}
    if any(value > 2**53 - 1 for value in (*metrics.values(), *limits.values())):
        raise ValueError("change_scope measurements exceed the supported bound")
    for key in ("files", "added_lines", "changed_lines"):
        if metrics[f"total_{key}"] != metrics[key] + metrics[f"excluded_{key}"]:
            raise ValueError("change_scope aggregate totals are inconsistent")
    for prefix in ("", "excluded_"):
        files = metrics[f"{prefix}files"]
        binary = metrics[f"{prefix}binary_files"]
        added = metrics[f"{prefix}added_lines"]
        changed = metrics[f"{prefix}changed_lines"]
        if binary > files or added > changed or (files == binary and changed != 0):
            raise ValueError("change_scope measurements are inconsistent")
    maximum = metrics["max_added_lines_per_file"]
    text_files = metrics["files"] - metrics["binary_files"]
    if maximum > metrics["added_lines"] or metrics["added_lines"] > maximum * text_files:
        raise ValueError("change_scope per-file measurements are inconsistent")
    exceeded = any(metrics[key] > limits[limit] for key, limit, _ in _SCOPE_ROWS)
    status = "failed" if exceeded else "passed"
    if result.get("status") != status or row.get("evidence_status") != status:
        raise ValueError("change_scope status does not match its measurements")
    return {"availability": "available", "mode": mode, "status": status,
            "metrics": metrics, "thresholds": limits}


def _scope_markdown(scope: dict[str, Any]) -> str:
    title = "\n## PR Size · Files & LOC\n\n"
    if scope["availability"] != "available":
        return title + "Measurements unavailable. This source does not contain validated PR size measurements.\n"
    metrics, limits = scope["metrics"], scope["thresholds"]
    meaning = "Advisory — warns only; does not block the policy decision." if scope["mode"] == "advisory" else "Enforced — exceeding a limit blocks the policy decision."
    lines = [title + meaning, "", "| Measurement | Counted | Limit | Result |", "| --- | ---: | ---: | --- |"]
    for key, limit, label in _SCOPE_ROWS:
        state = "Above limit" if metrics[key] > limits[limit] else "Within limit"
        lines.append(f"| {label} | {metrics[key]} | {limits[limit]} | {state} |")
    lines += ["", f"Total: {metrics['total_files']} files; {metrics['total_added_lines']} added lines; {metrics['total_changed_lines']} added + deleted lines.",
              f"Excluded: {metrics['excluded_files']} files; {metrics['excluded_added_lines']} added lines; {metrics['excluded_changed_lines']} added + deleted lines.",
              f"Binary files: {metrics['binary_files']} counted; {metrics['excluded_binary_files']} excluded. Binary contents have no line count."]
    return "\n".join(lines) + "\n"


def _scope_html(scope: dict[str, Any]) -> str:
    heading = '<section class="scope-panel" aria-labelledby="size-title"><p class="eyebrow">Change scope</p><h2 id="size-title">PR Size · Files &amp; LOC</h2>'
    if scope["availability"] != "available":
        return heading + '<p><strong>Measurements unavailable</strong></p><p>This source does not contain validated PR size measurements. No size verdict is available; missing measurements are not a pass.</p></section>'
    metrics, limits = scope["metrics"], scope["thresholds"]
    advisory = scope["mode"] == "advisory"
    meaning = "Advisory · warns only; does not block the policy decision." if advisory else "Enforced · exceeding a limit blocks the policy decision."
    rows = []
    for key, limit, label in _SCOPE_ROWS:
        exceeded = metrics[key] > limits[limit]
        tone = ("caution" if advisory else "danger") if exceeded else "good"
        state = "Above limit" if exceeded else "Within limit"
        rows.append(f'<tr><th scope="row">{label}</th><td>{metrics[key]:,}</td><td>{limits[limit]:,}</td><td><span class="size-result {tone}">{state}</span></td></tr>')
    return heading + f'''<p class="scope-mode">{meaning}</p>
<div class="size-table-wrap" role="region" aria-label="PR size measurements" tabindex="0"><table class="size-table"><caption>Counted changes compared with the configured limits</caption><thead><tr><th scope="col">Measurement</th><th scope="col">Counted</th><th scope="col">Limit</th><th scope="col">Result</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<div class="scope-totals"><p><strong>Total diff</strong><br>{metrics['total_files']:,} files · {metrics['total_added_lines']:,} added lines · {metrics['total_changed_lines']:,} added + deleted lines</p><p><strong>Excluded from limits</strong><br>{metrics['excluded_files']:,} files · {metrics['excluded_added_lines']:,} added lines · {metrics['excluded_changed_lines']:,} added + deleted lines</p></div>
<p class="size-footnote">Counted changes exclude the configured path patterns. Binary files: {metrics['binary_files']:,} counted; {metrics['excluded_binary_files']:,} excluded. Binary contents have no line count. File paths are not published.</p></section>'''


def _validated_scorecard(source_dir: Path) -> dict[str, Any]:
    json_path, _ = _bounded_source(source_dir)
    try:
        document = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"invalid scorecard JSON: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("scorecard JSON must contain an object")
    if document.get("version") != 2 or type(document.get("version")) is not int:
        raise ValueError("scorecard version must be 2")
    if document.get("operation") != "change":
        raise ValueError("scorecard operation must be change")
    status = document.get("status")
    decision = document.get("decision")
    if not isinstance(status, str) or status not in VALID_STATUSES:
        raise ValueError("scorecard status must be GREEN, ORANGE, or RED")
    if not isinstance(decision, str) or decision not in VALID_DECISIONS:
        raise ValueError("scorecard decision must be allow or block")
    subject = document.get("subject")
    if not isinstance(subject, dict) or subject.get("type") != "git-commit":
        raise ValueError("scorecard subject must be a git commit")
    revision = subject.get("revision")
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise ValueError(
            "scorecard revision must be an exact lowercase 40-character SHA"
        )
    enforced = _counts(document, "enforced")
    advisory = _counts(document, "advisory")
    passed = enforced["passed"] + advisory["passed"]
    total = enforced["total"] + advisory["total"]
    if total == 0:
        raise ValueError("scorecard must contain at least one active control")
    enforced_miss = enforced["passed"] < enforced["total"]
    advisory_miss = advisory["passed"] < advisory["total"]
    expected_status = "RED" if enforced_miss else "ORANGE" if advisory_miss else "GREEN"
    expected_decision = "block" if expected_status == "RED" else "allow"
    if status != expected_status or decision != expected_decision:
        raise ValueError(
            "scorecard status and decision are inconsistent with aggregate counts"
        )
    return {
        "status": status,
        "decision": decision,
        "enforced": enforced,
        "advisory": advisory,
        "passed": passed,
        "total": total,
        "subject_revision": revision,
        "change_scope": _change_scope(document),
    }


def inspect_scorecard(source_dir: Path) -> dict[str, object]:
    """Return the normalized trusted fields needed to validate a source artifact."""
    return dict(_validated_scorecard(Path(source_dir)))


def _write_atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _public_metadata(
    inspected: dict[str, Any],
    repository: str,
    run_id: int,
    run_attempt: int,
    run_url: str,
    source_run_created_at: str,
    expected_revision: str,
) -> dict[str, Any]:
    published_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    passed = inspected["passed"]
    total = inspected["total"]
    return {
        "version": 1,
        "operation": "change",
        "label": "Latest PR Scorecard",
        "status": inspected["status"],
        "decision": inspected["decision"],
        "message": f"{inspected['status']} {passed}/{total}",
        "repository": repository,
        "source_run_id": run_id,
        "source_run_attempt": run_attempt,
        "source_run_url": run_url,
        "source_run_created_at": source_run_created_at,
        "published_at": published_at,
        "subject_digest": f"sha256:{hashlib.sha256(expected_revision.encode()).hexdigest()}",
        "passed": passed,
        "total": total,
        "enforced": inspected["enforced"],
        "advisory": inspected["advisory"],
        "pages_url": pages_base_url(repository),
        "change_scope": inspected["change_scope"],
    }


def _svg(metadata: dict[str, Any]) -> str:
    label = str(metadata["label"])
    message = str(metadata["message"])
    label_width = 128
    message_width = max(88, len(message) * 8 + 20)
    total_width = label_width + message_width
    description = html.escape(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")), quote=True
    )
    safe_label = html.escape(label)
    safe_message = html.escape(message)
    color = VALID_STATUSES[str(metadata["status"])]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{safe_label}: {safe_message}">
  <title>{safe_label}: {safe_message}</title>
  <desc>{description}</desc>
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
  <clipPath id="r"><rect width="{total_width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)"><rect width="{label_width}" height="20" fill="#555"/><rect x="{label_width}" width="{message_width}" height="20" fill="{color}"/><rect width="{total_width}" height="20" fill="url(#s)"/></g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11"><text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{safe_label}</text><text x="{label_width / 2}" y="14">{safe_label}</text><text x="{label_width + message_width / 2}" y="15" fill="#010101" fill-opacity=".3">{safe_message}</text><text x="{label_width + message_width / 2}" y="14">{safe_message}</text></g>
</svg>
"""


def _markdown(metadata: dict[str, Any]) -> str:
    return f"""# Latest PR Scorecard

![{metadata["message"]}](guardrails-badge.svg)

| Field | Value |
| --- | --- |
| Repository | {metadata["repository"]} |
| Operation | {metadata["operation"]} |
| Status | {metadata["status"]} |
| Active controls | {metadata["passed"]}/{metadata["total"]} passed |
| Enforced | {metadata["enforced"]["passed"]}/{metadata["enforced"]["total"]} passed |
| Advisory | {metadata["advisory"]["passed"]}/{metadata["advisory"]["total"]} passed |
| Source run | [{metadata["source_run_id"]} attempt {metadata["source_run_attempt"]}]({metadata["source_run_url"]}) |
| Source created | {metadata["source_run_created_at"]} |
| Published | {metadata["published_at"]} |
| Subject digest | {metadata["subject_digest"]} |
{_scope_markdown(metadata["change_scope"])}
"""


_REPORT_CSS = """
:root{color-scheme:light;--ink:#182b32;--muted:#52636b;--line:#dbe3e4;
  --paper:#fff;--canvas:#f4f7f7;--accent:#155e63;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--canvas);color:var(--ink);font-size:15px;line-height:1.6}
a{color:var(--accent);text-underline-offset:4px}
a:hover{text-decoration-thickness:2px}
a:focus-visible,summary:focus-visible{outline:3px solid #227b92;outline-offset:5px;border-radius:3px}
.skip-link{position:absolute;left:16px;top:-80px;background:var(--paper);padding:12px;z-index:1}
.skip-link:focus{top:12px}
.shell{width:min(1080px,100% - 64px);margin-inline:auto}
.topbar{background:var(--paper);border-bottom:1px solid var(--line)}
.topbar .shell{display:flex;justify-content:space-between;align-items:center;gap:24px;min-height:82px;padding-block:16px}
.brand{display:flex;align-items:center;gap:12px;min-width:0}
.brand-mark{display:grid;place-items:center;width:36px;height:40px;flex-shrink:0;background:var(--accent);color:#fff;font-weight:750;border-radius:9px 9px 16px 16px}
.brand-name{display:block;font-size:16px;font-weight:750;letter-spacing:-.3px}
.repository{display:block;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.repo-link{font-size:13px;font-weight:600;white-space:nowrap}
main{padding-block:48px 36px}
.eyebrow{margin:0 0 8px;color:var(--accent);font-size:11px;font-weight:750;letter-spacing:1.7px;text-transform:uppercase}
h1{margin:0;font-size:clamp(30px,4.5vw,42px);font-weight:650;line-height:1.2;letter-spacing:-1.6px}
.intro{margin:12px 0 28px;color:var(--muted);max-width:680px;font-size:16px}
.good{--tone:#216341;--wash:#eef8f1;--edge:#c6e1cf}
.caution{--tone:#815407;--wash:#fff7e8;--edge:#ecd5a7}
.danger{--tone:#a02d36;--wash:#fff1f2;--edge:#ebc5c9}
.neutral{--tone:#52636b;--wash:#f2f5f5;--edge:var(--line)}
.status-panel{display:flex;justify-content:space-between;align-items:center;gap:24px;padding:25px 28px;border:1px solid var(--edge);border-left:4px solid var(--tone);border-radius:12px;background:var(--wash);margin-bottom:22px}
.status-label{display:flex;align-items:center;gap:8px;color:var(--tone);font-size:12px;font-weight:800;letter-spacing:1px}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--tone)}
.status-panel h2{font-size:21px;line-height:1.35;letter-spacing:-.4px;margin:7px 0 4px}
.status-panel p{margin:0;color:var(--muted);font-size:13px}
.decision{text-align:right;flex-shrink:0}
.decision dt{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:1px}
.decision dd{color:var(--tone);margin:4px 0 0;font-size:20px;font-weight:750}
.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.metric{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:24px}
.metric h2{margin:0 0 12px;font-size:13px;font-weight:650;color:var(--muted)}
.count{font-size:40px;font-weight:650;line-height:1.2;letter-spacing:-1.5px;font-variant-numeric:tabular-nums}
.count span{font-size:24px;color:var(--muted);font-weight:450;letter-spacing:-.5px}
.count-caption{font-size:12px;color:var(--muted);margin:5px 0 20px}
.track{height:6px;border-radius:5px;background:#e8eeee;overflow:hidden}
.fill{height:100%;background:var(--tone);border-radius:5px}
.metric-note{color:var(--tone);font-size:12px;font-weight:650;margin:10px 0 0}
.scope-panel{margin-top:24px;padding:28px;background:var(--paper);border:1px solid var(--line);border-radius:12px}
.scope-panel h2{margin:0;font-size:24px;letter-spacing:-.5px}
.scope-panel p{color:var(--muted);font-size:13px}
.scope-mode{font-weight:650}
.size-table-wrap{overflow-x:auto}.size-table-wrap:focus-visible{outline:3px solid #227b92;outline-offset:3px}
.size-table{width:100%;border-collapse:collapse;font-size:13px}
.size-table caption{text-align:left;color:var(--muted);padding:8px 0 12px}
.size-table th,.size-table td{text-align:left;padding:13px 10px;border-bottom:1px solid var(--line)}
.size-table thead{background:var(--canvas)}
.size-table td:nth-child(2),.size-table td:nth-child(3){font-variant-numeric:tabular-nums}
.size-result{display:inline-block;white-space:nowrap;padding:3px 9px;border-radius:5px;background:var(--wash);color:var(--tone);font-weight:650}
.scope-totals{display:grid;grid-template-columns:1fr 1fr;gap:20px}.scope-totals strong{color:var(--ink)}
.size-footnote{margin-bottom:0}
.evidence{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:36px;padding:30px;margin-top:24px;background:var(--paper);border:1px solid var(--line);border-radius:12px}
.evidence h2{margin:0 0 8px;font-size:18px;letter-spacing:-.3px}
.evidence p{color:var(--muted);font-size:13px;margin:0 0 20px;max-width:420px}
.button{display:inline-flex;align-items:center;gap:20px;background:var(--accent);color:#fff;border:1px solid var(--accent);border-radius:7px;text-decoration:none;font-size:13px;font-weight:650;padding:10px 16px}
.button:hover{background:#104b50}
.source-facts{margin:0;display:grid;gap:15px;align-content:start}
.source-facts div{display:grid;grid-template-columns:110px minmax(0,1fr);gap:16px}
.source-facts dt{color:var(--muted);font-size:12px}
.source-facts dd{margin:0;font-size:12px;font-weight:550;overflow-wrap:anywhere}
.scope-note{display:flex;gap:12px;padding:20px 2px;color:var(--muted);font-size:12px;line-height:1.7}
.scope-note strong{color:var(--ink);font-weight:650}
.scope-note p{margin:0}
.note-mark{flex-shrink:0;font-size:16px;color:var(--accent)}
details{border-top:1px solid var(--line);padding:18px 0;color:var(--muted);font-size:12px}
summary{cursor:pointer;width:fit-content;font-weight:600}
.digest{margin:14px 0 0}
.digest code{display:block;margin-top:5px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere;color:var(--ink)}
footer{display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding:22px 0 12px;color:var(--muted);font-size:11px}
footer img{display:block;max-width:100%;height:auto}
.formats{display:flex;gap:20px;flex-wrap:wrap;font-size:12px}
@media(max-width:680px){
  .shell{width:calc(100% - 36px)}
  .topbar .shell{gap:12px}.repo-link{font-size:12px}
  main{padding-top:30px}.intro{font-size:14px}
  .status-panel{align-items:flex-start;padding:20px;gap:16px}
  .status-panel h2{font-size:18px}.decision dd{font-size:17px}
  .metrics{grid-template-columns:1fr;gap:12px}
  .scope-panel{padding:20px}.scope-totals{grid-template-columns:1fr;gap:0}
  .size-table{font-size:12px}
  .size-table th,.size-table td{padding:10px 5px}
  .metric{padding:20px}.count-caption{margin-bottom:14px}
  .evidence{grid-template-columns:1fr;gap:26px;padding:22px}
  .source-facts div{grid-template-columns:95px minmax(0,1fr);gap:12px}
  footer{align-items:flex-start;flex-direction:column}
}
@media(max-width:380px){.status-panel{flex-direction:column}.decision{text-align:left;margin:0}}
@media(prefers-reduced-motion:no-preference){a{transition:background-color .15s ease}}
"""


def _html(metadata: dict[str, Any]) -> str:
    safe = {key: html.escape(str(value), quote=True) for key, value in metadata.items()}
    tone, headline = {
        "GREEN": ("good", "All active controls passed"),
        "ORANGE": ("caution", "Advisory controls need attention"),
        "RED": ("danger", "Enforced controls need attention"),
    }[metadata["status"]]
    cards = []
    for label, counts, card_tone in (
        ("Active controls", metadata, tone),
        ("Enforced", metadata["enforced"], "danger"),
        ("Advisory", metadata["advisory"], "caution"),
    ):
        passed, total = counts["passed"], counts["total"]
        percent = passed / total * 100 if total else 0
        if not total:
            card_tone, note = "neutral", "No controls configured"
        elif passed == total:
            card_tone, note = "good", "All passed"
        else:
            note = f"{total - passed} not passed"
        cards.append(f"""<section class="metric {card_tone}" aria-label="{label}">
  <h2>{label}</h2><div class="count">{passed}<span>/{total}</span></div>
  <p class="count-caption">controls passed</p>
  <div class="track" aria-hidden="true"><div class="fill" style="width:{percent:.2f}%"></div></div>
  <p class="metric-note">{note}</p>
</section>""")
    timestamps = {
        key: datetime.fromisoformat(str(metadata[key]).replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .strftime("%d %b %Y · %H:%M:%S UTC")
        for key in ("source_run_created_at", "published_at")
    }
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="Latest published pull-request scorecard for {safe['repository']}: {safe['message']}.">
  <title>Latest PR Scorecard · {safe['repository']}</title>
  <style>{_REPORT_CSS}</style>
</head>
<body>
<a class="skip-link" href="#scorecard">Skip to scorecard</a>
<header class="topbar"><div class="shell">
  <div class="brand"><span class="brand-mark" aria-hidden="true">G</span><div>
    <span class="brand-name">Guardrails</span><span class="repository">{safe['repository']}</span>
  </div></div>
  <a class="repo-link" href="https://github.com/{safe['repository']}">View repository <span aria-hidden="true">↗</span></a>
</div></header>
<main class="shell" id="scorecard">
  <p class="eyebrow">CI evidence / change assessment</p>
  <h1>Latest PR Scorecard</h1>
  <p class="intro">A clear view of the latest published pull-request evaluation.</p>
  <section class="status-panel {tone}" aria-label="Scorecard status">
    <div><div class="status-label"><span class="status-dot" aria-hidden="true"></span>{safe['status']}</div>
      <h2>{headline}</h2><p>The policy decision is based on enforced controls.</p></div>
    <dl class="decision"><dt>Policy decision</dt><dd>{safe['decision'].upper()}</dd></dl>
  </section>
  <div class="metrics">{''.join(cards)}</div>
  {_scope_html(metadata["change_scope"])}
  <section class="evidence" aria-labelledby="evidence-title">
    <div><h2 id="evidence-title">Trace it to the evidence</h2>
      <p>Open the source CI run for the full scorecard, individual controls, and supporting results.</p>
      <a class="button" href="{safe['source_run_url']}">View source CI run <span aria-hidden="true">↗</span></a>
    </div>
    <dl class="source-facts">
      <div><dt>Source run</dt><dd>#{safe['source_run_id']} · attempt {safe['source_run_attempt']}</dd></div>
      <div><dt>Source created</dt><dd><time datetime="{safe['source_run_created_at']}">{timestamps['source_run_created_at']}</time></dd></div>
      <div><dt>Published</dt><dd><time datetime="{safe['published_at']}">{timestamps['published_at']}</time></dd></div>
      <div><dt>Operation</dt><dd>{safe['operation']}</dd></div>
    </dl>
  </section>
  <aside class="scope-note"><span class="note-mark" aria-hidden="true">ⓘ</span>
    <p><strong>A PR snapshot, not an assessment of current main.</strong> Counts show controls with passing evidence.
    “Not passed” includes failed, missing, or unresolved results. Advisory gaps do not block the policy decision;
    repository merge requirements may apply separately.</p>
  </aside>
  <details><summary>Verification details</summary>
    <p class="digest">Subject digest<code>{safe['subject_digest']}</code></p>
  </details>
  <footer><img src="guardrails-badge.svg" alt="{safe['message']}" width="216" height="20">
    <nav class="formats" aria-label="Report formats"><a href="scorecard.json">Summary JSON</a><a href="scorecard.md">Summary Markdown</a></nav>
  </footer>
</main>
</body></html>
"""


def _replace_directory(temporary: Path, output_dir: Path) -> None:
    if output_dir.is_symlink():
        raise OSError("output directory cannot be a symlink")
    if output_dir.exists() and not output_dir.is_dir():
        raise OSError("output path must be a directory")
    backup: Path | None = None
    if output_dir.exists():
        backup = (
            output_dir.parent
            / f".{output_dir.name}.backup-{next(tempfile._get_candidate_names())}"
        )
        os.replace(output_dir, backup)
    try:
        os.replace(temporary, output_dir)
    except Exception:
        if backup is not None and not output_dir.exists():
            os.replace(backup, output_dir)
        raise
    if backup is not None:
        try:
            shutil.rmtree(backup)
        except OSError:
            # The second rename is the publication commit point. Cleanup must
            # never turn a successfully installed output into a failed run.
            pass


def render_badge(
    source_dir: Path,
    output_dir: Path,
    repository: str,
    run_id: int,
    run_attempt: int,
    run_url: str,
    source_run_created_at: str,
    expected_revision: str,
) -> dict[str, object]:
    """Render a validated scorecard into a bounded, static public projection."""
    inspected = _validated_scorecard(Path(source_dir))
    _repository(repository)
    run_id = _integer(run_id, "run_id", positive=True)
    run_attempt = _integer(run_attempt, "run_attempt", positive=True)
    run_url = _validate_run_url(repository, run_id, run_attempt, run_url)
    source_run_created_at = _timestamp(source_run_created_at, "source_run_created_at")
    if not isinstance(expected_revision, str) or not REVISION_PATTERN.fullmatch(
        expected_revision
    ):
        raise ValueError(
            "expected_revision must be an exact lowercase 40-character SHA"
        )
    if inspected["subject_revision"] != expected_revision:
        raise ValueError("scorecard revision does not match expected revision")

    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent)
    )
    try:
        metadata = _public_metadata(
            inspected,
            repository,
            run_id,
            run_attempt,
            run_url,
            source_run_created_at,
            expected_revision,
        )
        (temporary / "guardrails-badge.svg").write_text(
            _svg(metadata), encoding="utf-8"
        )
        (temporary / "scorecard.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (temporary / "scorecard.md").write_text(_markdown(metadata), encoding="utf-8")
        (temporary / "index.html").write_text(_html(metadata), encoding="utf-8")
        _replace_directory(temporary, output_dir)
        return metadata
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a bounded public Guardrails scorecard badge"
    )
    parser.add_argument("--source-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect-output", type=Path)
    mode.add_argument("--output-dir", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--run-attempt", type=int)
    parser.add_argument("--run-url")
    parser.add_argument("--source-run-created-at")
    parser.add_argument("--expected-revision")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.inspect_output is not None:
            inspected = inspect_scorecard(args.source_dir)
            _write_atomic_text(
                args.inspect_output,
                json.dumps(inspected, indent=2, sort_keys=True) + "\n",
            )
            return 0
        required = {
            "repository": args.repository,
            "run_id": args.run_id,
            "run_attempt": args.run_attempt,
            "run_url": args.run_url,
            "source_run_created_at": args.source_run_created_at,
            "expected_revision": args.expected_revision,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"rendering requires: {', '.join(missing)}")
        metadata = render_badge(args.source_dir, args.output_dir, **required)
        print(
            f"Published badge input: {metadata['status']} {metadata['passed']}/{metadata['total']}"
        )
        return 0
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"ERROR runtime: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
