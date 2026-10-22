#!/usr/bin/env python3
"""Hosted, explicit consumer acceptance for the exact release CLI archive.

Run after required CI. No provider, scanner, lifecycle, application, deployment,
GitHub variable, or branch protection operation is executed by these fixtures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

STARTER = {
    "proof-scorecard.yml", "repository-validation.yml", "change-scope.yml", "pr-metadata.yml",
    "build.yml", "unit-tests.yml", "changed-code-coverage.yml", "format-and-lint.yml",
    "migration-validation.yml", "semgrep-ce.yml", "gitleaks.yml",
}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def run(command: list[str], target: Path, environment: dict, *, codes: tuple = (0,)) -> str:
    completed = subprocess.run(command, cwd=target, env=environment, capture_output=True, text=True, timeout=120)
    require(completed.returncode in codes, f"Fixture command failed: {command[1:3]}: {completed.stderr}")
    return completed.stdout


def workflows(target: Path) -> set[str]:
    return {p.name for p in (target / ".github/workflows").glob("*.yml")}


def verify(archive: Path, legacy_source: Path, revision: str) -> dict:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    require(archive.with_name(archive.name + ".sha256").read_text().split()[0] == digest, "Archive checksum mismatch")
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.testzip() is None, "Archive integrity failure")
        names = bundle.namelist()
        require(len(names) == len(set(names)), "Duplicate archive members")
        require(not any(name.startswith("payload/tooling/speckit/") or name == "payload/tooling/package-speckit-preset.sh" for name in names), "Bundled Spec Kit")
        require(json.loads(bundle.read("payload/tooling/ai_toolkit/BUILD.json"))["revision"] == revision, "Wrong source revision")
    cases = []
    with tempfile.TemporaryDirectory(prefix="toolkit-consumer-acceptance-") as temporary:
        workspace = Path(temporary)
        binaries = workspace / "bin"
        binaries.mkdir()
        gh = binaries / "gh"
        gh.write_text("#!/bin/sh\nexit 1\n")
        gh.chmod(0o755)
        environment = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                       "AI_TOOLKIT_CACHE": str(workspace / "cache"), "PYTHONDONTWRITEBYTECODE": "1",
                       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                       "GIT_CONFIG_COUNT": "4", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull,
                       "GIT_CONFIG_KEY_1": "maintenance.auto", "GIT_CONFIG_VALUE_1": "false",
                       "GIT_CONFIG_KEY_2": "gc.auto", "GIT_CONFIG_VALUE_2": "0",
                       "GIT_CONFIG_KEY_3": "core.fsmonitor", "GIT_CONFIG_VALUE_3": "false"}
        for key in list(environment):
            if key.startswith("PROOF_"):
                del environment[key]
        command = [sys.executable, str(archive)]
        for name, options, client in (
            ("starter-codex", ["--clients", "codex"], "codex"),
            ("starter-claude", ["--clients", "claude-code"], "claude-code"),
            ("proof-only", ["--components", "proof"], None),
            ("runtime-only", ["--components", "proof", "--no-actions"], None),
        ):
            target = workspace / name
            target.mkdir()
            (target / "README.md").write_text("# Consumer\n")
            run(["git", "init", "-q"], target, environment)
            run(["git", "add", "README.md"], target, environment)
            run(["git", "-c", "user.name=Toolkit Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Initialize consumer"], target, environment)
            run(command + ["init", "--target", str(target), "--yes", *options], target, environment)
            require(workflows(target) == (set() if name == "runtime-only" else STARTER), "Unexpected fresh workflows")
            lock = json.loads((target / "toolkit.lock.json").read_text())
            require(lock["toolkit"]["install_set"] == "starter", "Starter not persisted")
            require('install_set = "starter"' in (target / "toolkit.toml").read_text(), "Configuration set missing")
            require(len(json.loads((target / ".proof/control-catalog.yaml").read_text())["controls"]) == 33, "Catalog narrowed")
            profiles = json.loads((target / ".proof/profiles.yaml").read_text())
            core = profiles["profiles"]["core"]["defaults"]["change"]
            require(len(core) == 12 and set(core.values()) == {"advisory"}, "Core coverage changed")
            require((target / ".agents").exists() == (client == "codex"), "Unexpected Codex destination")
            require((target / ".claude").exists() == (client == "claude-code"), "Unexpected Claude destination")
            if client:
                root = target / (".agents/skills" if client == "codex" else ".claude/skills")
                require(len(list(root.glob("*/SKILL.md"))) == 7, "Starter skill count changed")
            run(command + ["update", "--target", str(target), "--force"], target, environment)
            require(workflows(target) == (set() if name == "runtime-only" else STARTER), "Update widened starter workflows")
            before = run(["git", "status", "--porcelain"], target, environment)
            report = json.loads(run(command + ["doctor", "--target", str(target), "--json"], target, environment, codes=(0, 1)))
            require(run(["git", "status", "--porcelain"], target, environment) == before, "Doctor mutated the consumer")
            require(len(report["activation"]) == 33, "Doctor omitted checks")
            require(all(not row["evidence"]["verified"] for row in report["activation"]), "Unexecuted fixture gained passing evidence")
            cases.append({"name": name, "status": "passed", "checks": 33, "core_advisory": 12})

        # Build the starting consumer with the actual previously published source.
        legacy_revision = run(["git", "rev-parse", "HEAD"], legacy_source, environment).strip()
        require(legacy_revision == "bf05798e4b03610551f9882620767f31de03d1df", "Unexpected legacy source")
        target = workspace / "published-consumer"
        target.mkdir()
        (target / "README.md").write_text("# Legacy consumer\n")
        run([sys.executable, str(legacy_source / "tooling/ai_toolkit"), "init", "--target", str(target), "--clients", "codex", "--yes"], target, environment)
        require({"trivy.yml", "lifecycle-verification.yml"} <= workflows(target), "Legacy fixture is not full")
        configuration = (target / "toolkit.toml").read_text()
        policy = (target / ".proof/policy.yaml").read_bytes()
        workflow = target / ".github/workflows/build.yml"
        workflow.write_text("name: Consumer-owned build\n")
        custom = target / ".proof/consumer-owned.txt"
        custom.write_text("keep this file\n")
        (target / ".proof/scan.py").unlink()
        run(command + ["update", "--target", str(target), "--force"], target, environment)
        require(workflow.read_text() == "name: Consumer-owned build\n", "Consumer workflow overwritten")
        require(custom.read_text() == "keep this file\n", "Custom file lost")
        require((target / ".proof/policy.yaml").read_bytes() == policy, "Legacy policy changed")
        require((target / ".proof/scan.py").is_file(), "Partial runtime not repaired")
        require({"trivy.yml", "lifecycle-verification.yml"} <= workflows(target), "Legacy workflows narrowed")
        require("install_set" not in json.loads((target / "toolkit.lock.json").read_text())["toolkit"], "Legacy lock migrated")
        require("install_set" not in (target / "toolkit.toml").read_text() and "install_set" not in configuration, "Legacy configuration migrated")
        cases.append({"name": "published-v2.2.1-customized-partial-consumer", "status": "passed", "source_revision": legacy_revision})
    return {"version": 1, "kind": "distribution-acceptance", "source_revision": revision,
            "archive_sha256": digest, "all_passed": True, "cases": cases,
            "limits": "Hosted fixture acceptance only; no scanner, lifecycle, application readiness, credential migration, or consumer deployment claim."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--legacy-source", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.archive.resolve(), args.legacy_source.resolve(), args.revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
