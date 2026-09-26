#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
ABSOLUTE_PATH_PATTERN = re.compile(r"(/Users/|/private/|\\\\Users\\\\)")
REFERENCE_PATTERN = re.compile(r"`([^`]+/(?:references|scripts)/[^`]+)`")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        fail(f"{path.relative_to(ROOT)} is missing opening frontmatter delimiter")
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        fail(f"{path.relative_to(ROOT)} is missing closing frontmatter delimiter")

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            fail(f"{path.relative_to(ROOT)} has invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        metadata[key] = value.strip().strip('"')

    allowed = {"name", "description"}
    extra = sorted(set(metadata) - allowed)
    if extra:
        fail(f"{path.relative_to(ROOT)} has nonstandard frontmatter keys: {', '.join(extra)}")
    if not metadata.get("name"):
        fail(f"{path.relative_to(ROOT)} is missing frontmatter name")
    if not metadata.get("description"):
        fail(f"{path.relative_to(ROOT)} is missing frontmatter description")
    if metadata["name"] != path.parent.name:
        fail(f"{path.relative_to(ROOT)} name does not match folder {path.parent.name}")
    return metadata


def validate_references(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for match in REFERENCE_PATTERN.finditer(text):
        raw = match.group(1).split()[0]
        candidate = (path.parent / raw).resolve()
        if not candidate.exists():
            fail(f"{path.relative_to(ROOT)} references missing file {raw}")


ACTION_SKILLS = ("fix-ci", "generate-unit-tests", "fix-security-finding", "dependency-upgrade", "address-pr-findings")
SUPPORTED_CLIENTS = ("codex", "claude-code")
FIXTURES_DIR = ROOT / "tooling" / "tests" / "fixtures" / "skills"


def validate_action_skill(name: str) -> None:
    """Action skills need a seeded fixture and a per-client verification ledger."""
    skill_dir = SKILLS_DIR / name
    if not (skill_dir / "SKILL.md").is_file():
        fail(f"action skill {name} has no SKILL.md")
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for heading in ("## Inputs", "## Permitted changes", "## Stop conditions", "## Verification", "## Outcome report"):
        if heading not in text:
            fail(f"skills/{name}/SKILL.md is missing the {heading!r} section")
    fixture = FIXTURES_DIR / name
    if not (fixture / "TASK.md").is_file():
        fail(f"action skill {name} is missing its seeded fixture {fixture}/TASK.md")
    ledger = skill_dir / "VERIFICATION.md"
    if not ledger.is_file():
        fail(f"action skill {name} is missing VERIFICATION.md")
    rows = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0] in SUPPORTED_CLIENTS:
            rows[cells[0]] = cells
    for client in SUPPORTED_CLIENTS:
        if client not in rows:
            fail(f"skills/{name}/VERIFICATION.md ledger has no row for {client}")
        verified, revision = rows[client][1].lower(), rows[client][3]
        if verified not in {"yes", "no"}:
            fail(f"skills/{name}/VERIFICATION.md {client} row must say yes or no, not {verified!r}")
        if verified == "yes" and revision in {"", "—", "-"}:
            fail(f"skills/{name}/VERIFICATION.md {client} row is verified without a toolkit revision")


def validate_no_absolute_paths() -> None:
    for path in SKILLS_DIR.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".py", ".yaml", ".yml"}:
            text = path.read_text(encoding="utf-8")
            if ABSOLUTE_PATH_PATTERN.search(text):
                fail(f"{path.relative_to(ROOT)} contains a machine-local absolute path")


def run_tests() -> None:
    test_dirs = [
        SKILLS_DIR / "_shared-project-ops" / "scripts" / "tests",
        SKILLS_DIR / "issue-operator" / "scripts" / "tests",
        SKILLS_DIR / "full-test-suite" / "scripts" / "tests",
    ]
    for test_dir in test_dirs:
        if test_dir.exists():
            subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(test_dir), "-p", "test_*.py"],
                cwd=ROOT,
                check=True,
            )


def main() -> None:
    if not SKILLS_DIR.exists():
        fail("skills does not exist")

    skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    if not skill_files:
        fail("no skill files found")

    for skill_file in skill_files:
        parse_frontmatter(skill_file)
        validate_references(skill_file)
        agents_file = skill_file.parent / "agents" / "openai.yaml"
        if not agents_file.exists():
            fail(f"{skill_file.parent.relative_to(ROOT)} is missing agents/openai.yaml")

    for name in ACTION_SKILLS:
        validate_action_skill(name)

    validate_no_absolute_paths()
    run_tests()
    print(f"Validated {len(skill_files)} skills")


if __name__ == "__main__":
    main()
