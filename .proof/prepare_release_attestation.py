#!/usr/bin/env python3
"""Download and hash exact published assets for a release-verification attestation.

This verifies publication identity; it does not claim the original build ran here.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote


PREDICATE_TYPE = "https://github.com/ravisingh11/ai-software-toolkit/attestations/release-artifact-verification/v1"


def api(path: str) -> dict:
    value = json.loads(subprocess.check_output(["gh", "api", path], timeout=60))
    if not isinstance(value, dict):
        raise ValueError("GitHub response is not an object")
    return value


def prepare(repository: str, tag: str, pattern: str, output: Path) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not tag or not pattern:
        raise ValueError("repository, tag and asset pattern are required")
    release = api(f"repos/{repository}/releases/tags/{quote(tag, safe='')}")
    if release.get("draft") is not False or release.get("tag_name") != tag:
        raise ValueError("expected the requested published release")
    tag_ref = api(f"repos/{repository}/git/ref/tags/{quote(tag, safe='')}")["object"]
    ref = tag_ref
    for _ in range(5):
        if not re.fullmatch(r"[a-f0-9]{40}", ref.get("sha", "")):
            raise ValueError("invalid tag object")
        if ref.get("type") == "commit":
            break
        if ref.get("type") != "tag":
            raise ValueError("tag does not resolve to a commit")
        ref = api(f"repos/{repository}/git/tags/{ref['sha']}")["object"]
    if ref.get("type") != "commit":
        raise ValueError("tag nesting exceeds the supported bound")
    if not isinstance(release.get("assets"), list) or any(not isinstance(asset, dict) for asset in release["assets"]):
        raise ValueError("invalid release inventory")
    selected = [asset for asset in release.get("assets", []) if fnmatch.fnmatchcase(asset.get("name", ""), pattern)]
    if not selected or len(selected) > 100:
        raise ValueError("asset pattern must match between 1 and 100 uploaded files")
    assets = output / "assets"
    assets.mkdir(parents=True, exist_ok=False)
    records = []
    total_bytes = 0
    for asset in selected:
        name = asset.get("name", "")
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+-]{0,199}", name):
            raise ValueError("release asset has an unsafe filename")
        if type(asset.get("id")) is not int or asset["id"] <= 0:
            raise ValueError("invalid release asset identity")
        if type(asset.get("size")) is not int or not 0 < asset["size"] <= 4 * 1024**3:
            raise ValueError("release asset is empty or exceeds 4 GiB")
        total_bytes += asset["size"]
        if total_bytes > 4 * 1024**3:
            raise ValueError("selected assets exceed the 4 GiB total budget")
        expected = asset.get("digest")
        if not isinstance(expected, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", expected):
            raise ValueError("release asset lacks a GitHub SHA-256 digest")
        path = assets / name
        with path.open("xb") as destination:
            subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream",
                            f"repos/{repository}/releases/assets/{asset['id']}"],
                           stdout=destination, check=True, timeout=900)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = "sha256:" + digest.hexdigest()
        if actual != expected or path.stat().st_size != asset["size"]:
            raise ValueError("downloaded asset differs from GitHub metadata")
        records.append({"name": name, "sha256": digest.hexdigest(), "bytes": asset["size"]})
    # Refuse a release/tag changed during retrieval; older mutable releases need this too.
    latest = api(f"repos/{repository}/releases/tags/{quote(tag, safe='')}")
    identity = lambda record: (record.get("id"), record.get("draft"), record.get("tag_name"), record.get("updated_at"),
                               sorted((asset.get("id"), asset.get("name"), asset.get("size"), asset.get("digest")) for asset in record.get("assets", [])))
    if identity(latest) != identity(release) or api(f"repos/{repository}/git/ref/tags/{quote(tag, safe='')}")["object"] != tag_ref:
        raise ValueError("release or tag changed during retrieval")
    predicate = {"version": 1, "kind": "release-artifact-verification",
                 "repository": repository, "release_id": release["id"], "tag": tag,
                 "source_commit": ref["sha"], "assets": records,
                 "scope": "Downloaded bytes match published release assets; original build execution is not asserted."}
    (output / "predicate.json").write_text(json.dumps(predicate, indent=2) + "\n")
    return predicate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--pattern", default="*")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        predicate = prepare(args.repository, args.tag, args.pattern, args.output)
        print(f"Verified {len(predicate['assets'])} release assets for {predicate['source_commit']}")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"BLOCKED: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
