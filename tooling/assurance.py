#!/usr/bin/env python3
"""Portable integrity contracts for packages and checkpoint receipts.

This module never executes evidence, contacts a platform, or grants authority.
It is also distributed verbatim for application-owned package integrations.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlsplit

VERSION = 1
MAX_DOCUMENT = 2 * 1024 * 1024
MAX_FILES = 20000
MAX_FILE_SIZE = 64 * 1024 * 1024
MAX_PACKAGE_SIZE = 512 * 1024 * 1024
CHECKPOINTS = (
    "coding-finished", "pre-commit", "commit-creation", "post-commit", "pre-push",
    "pr", "pre-merge", "post-merge", "release", "deployment", "runtime",
)
SUBJECTS = {"git-index", "git-commit", "pull-request", "artifact", "environment"}
STATUSES = {"passed", "failed", "blocked", "not_run"}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def read_document(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DOCUMENT:
        raise ValueError("Document must be a bounded regular file")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    if not isinstance(value, dict):
        raise ValueError("Document must be an object")
    return value


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError("Unexpected or missing contract fields")


def _text(value, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("Expected bounded nonempty text")


def _hex(value, length=64):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value):
        raise ValueError("Invalid content identity")


def relative_path(value: str) -> Path:
    _text(value)
    pure = PurePosixPath(value)
    if pure.is_absolute() or value != pure.as_posix() or any(part in {"", ".", ".."} for part in pure.parts) or not pure.parts or "\\" in value or ":" in value or len(pure.parts) > 32:
        raise ValueError("Unsafe or noncanonical relative path")
    return Path(*pure.parts)


def confined_file(root: Path, value: str) -> Path:
    root = root.resolve()
    relative = relative_path(value)
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError("Symlink in evidence or package path")
    if not path.resolve().is_relative_to(root) or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Missing regular file within declared root")
    return path


def validate_manifest(manifest: dict) -> None:
    _object(manifest, {"version", "kind", "source", "build", "configuration", "files"})
    if type(manifest["version"]) is not int or manifest["version"] != VERSION or manifest["kind"] != "package-manifest":
        raise ValueError("Unsupported package manifest contract")
    source = manifest["source"]
    _object(source, {"repository", "revision", "tree"})
    _text(source["repository"])
    url = urlsplit(source["repository"])
    if url.scheme != "https" or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError("Repository must be a credential-free HTTPS identity")
    _hex(source["revision"], 40)
    _hex(source["tree"], 40)
    _object(manifest["build"], {"tool", "version"})
    for value in manifest["build"].values():
        _text(value, 128)
    _object(manifest["configuration"], {"sha256"}, {"path"})
    _hex(manifest["configuration"]["sha256"])
    config_path = manifest["configuration"].get("path", "deploy-config.json")
    relative_path(config_path)
    files = manifest["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("Package requires a bounded nonempty inventory")
    names = set()
    total = 0
    for entry in files:
        _object(entry, {"path", "size", "sha256", "mode"})
        relative_path(entry["path"])
        if entry["path"] in names:
            raise ValueError("Duplicate package member")
        names.add(entry["path"])
        if type(entry["size"]) is not int or not 0 <= entry["size"] <= MAX_FILE_SIZE:
            raise ValueError("Invalid package file size")
        total += entry["size"]
        _hex(entry["sha256"])
        if entry["mode"] not in {"0644", "0755"}:
            raise ValueError("Unsupported package file mode")
    if total > MAX_PACKAGE_SIZE or config_path not in names:
        raise ValueError("Package too large or configuration not inventoried")
    config_entry = next(entry for entry in files if entry["path"] == config_path)
    if config_entry["sha256"] != manifest["configuration"]["sha256"]:
        raise ValueError("Configuration digest disagrees with inventory")


def package_digest(manifest: dict) -> str:
    validate_manifest(manifest)
    return hashlib.sha256(canonical(manifest)).hexdigest()


def verify_package(root: Path, manifest: dict) -> dict:
    validate_manifest(manifest)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Package root must be a real directory")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("Unsupported package member")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != {entry["path"] for entry in manifest["files"]}:
        raise ValueError("Package membership differs from manifest")
    for entry in manifest["files"]:
        path = confined_file(root, entry["path"])
        if path.stat().st_size != entry["size"] or sha256_file(path) != entry["sha256"] or format(stat.S_IMODE(path.stat().st_mode), "04o") != entry["mode"]:
            raise ValueError("Package bytes or mode differ from manifest")
    return {"version": VERSION, "kind": "package-integrity", "valid": True,
            "package_digest": package_digest(manifest), "source": manifest["source"],
            "files_verified": len(actual), "authenticated_build_provenance": False,
            "limits": "Integrity and declared source only; platform identity requires independent verification."}


def _time(value: str) -> datetime:
    _text(value, 64)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Observation time requires timezone")
    return result


def validate_receipt(receipt: dict) -> None:
    _object(receipt, {"version", "kind", "checkpoint", "subject", "observed_at", "context", "dependencies", "results", "evidence_refs"},
            {"expires_at", "skills", "relationships", "platform_requirements"})
    if type(receipt["version"]) is not int or receipt["version"] != VERSION or receipt["kind"] != "checkpoint-receipt" or receipt["checkpoint"] not in CHECKPOINTS:
        raise ValueError("Unsupported checkpoint receipt contract")
    _object(receipt["subject"], {"type", "revision"})
    if receipt["subject"]["type"] not in SUBJECTS:
        raise ValueError("Unsupported checkpoint subject")
    _text(receipt["subject"]["revision"])
    if receipt["checkpoint"] == "pre-commit" and receipt["subject"]["type"] != "git-index":
        raise ValueError("Pre-commit evidence must identify the index")
    if receipt["subject"]["type"] in {"git-index", "git-commit"}:
        _hex(receipt["subject"]["revision"], 40)
    observed = _time(receipt["observed_at"])
    if "expires_at" in receipt and _time(receipt["expires_at"]) <= observed:
        raise ValueError("Expiry must follow observation")
    _object(receipt["context"], {"invocation"}, {"repository", "run_url", "run_id", "run_attempt", "workflow_revision"})
    for value in receipt["context"].values():
        _text(value)
    allowed_dependencies = {"index_tree", "source_revision", "comparison_base", "pr_metadata_revision", "configuration_digest", "provider_digest"}
    if not isinstance(receipt["dependencies"], dict) or set(receipt["dependencies"]) - allowed_dependencies:
        raise ValueError("Unsupported dependency key")
    for key, value in receipt["dependencies"].items():
        _hex(value, 40 if key in {"index_tree", "source_revision", "comparison_base"} else 64)
    results = receipt["results"]
    if not isinstance(results, list) or not 1 <= len(results) <= 100:
        raise ValueError("Receipt requires bounded explicit outcomes")
    names = set()
    for row in results:
        _object(row, {"check", "provider", "status"}, {"reason", "evidence"})
        _text(row["check"], 128)
        _text(row["provider"], 128)
        if row["check"] in names or row["status"] not in STATUSES:
            raise ValueError("Duplicate check or invalid raw outcome")
        names.add(row["check"])
        if row["status"] in {"passed", "failed"}:
            if not isinstance(row.get("evidence"), list) or not 1 <= len(row["evidence"]) <= 20:
                raise ValueError("Completed result requires evidence references")
            for value in row["evidence"]:
                _text(value)
        else:
            _text(row.get("reason"), 1000)
        if "reason" in row:
            _text(row["reason"], 1000)
    refs = receipt["evidence_refs"]
    if not isinstance(refs, list) or len(refs) > 100:
        raise ValueError("Invalid evidence references")
    paths = set()
    for ref in refs:
        _object(ref, {"path", "sha256", "size"})
        relative_path(ref["path"])
        _hex(ref["sha256"])
        if ref["path"] in paths or type(ref["size"]) is not int or not 0 <= ref["size"] <= MAX_FILE_SIZE:
            raise ValueError("Duplicate or oversized evidence reference")
        paths.add(ref["path"])
    for row in results:
        if row["status"] in {"passed", "failed"} and not set(row["evidence"]) <= paths:
            raise ValueError("Completed outcome references unbound evidence")
    skills = receipt.get("skills", [])
    if not isinstance(skills, list) or len(skills) > 50:
        raise ValueError("Invalid skill references")
    for skill in skills:
        _object(skill, {"name", "origin"}, {"revision", "sha256", "execution_evidence"})
        _text(skill["name"], 128)
        if skill["origin"] not in {"toolkit", "local", "external", "human"}:
            raise ValueError("Invalid skill origin")
        if "revision" in skill:
            _text(skill["revision"], 128)
        if "sha256" in skill:
            _hex(skill["sha256"])
        if "execution_evidence" in skill and skill["execution_evidence"] not in paths:
            raise ValueError("Skill execution reference is not bound")
    relationships = receipt.get("relationships", [])
    if not isinstance(relationships, list) or len(relationships) > 50:
        raise ValueError("Invalid handoff relationships")
    for relation in relationships:
        _object(relation, {"relation", "subject", "evidence"})
        if relation["relation"] not in {"prepared", "tested", "merged", "packaged", "published", "uploaded", "deployed", "observed"}:
            raise ValueError("Invalid relationship")
        _object(relation["subject"], {"type", "revision"})
        if relation["subject"]["type"] not in SUBJECTS:
            raise ValueError("Invalid related subject")
        _text(relation["subject"]["revision"])
        if relation["evidence"] not in paths:
            raise ValueError("Relationship requires bound supporting evidence")
    requirements = receipt.get("platform_requirements", [])
    if not isinstance(requirements, list) or len(requirements) > 50:
        raise ValueError("Invalid platform requirements")
    for item in requirements:
        _text(item)


def verify_receipt(path: Path, *, expected: dict | None = None, now: datetime | None = None) -> dict:
    receipt = read_document(path)
    validate_receipt(receipt)
    for ref in receipt["evidence_refs"]:
        evidence = confined_file(path.parent, ref["path"])
        if evidence.stat().st_size != ref["size"] or sha256_file(evidence) != ref["sha256"]:
            raise ValueError("Referenced evidence bytes differ")
    clock = now or datetime.now(timezone.utc)
    reasons = []
    if _time(receipt["observed_at"]) > clock:
        reasons.append("observation-in-future")
    if "expires_at" in receipt and clock >= _time(receipt["expires_at"]):
        reasons.append("expired-observation")
    if receipt["checkpoint"] == "runtime" and "expires_at" not in receipt:
        reasons.append("freshness-unverified")
    for key, value in (expected or {}).items():
        if key == "subject":
            if receipt["subject"] != value:
                reasons.append("subject-mismatch")
        elif key not in receipt["dependencies"] or receipt["dependencies"][key] != value:
            reasons.append(key + "-mismatch")
    for key in receipt["dependencies"]:
        if key not in (expected or {}):
            reasons.append("unverified-dependency:" + key)
    counts = {status: sum(row["status"] == status for row in receipt["results"]) for status in sorted(STATUSES)}
    return {"version": VERSION, "kind": "checkpoint-integrity", "valid": True,
            "receipt_digest": hashlib.sha256(canonical(receipt)).hexdigest(),
            "checkpoint": receipt["checkpoint"], "subject": receipt["subject"],
            "applicable": not reasons, "invalidation_reasons": reasons,
            "all_reported_checks_passed": not reasons and all(row["status"] == "passed" for row in receipt["results"]),
            "status_counts": counts, "results": receipt["results"],
            "platform_requirements": receipt.get("platform_requirements", []),
            "skill_references": receipt.get("skills", []),
            "authenticated_producer": False, "authorization_granted": False,
            "limits": "File integrity and recorded context only. Provider/platform authority and approvals require independent verification; skill references are reported attribution."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    package = sub.add_parser("package-verify")
    package.add_argument("--root", required=True, type=Path)
    package.add_argument("--manifest", required=True, type=Path)
    receipt = sub.add_parser("receipt-verify")
    receipt.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_package(args.root, read_document(args.manifest)) if args.action == "package-verify" else verify_receipt(args.receipt)
        print(json.dumps(result, indent=2))
        return 0 if result.get("all_reported_checks_passed", True) else 1
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({"valid": False, "error": "Invalid or unavailable assurance record; inspect its version, inventory and references."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
