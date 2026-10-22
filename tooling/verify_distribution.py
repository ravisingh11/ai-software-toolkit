#!/usr/bin/env python3
"""Hosted acceptance of exact candidate and published CLI bytes; no real producers.

The published baseline is pinned independently of the candidate implementation.
Raw semantic comparisons and accepted file differences accompany the release.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

LEGACY_REVISION = "bf05798e4b03610551f9882620767f31de03d1df"
LEGACY_SHA256 = "020949c5a42490db814d9f8867c637530f2f66aa69c9a7d3bb1916315fd82eee"
LEGACY_CHECKSUM_SHA256 = "99b1f4e6106f64ed07602264b3c3429584d7107fcdd32e873d34902b3fdd467f"
LEGACY_ASSETS = {"ai-toolkit.pyz": 665661829, "ai-toolkit.pyz.sha256": 665661888}
STARTER = {
    "proof-scorecard.yml", "repository-validation.yml", "change-scope.yml", "pr-metadata.yml",
    "build.yml", "unit-tests.yml", "changed-code-coverage.yml", "format-and-lint.yml",
    "migration-validation.yml", "semgrep-ce.yml", "gitleaks.yml",
}
SKILLS = {"toolkit-setup", "prepare-safe-change", "code-review", "test-gap-finder",
          "security-audit-lite", "dependency-risk-review", "qa-bootstrap"}
RECORDS = {"toolkit.toml", "toolkit.lock.json"}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(command: list[str], target: Path, environment: dict, *, codes: tuple = (0,)) -> str:
    completed = subprocess.run(command, cwd=target, env=environment, capture_output=True, text=True, timeout=120)
    require(completed.returncode in codes, f"Fixture command failed: {command[1:]}: {completed.stderr}")
    return completed.stdout


def workflows(target: Path) -> set[str]:
    return {p.name for p in (target / ".github/workflows").glob("*.yml")}


def snapshot(target: Path, *, consumer_files: bool = False) -> dict:
    """Include ignored files, links and directories; never follow a link's referent."""
    result = {}
    for path in sorted(target.rglob("*")):
        relative = path.relative_to(target).as_posix()
        if consumer_files and (relative.split("/")[0] in {".git", ".artifacts"} or relative in RECORDS):
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            result[relative] = {"link": os.readlink(path), "mode": mode}
        elif path.is_file():
            result[relative] = {"sha256": digest(path.read_bytes()), "mode": mode}
        elif path.is_dir():
            result[relative] = {"directory": True, "mode": mode}
    return result


def equal(expected, observed, label: str) -> None:
    require(expected == observed, f"Unexpected difference: {label}")


def reject(name: str, operation) -> dict:
    try:
        operation()
    except ValueError:
        return {"name": name, "status": "rejected-as-expected"}
    raise ValueError(f"Negative control escaped detection: {name}")


def contracts(target: Path) -> dict:
    configuration = tomllib.loads((target / "toolkit.toml").read_text())
    configuration["toolkit"].pop("revision", None)  # This is the only configuration normalization.
    lock = json.loads((target / "toolkit.lock.json").read_text()) if (target / "toolkit.lock.json").exists() else None
    return {"configuration": configuration, "lock_components": lock["components"] if lock else None,
            "lock_install_set": lock["toolkit"].get("install_set") if lock else None,
            "workflows": sorted(workflows(target)),
            "policy": json.loads((target / ".proof/policy.yaml").read_text()),
            "providers": json.loads((target / ".proof/providers.yaml").read_text()),
            "profiles": json.loads((target / ".proof/profiles.yaml").read_text())}


def compare_consumers(old: Path, new: Path, replacements: dict, additions: dict) -> list[dict]:
    equal(contracts(old), contracts(new), "consumer selections, clients, workflows or records")
    old_lock = json.loads((old / "toolkit.lock.json").read_text())
    new_lock = json.loads((new / "toolkit.lock.json").read_text())
    removed = set(old_lock["managed"]) - set(new_lock["managed"])
    added = set(new_lock["managed"]) - set(old_lock["managed"])
    require(not removed and added <= set(additions), f"Unexpected managed ownership differences: {removed}, {added}")
    before, after = snapshot(old, consumer_files=True), snapshot(new, consumer_files=True)
    differences = []
    for path in sorted(before.keys() | after.keys()):
        if before.get(path) == after.get(path):
            continue
        previous, current = before.get(path, {}), after.get(path, {})
        allowed = (path in additions and not previous and current.get("sha256") == additions[path]) or (
            previous.get("sha256") in replacements
            and current.get("sha256") in replacements[previous["sha256"]]
            and previous.get("mode") == current.get("mode"))
        require(allowed, f"Undocumented consumer file difference: {path}")
        differences.append({"path": path, "before": previous, "after": current,
                            "reason": "declared canonical runtime/documentation upgrade"})
    return differences


def unpack(archive: Path, destination: Path) -> dict[str, bytes]:
    payload = {}
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.testzip() is None, "Archive CRC failure")
        require(len(bundle.namelist()) == len(set(bundle.namelist())), "Duplicate archive members")
        for entry in bundle.infolist():
            path = Path(entry.filename)
            require(not path.is_absolute() and ".." not in path.parts, "Unsafe archive member")
            if entry.is_dir() or not entry.filename.startswith("payload/"):
                continue
            relative = entry.filename[len("payload/"):]
            data = bundle.read(entry)
            payload[relative] = data
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return payload


def evaluation_comparison(old_source: Path, new_source: Path, workspace: Path, environment: dict) -> list[dict]:
    """Identical published-contract inputs, both public evaluators, no normalization."""
    providers = json.loads((old_source / "policies/provider-config.yaml").read_text())
    providers["selections"]["deep-sast"]["supplemental"] = ["snyk-code"]
    profiles = json.loads((old_source / "policies/profiles.yaml").read_text())
    catalog = json.loads((old_source / "policies/control-catalog.yaml").read_text())
    documents = workspace / "evaluation-inputs"
    documents.mkdir()
    for name, value in (("profiles", profiles), ("catalog", catalog), ("providers", providers)):
        (documents / f"{name}.json").write_text(json.dumps(value))
    cases = []
    definitions = [
        ("authoritative-pass", "passed", False, False, False, False, False),
        ("selected-failure", "failed", False, False, False, False, False),
        ("missing-authority", None, False, False, False, False, False),
        ("supplemental-only-pass", None, True, False, False, False, False),
        ("missing-scanner-prerequisite", "blocked", False, False, False, False, False),
        ("missing-credential", "not_run", False, False, False, False, False),
        ("stale-revision", "passed", False, True, False, False, False),
        ("wrong-subject", None, False, False, True, False, False),
        ("inactive-check", "failed", False, False, False, True, False),
        ("manual-producer-not-run", "not_run", False, False, False, False, True),
        ("manual-producer-missing", None, False, False, False, False, True),
    ]
    for name, status, supplemental, stale, wrong_subject, inactive, manual in definitions:
        operation, subject_type, check = ("release", "environment", "runtime-soak") if manual else ("change", "git-commit", "deep-sast")
        policy = {"version": 2, "name": "compatibility-oracle", "profiles": ["github"],
                  "overrides": {op: {key: "not_activated" for key in profiles["profiles"]["github"]["defaults"][op]}
                                for op in ("change", "release")}}
        policy["overrides"][operation][check] = "not_activated" if inactive else "advisory"
        authority = providers["selections"][check]["authoritative"]
        results = {}
        if status:
            value = {"producer": authority, "status": status}
            value.update({"evidence": ["fixture execution receipt"]} if status in {"passed", "failed"}
                         else {"reason": "manual producer not executed" if manual else name})
            results[authority] = value
        if supplemental:
            results["snyk-code"] = {"producer": "fixture", "status": "passed", "evidence": ["supplemental receipt"]}
        evidence = {"version": 2, "subject": {"type": "artifact" if wrong_subject else subject_type,
                                              "revision": "b" * 40 if stale else "a" * 40},
                    "results": {check: results} if results else {}}
        (documents / "policy.json").write_text(json.dumps(policy))
        (documents / "evidence.json").write_text(json.dumps(evidence))
        arguments = [argument for key in ("policy", "profiles", "catalog", "providers", "evidence")
                     for argument in ("--" + key, str(documents / f"{key}.json"))]
        arguments += ["--operation", operation, "--revision", "a" * 40, "--subject-type", subject_type,
                      "--all-catalog-controls", "--json"]
        outputs = {}
        for label, source in (("published", old_source), ("candidate", new_source)):
            outputs[label] = {kind: json.loads(run([sys.executable, str(source / script), *arguments], workspace, environment, codes=(0, 1)))
                              for kind, script in (("evaluation", "proof/evaluate.py"), ("scorecard", "tooling/proof_scorecard.py"))}
        equal(outputs["published"], outputs["candidate"], name + " evaluator/scorecard")
        card = outputs["candidate"]["scorecard"]
        equal(len(card["controls"]), 33, name + " discoverability")
        equal(card["advisory"]["total"], 0 if inactive else 1, name + " selected applicable denominator")
        equal(card["advisory"]["passed"], int(status == "passed" and not stale and not inactive), name + " passing count")
        equal(card["decision"], "block" if stale or wrong_subject else "allow", name + " decision")
        equal(card["status"], "RED" if stale or wrong_subject else "GREEN" if status == "passed" or inactive else "ORANGE", name + " status")
        cases.append({"name": name, "status": "passed", "policy": policy, "evidence": evidence,
                      "outputs": outputs, "comparison": "exact JSON equality; no fields removed"})
    return cases


def verify(archive: Path, legacy_archive: Path, revision: str) -> dict:
    archive_digest = digest(archive.read_bytes())
    require(archive.with_name(archive.name + ".sha256").read_text().split() == [archive_digest, archive.name], "Candidate checksum mismatch")
    equal(digest(legacy_archive.read_bytes()), LEGACY_SHA256, "published CLI pinned digest")
    checksum = legacy_archive.with_name(legacy_archive.name + ".sha256")
    equal(digest(checksum.read_bytes()), LEGACY_CHECKSUM_SHA256, "published checksum pinned digest")
    equal(checksum.read_text().split(), [LEGACY_SHA256, "ai-toolkit.pyz"], "published checksum contents")
    cases, negative_controls = [], []
    with tempfile.TemporaryDirectory(prefix="toolkit-consumer-acceptance-") as temporary:
        workspace = Path(temporary)
        old_source, new_source = workspace / "published-source", workspace / "candidate-source"
        old_payload, new_payload = unpack(legacy_archive, old_source), unpack(archive, new_source)
        equal(json.loads(old_payload["tooling/ai_toolkit/BUILD.json"])["revision"], LEGACY_REVISION, "published revision")
        equal(json.loads(new_payload["tooling/ai_toolkit/BUILD.json"])["revision"], revision, "candidate revision")
        require(not any(name.startswith("tooling/speckit/") or name == "tooling/package-speckit-preset.sh" for name in new_payload), "Bundled Spec Kit")
        spec = importlib.util.spec_from_file_location("acceptance_builder", Path(__file__).with_name("build_archive.py"))
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        source_root = Path(__file__).resolve().parents[1]
        expected = {path.relative_to(source_root).as_posix() for path in builder.payload_files(source_root)} | {"tooling/ai_toolkit/BUILD.json"}
        equal(set(new_payload), expected, "exact candidate payload inventory")
        for name in expected - {"tooling/ai_toolkit/BUILD.json"}:
            equal(new_payload[name], (source_root / name).read_bytes(), "packaged source " + name)
        replacements = {}
        for name in old_payload.keys() & new_payload.keys():
            if old_payload[name] != new_payload[name] and name != "tooling/ai_toolkit/BUILD.json":
                replacements.setdefault(digest(old_payload[name]), set()).add(digest(new_payload[name]))
        additions = {".proof/activation.py": digest(new_payload["tooling/activation.py"])}
        binaries = workspace / "bin"
        binaries.mkdir()
        gh = binaries / "gh"
        gh.write_text("#!/bin/sh\nexit 1\n")
        gh.chmod(0o755)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("PROOF_", "GIT_", "GH_", "GITHUB_")) and key not in {"BASH_ENV", "ENV"}}
        environment.update({"PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                            "AI_TOOLKIT_CACHE": str(workspace / "cache"), "PYTHONDONTWRITEBYTECODE": "1",
                            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                            "GIT_CONFIG_COUNT": "4", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull,
                            "GIT_CONFIG_KEY_1": "maintenance.auto", "GIT_CONFIG_VALUE_1": "false",
                            "GIT_CONFIG_KEY_2": "gc.auto", "GIT_CONFIG_VALUE_2": "0",
                            "GIT_CONFIG_KEY_3": "core.fsmonitor", "GIT_CONFIG_VALUE_3": "false"})
        command, old_command = [sys.executable, str(archive)], [sys.executable, str(legacy_archive)]

        def initialize(target):
            target.mkdir()
            (target / "README.md").write_text("# Consumer\n")
            run(["git", "init", "-q"], target, environment)
            run(["git", "add", "README.md"], target, environment)
            run(["git", "-c", "user.name=Toolkit Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Consumer"], target, environment)

        for name, options, client in (
            ("starter-codex", ["--clients", "codex"], "codex"),
            ("starter-claude", ["--clients", "claude-code"], "claude-code"),
            ("proof-only", ["--components", "proof"], None),
            ("runtime-only", ["--components", "proof", "--no-actions"], None),
        ):
            target = workspace / name
            initialize(target)
            run(command + ["init", "--target", str(target), "--yes", *options], target, environment)
            require(workflows(target) == (set() if name == "runtime-only" else STARTER), "Unexpected fresh workflows")
            configuration = contracts(target)
            equal(configuration["configuration"]["toolkit"]["components"], ["proof", "skills"] if client else ["proof"], name + " components")
            equal(configuration["configuration"]["toolkit"]["install_set"], "starter", name + " configuration set")
            equal(configuration["lock_install_set"], "starter", name + " lock set")
            equal(len(json.loads((target / ".proof/control-catalog.yaml").read_text())["controls"]), 33, "Catalog")
            core = configuration["profiles"]["profiles"]["core"]["defaults"]["change"]
            require(len(core) == 12 and set(core.values()) == {"advisory"}, "Core coverage changed")
            equal((target / ".agents").exists(), client == "codex", "Codex destination")
            equal((target / ".claude").exists(), client == "claude-code", "Claude destination")
            if client:
                root = target / (".agents/skills" if client == "codex" else ".claude/skills")
                equal({p.parent.name for p in root.glob("*/SKILL.md")}, SKILLS, "Exact starter skills")
            run(command + ["update", "--target", str(target), "--force"], target, environment)
            equal(contracts(target), configuration, name + " update selections")
            # Git status alone cannot detect edits to ignored evidence or existing untracked files.
            ignored = target / ".artifacts/doctor-read-only.txt"
            ignored.parent.mkdir(exist_ok=True)
            ignored.write_text("must remain byte-identical\n")
            before = snapshot(target)
            report = json.loads(run(command + ["doctor", "--target", str(target), "--json"], target, environment, codes=(0, 1)))
            equal(snapshot(target), before, name + " complete read-only snapshot")
            equal(len(report["activation"]), 33, "Doctor discoverability")
            require(all(not row["evidence"]["verified"] for row in report["activation"]), "Unexecuted fixture gained passing evidence")
            cases.append({"name": name, "status": "passed", "checks": 33, "core_advisory": 12})

        for locked in (True, False):
            for customized in (True, False):
                for partial in (True, False):
                    name = f"legacy-locked-{locked}-customized-{customized}-partial-{partial}"
                    seed = workspace / name
                    initialize(seed)
                    run(old_command + ["init", "--target", str(seed), "--clients", "codex", "--yes"], seed, environment)
                    if customized:
                        (seed / ".github/workflows/build.yml").write_text("name: Consumer-owned build\n")
                        (seed / ".proof/consumer-owned.txt").write_text("preserve custom file\n")
                        skill = seed / ".agents/skills/code-review/SKILL.md"
                        skill.write_text(skill.read_text() + "\nConsumer-owned instructions.\n")
                        policy_path = seed / ".proof/policy.yaml"
                        policy = json.loads(policy_path.read_text())
                        policy["overrides"]["change"]["unit-tests"] = "not_activated"
                        policy_path.write_text(json.dumps(policy))
                    if partial:
                        (seed / ".proof/scan.py").unlink()
                    if not locked:
                        (seed / "toolkit.lock.json").unlink()
                    for transition in ("reinit", "update-rollback"):
                        old, new = workspace / (name + transition + "-old"), workspace / (name + transition + "-new")
                        shutil.copytree(seed, old)
                        shutil.copytree(seed, new)
                        original = {label: snapshot(target, consumer_files=True) for label, target in (("old", old), ("new", new))}
                        differences = []
                        for target, executable in ((old, old_command), (new, command)):
                            args = ["init", "--yes"] if transition == "reinit" else ["update", "--force"]
                            run(executable + [*args, "--target", str(target)], target, environment)
                        differences.extend(compare_consumers(old, new, replacements, additions))
                        if transition == "update-rollback":
                            for label, target, executable in (("old", old, old_command), ("new", new, command)):
                                require((target / ".proof/scan.py").is_file(), "Partial runtime not restored")
                                run(executable + ["update", "--target", str(target), "--rollback"], target, environment)
                                equal(snapshot(target, consumer_files=True), original[label], name + " exact rollback files")
                            differences.extend(compare_consumers(old, new, replacements, additions))
                        require({"trivy.yml", "lifecycle-verification.yml"} <= workflows(new), "Legacy optional workflows lost")
                        require("install_set" not in contracts(new)["configuration"]["toolkit"], "Legacy configuration migrated")
                        cases.append({"name": name + "-" + transition, "status": "passed", "accepted_differences": differences})
        evaluations = evaluation_comparison(old_source, new_source, workspace, environment)
        negative_controls.append(reject("unexpected-archive-member", lambda: equal(set(new_payload) | {"tooling/speckit/unrequested.yml"}, expected, "archive membership")))
        policy = contracts(new)
        changed = copy.deepcopy(policy)
        changed["policy"]["overrides"]["change"]["unit-tests"] = "enforced"
        negative_controls.append(reject("changed-selection", lambda: equal(policy, changed, "selection")))
        custom = new / "README.md"
        custom.write_text("unexpected edit to an existing consumer file\n")
        negative_controls.append(reject("altered-custom-file", lambda: compare_consumers(old, new, replacements, additions)))
        card = evaluations[1]["outputs"]["candidate"]["scorecard"]
        false_pass = copy.deepcopy(card)
        false_pass["advisory"]["passed"] += 1
        negative_controls.append(reject("false-passing-evidence", lambda: equal(card, false_pass, "passing count")))
    return {"version": 1, "kind": "distribution-acceptance", "source_revision": revision,
            "archive_sha256": archive_digest, "all_passed": True, "cases": cases,
            "published_baseline": {"tag": "v2.2.1", "source_revision": LEGACY_REVISION, "archive_sha256": LEGACY_SHA256,
                                   "checksum_sha256": LEGACY_CHECKSUM_SHA256, "asset_ids": LEGACY_ASSETS},
            "evaluation_cases": evaluations, "negative_controls": negative_controls,
            "normalization": "Only toolkit.revision removed from parsed consumer configuration. Evaluator/scorecard JSON compared without normalization. File differences must match exact published-to-candidate canonical bytes; managed additions limited to .proof/activation.py.",
            "limits": "Hosted fixture acceptance only; no real scanner, lifecycle, credential validity, application certification, build provenance or deployment claim."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--legacy-archive", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.archive.resolve(), args.legacy_archive.resolve(), args.revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("source_revision", "archive_sha256", "all_passed", "published_baseline")} |
                     {"consumer_cases": len(report["cases"]), "evaluation_cases": len(report["evaluation_cases"]),
                      "negative_controls": report["negative_controls"]}, indent=2))


if __name__ == "__main__":
    main()
