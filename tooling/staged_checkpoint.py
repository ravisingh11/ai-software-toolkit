#!/usr/bin/env python3
"""Explicit, bounded scans of exact staged files. No hook or policy changes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from assurance import canonical, sha256_file, validate_receipt, verify_receipt  # noqa: E402
from checkpoints import git, index_state, plan, trusted_module  # noqa: E402

_PRODUCER = trusted_module("tooling/produce_proof_evidence.py", "produce.py")

TOOLS = {
    "custom-static-analysis": {"provider": "semgrep-ce", "binary": "semgrep", "version": _PRODUCER.SEMGREP_VERSION,
                               "image": _PRODUCER.SEMGREP_IMAGE},
    "secret-detection": {"provider": "gitleaks", "binary": "gitleaks", "version": _PRODUCER.GITLEAKS_VERSION,
                         "image": _PRODUCER.GITLEAKS_IMAGE},
}
CONFIG_FILES = {".proof/semgrep-rules.yml", ".gitleaks.toml", ".gitleaksignore", ".semgrepignore", ".gitignore",
                ".proof/policy.yaml", ".proof/providers.yaml", ".proof/profiles.yaml", ".proof/control-catalog.yaml"}
MAX_SNAPSHOT = 128 * 1024 * 1024


def configuration_digest(entries: list[dict]) -> str:
    return hashlib.sha256(canonical([entry for entry in entries if entry["path"] in CONFIG_FILES])).hexdigest()


def provider_digest() -> str:
    return hashlib.sha256(canonical(TOOLS)).hexdigest()


def snapshot_matches(snapshot: Path, entries: list[dict]) -> bool:
    paths = list(snapshot.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths):
        return False
    if {path.relative_to(snapshot).as_posix() for path in paths if path.is_file()} != {entry["path"] for entry in entries}:
        return False
    for entry in entries:
        data = (snapshot / entry["path"]).read_bytes()
        oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False).hexdigest()
        if oid != entry["oid"]:
            return False
    return True


def materialize(target: Path, entries: list[dict], destination: Path) -> None:
    """Read blobs directly; never run filters, checkout hooks or Git write-tree."""
    ids = [entry["oid"] for entry in entries]
    sizes = git(target, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                input_data=("\n".join(ids) + "\n").encode(), binary=True) if ids else b""
    metadata = [line.split() for line in sizes.splitlines()]
    if len(metadata) != len(entries) or any(len(item) != 3 or item[1] != b"blob" for item in metadata):
        raise ValueError("Index object unavailable")
    if sum(int(item[2]) for item in metadata) > MAX_SNAPSHOT:
        raise ValueError("Staged snapshot exceeds bounded size")
    content = git(target, "cat-file", "--batch", input_data=("\n".join(ids) + "\n").encode(), binary=True) if ids else b""
    offset = 0
    for entry, item in zip(entries, metadata):
        end = content.find(b"\n", offset)
        if end < 0 or content[offset:end].split() != item:
            raise ValueError("Git blob response changed or malformed")
        offset = end + 1
        size = int(item[2])
        blob = content[offset:offset + size]
        if len(blob) != size or content[offset + size:offset + size + 1] != b"\n":
            raise ValueError("Incomplete index blob")
        offset += size + 1
        path = destination / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        path.chmod(0o755 if entry["mode"] == "100755" else 0o644)
    if offset != len(content):
        raise ValueError("Unexpected index blob response")


def run_command(command: list[str], cwd: Path, environment: dict) -> tuple[int, str]:
    try:
        result = subprocess.run(command, cwd=cwd, env=environment, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=180)
        return result.returncode, result.stdout[:65536]
    except (OSError, subprocess.TimeoutExpired):
        return 125, ""


def scan(identifier: str, tool: dict, snapshot: Path, output: Path) -> dict:
    """Only redacted/bounded outcome metadata is retained, never source findings."""
    result = {"check": identifier, "provider": tool["provider"], "status": "blocked", "reason": "Pinned scanner unavailable or incomplete."}
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL") if key in os.environ}
    environment.update(SEMGREP_SEND_METRICS="off", SEMGREP_ENABLE_VERSION_CHECK="0", SEMGREP_SETTINGS_FILE=str(output / "settings.yml"),
                       SEMGREP_LOG_FILE=str(output / "semgrep.log"), XDG_CONFIG_HOME=str(output / "config"), XDG_CACHE_HOME=str(output / "cache"))
    binary = shutil.which(tool["binary"])
    docker = False
    if binary:
        version_arg = "--version" if tool["provider"] == "semgrep-ce" else "version"
        code, version = run_command([binary, version_arg], snapshot, environment)
        versions = re.findall(r"\b\d+\.\d+\.\d+\b", version)
        if code != 0 or versions != [tool["version"]]:
            result["reason"] = "Host scanner version does not match the pinned version."
            return result
        prefix = [binary]
        report_path, source_path = str(output / "findings.json"), "."
        rules = ".proof/semgrep-rules.yml"
    elif shutil.which("docker"):
        docker = True
        prefix = [shutil.which("docker"), "--config", str(output / "docker-config"), "run", "--rm", "--pull", "never", "--network", "none",
                  "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", str(os.getuid()) + ":" + str(os.getgid()),
                  "-v", str(snapshot) + ":/src:ro", "-v", str(output) + ":/out", "-w", "/src"]
        if tool["provider"] == "semgrep-ce":
            prefix += ["-e", "SEMGREP_SETTINGS_FILE=/out/settings.yml", "-e", "SEMGREP_LOG_FILE=/out/semgrep.log", "-e", "SEMGREP_SEND_METRICS=off", "-e", "SEMGREP_ENABLE_VERSION_CHECK=0"]
        prefix += [tool["image"]]
        if tool["provider"] == "semgrep-ce":
            prefix += ["semgrep"]
        report_path, source_path, rules = "/out/findings.json", "/src", "/src/.proof/semgrep-rules.yml"
    else:
        return result
    if tool["provider"] == "semgrep-ce":
        if not (snapshot / ".proof/semgrep-rules.yml").is_file():
            result["reason"] = "Semgrep rules are absent from staged contents."
            return result
        command = [*prefix, "scan", "--error", "--json", "--metrics", "off", "--disable-version-check", "--config", rules,
                   "--exclude", ".proof/semgrep-tests/fixtures", "--exclude", "security/semgrep/tests/fixtures", "--output", report_path, source_path]
    else:
        command = [*prefix, "dir", "--redact", "--no-banner", "--report-format", "json", "--report-path", report_path, source_path]
    code, _ = run_command(command, snapshot, environment)
    path = output / "findings.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        result["reason"] = "Scanner did not retain a bounded valid report."
        return result
    try:
        report = json.loads(path.read_text())
        findings = report.get("results") if tool["provider"] == "semgrep-ce" and isinstance(report, dict) else report
        errors = report.get("errors", []) if tool["provider"] == "semgrep-ce" and isinstance(report, dict) else []
        if not isinstance(findings, list) or not isinstance(errors, list) or errors or code not in (0, 1) or (code == 0 and findings) or (code == 1 and not findings):
            raise ValueError("Incomplete or inconsistent scanner report")
    except (OSError, ValueError, TypeError):
        result["reason"] = "Scanner report is malformed, incomplete or inconsistent with exit status."
        return result
    result.update(status="failed" if findings else "passed", reason=f"{len(findings)} findings in exact staged snapshot.")
    result["recorded_execution"] = {"tool_version": tool["version"], "image": tool["image"] if docker else None,
                                    "exit_code": code, "finding_count": len(findings), "scope": "staged-filesystem", "raw_findings_retained": False}
    return result


def run(target: Path, receipt_path: Path | None = None) -> dict:
    tree, entries = index_state(target)
    planning = plan(target, "pre-commit")
    if not planning["checks"]:
        raise ValueError("Valid installed policy and providers are required before scanning")
    staged = {entry["path"]: entry for entry in entries}
    for name in (".proof/policy.yaml", ".proof/providers.yaml", ".proof/profiles.yaml", ".proof/control-catalog.yaml"):
        if name not in staged:
            raise ValueError("Assurance configuration must be present in staged contents")
        # Selection and rules must describe the proposed snapshot, not an unstaged policy edit.
        blob = git(target, "cat-file", "blob", staged[name]["oid"], binary=True)
        if (target / name).is_symlink() or (target / name).read_bytes() != blob:
            raise ValueError("Assurance configuration differs between index and working tree")
    if receipt_path is None:
        parent = target / ".artifacts/checkpoints"
        if parent.exists() and (parent.is_symlink() or not parent.resolve().is_relative_to(target.resolve())):
            raise ValueError("Unsafe receipt destination")
        parent.mkdir(parents=True, exist_ok=True)
        receipt_path = Path(tempfile.mkdtemp(prefix="pre-commit-", dir=parent)) / "receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("Preserve existing receipt; choose a new path")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(tempfile.mkdtemp(prefix="evidence-", dir=receipt_path.parent))
    rows, refs = [], []
    with tempfile.TemporaryDirectory(prefix="ai-toolkit-index-") as temporary:
        snapshot = Path(temporary) / "snapshot"
        snapshot.mkdir()
        materialize(target, entries, snapshot)
        # Read-only source tree; a host producer cannot silently rewrite its scanned files.
        for path in snapshot.rglob("*"):
            if path.is_file():
                path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
        for identifier, tool in TOOLS.items():
            selected = next((row for row in planning["checks"] if row["id"] == identifier), None)
            if not selected or not selected["selected"] or selected["authoritative_provider"] != tool["provider"]:
                continue
            output = Path(temporary) / identifier
            output.mkdir()
            outcome = scan(identifier, tool, snapshot, output)
            execution = outcome.pop("recorded_execution", None)
            if not snapshot_matches(snapshot, entries):
                outcome["status"] = "blocked"
                outcome["reason"] = "Scanner modified isolated snapshot; original contents were not established."
                execution = None
            if execution:
                file = evidence_dir / (tool["provider"] + ".json")
                file.write_text(json.dumps({"index_tree": tree, "configuration_digest": configuration_digest(entries), "execution": execution}, indent=2) + "\n")
                relative = file.relative_to(receipt_path.parent).as_posix()
                outcome["evidence"] = [relative]
                refs.append({"path": relative, "sha256": sha256_file(file), "size": file.stat().st_size})
            rows.append(outcome)
    if not rows:
        rows = [{"check": "pre-commit-snapshot", "provider": "checkpoint-adapters", "status": "not_run", "reason": "No supported staged scanner is selected; nothing was activated."}]
    receipt = {"version": 1, "kind": "checkpoint-receipt", "checkpoint": "pre-commit", "subject": {"type": "git-index", "revision": tree},
               "observed_at": datetime.now(timezone.utc).isoformat(), "context": {"invocation": "explicit:checkpoint-run"},
               "dependencies": {"index_tree": tree, "configuration_digest": configuration_digest(entries), "provider_digest": provider_digest()},
               "results": rows, "evidence_refs": refs}
    validate_receipt(receipt)
    # Refuse overwrite even if another process created the requested file during scans.
    with receipt_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    try:
        current_tree, current_entries = index_state(target)
        expected = {"subject": {"type": "git-index", "revision": current_tree}, "index_tree": current_tree,
                    "configuration_digest": configuration_digest(current_entries), "provider_digest": provider_digest()}
        verified = verify_receipt(receipt_path, expected=expected)
    except (OSError, ValueError, subprocess.SubprocessError):
        verified = verify_receipt(receipt_path)
        verified["invalidation_reasons"].append("current-index-unavailable")
        verified["applicable"] = verified["all_reported_checks_passed"] = False
    verified["receipt_path"] = str(receipt_path)
    return verified
