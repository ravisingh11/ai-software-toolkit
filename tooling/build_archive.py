#!/usr/bin/env python3
"""Build the distributable ``ai-toolkit.pyz`` archive and its SHA-256 checksum.

The archive carries the toolkit source subset that installation needs. When
run, it extracts that payload to a per-checksum cache directory and executes
the CLI from there, so ``install.py`` copies real files into the target's
``.guardrails/`` exactly as a source checkout does. Installed repositories
never import code from the archive at evaluation time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipapp
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_NAME = "ai-toolkit.pyz"
PAYLOAD_DIRECTORIES = ("tooling", "guardrails", "policies", "workflows", "security/semgrep", "skills", "pr-review")
EXCLUDED_PARTS = {"__pycache__", ".ruff_cache", "tests", "coverage-support", ".DS_Store"}

LAUNCHER = '''"""ai-toolkit archive launcher: extract the payload once per checksum, then run the CLI."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def archive_path():
    return Path(sys.argv[0]).resolve()


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_root():
    override = os.environ.get("AI_TOOLKIT_CACHE", "").strip()
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    return Path(xdg) / "ai-toolkit" if xdg else Path.home() / ".cache" / "ai-toolkit"


def extracted_root(archive, digest):
    root = cache_root() / digest[:16]
    marker = root / ".complete"
    if marker.is_file():
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="ai-toolkit-", dir=str(root.parent)))
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                name = member.filename
                if not name.startswith("payload/") or member.is_dir():
                    continue
                relative = Path(name[len("payload/"):])
                if relative.is_absolute() or ".." in relative.parts:
                    raise SystemExit("ERROR the archive contains an unsafe path")
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                if relative.suffix in {".sh", ".py"}:
                    destination.chmod(0o755)
        (staging / ".complete").write_text(digest + "\\n", encoding="utf-8")
        if root.exists():
            shutil.rmtree(staging)
        else:
            staging.rename(root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return root


def main():
    archive = archive_path()
    if not zipfile.is_zipfile(archive):
        raise SystemExit("ERROR run this launcher as python3 ai-toolkit.pyz <command>")
    root = extracted_root(archive, checksum(archive))
    command = [sys.executable, str(root / "tooling" / "ai_toolkit"), *sys.argv[1:]]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
'''


def payload_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for directory in PAYLOAD_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part in EXCLUDED_PARTS for part in relative.parts) or path.suffix in {".pyc", ".pyo"}:
                continue
            files.append(path)
    # Semgrep fixtures are installed into the target; keep them even though they sit under tests/.
    fixtures = root / "security" / "semgrep" / "tests" / "fixtures"
    if fixtures.is_dir():
        files.extend(sorted(path for path in fixtures.rglob("*") if path.is_file()))
    # The installer validates providers with the source validator; keep validators' tests out but the module in.
    return sorted(set(files))


def revision(root: Path = ROOT) -> str:
    if shutil.which("git") and (root / ".git").exists():
        completed = subprocess.run(["git", "-C", str(root), "describe", "--tags", "--always", "--dirty"], text=True, capture_output=True)
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout.strip()
    sys.path.insert(0, str(root / "tooling"))
    from ai_toolkit import VERSION  # noqa: E402

    return VERSION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output: Path, *, root: Path = ROOT, build_revision: str | None = None) -> tuple[Path, Path]:
    build_revision = build_revision or revision(root)
    with tempfile.TemporaryDirectory(prefix="ai-toolkit-build-") as temporary:
        staging = Path(temporary) / "app"
        payload = staging / "payload"
        for path in payload_files(root):
            destination = payload / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        metadata = payload / "tooling" / "ai_toolkit" / "BUILD.json"
        metadata.write_text(json.dumps({
            "revision": build_revision,
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, indent=2) + "\n", encoding="utf-8")
        (staging / "__main__.py").write_text(LAUNCHER, encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(staging, output, interpreter="/usr/bin/env python3", compressed=True)
    checksum_path = output.with_name(output.name + ".sha256")
    checksum_path.write_text(f"{sha256_file(output)}  {output.name}\n", encoding="utf-8")
    return output, checksum_path


def verify(archive: Path) -> bool:
    checksum_path = archive.with_name(archive.name + ".sha256")
    try:
        expected = checksum_path.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        return False
    return expected == sha256_file(archive)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / ARCHIVE_NAME)
    parser.add_argument("--revision", help="override the recorded toolkit revision")
    parser.add_argument("--verify", type=Path, metavar="ARCHIVE", help="verify an archive against its .sha256 file and exit")
    args = parser.parse_args()
    if args.verify:
        if verify(args.verify):
            print(f"OK {args.verify}")
            return 0
        print(f"MISMATCH {args.verify}", file=sys.stderr)
        return 1
    archive, checksum = build(args.output, build_revision=args.revision)
    print(f"Built {archive} ({archive.stat().st_size} bytes)\nChecksum {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
