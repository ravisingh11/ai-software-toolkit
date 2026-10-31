#!/usr/bin/env python3
"""Checkpoint placement and integrity reports, separate from Proof decisions."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from assurance import CHECKPOINTS, verify_receipt  # noqa: E402

DECISIONS = {
    "coding-finished": "Ready to prepare a commit?", "pre-commit": "Ready to record these exact staged contents?",
    "commit-creation": "Is the proposed commit record acceptable?", "post-commit": "What is known about this revision?",
    "pre-push": "Ready to share this outgoing revision range?", "pr": "Ready for review?",
    "pre-merge": "Ready to integrate the current candidate?", "post-merge": "Is the resulting main revision healthy?",
    "release": "Ready to publish this exact package?", "deployment": "Ready to deploy the approved package?",
    "runtime": "What was observed about this running version, and when?",
}
EARLY = {"coding-finished", "pre-commit", "commit-creation", "pre-push"}


def git(target: Path, *args: str, binary=False):
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "TZ") if key in os.environ}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}",
                             "-C", str(target), *args], capture_output=True, env=environment, timeout=30, check=True)
    return result.stdout if binary else result.stdout.decode().strip()


def index_state(target: Path) -> tuple[str, list[dict]]:
    """Compute Git's tree identity from index entries without writing Git objects."""
    if git(target, "rev-parse", "--show-object-format") != "sha1":
        raise ValueError("This checkpoint adapter currently requires SHA-1 Git object format")
    raw = git(target, "ls-files", "--stage", "-z", binary=True)
    entries, tree = [], {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        name = raw_name.decode("utf-8")
        from assurance import relative_path
        parts = relative_path(name).parts
        if stage != "0" or mode not in {"100644", "100755"}:
            raise ValueError("Conflicts, symbolic links and submodules are unsupported staged contents")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValueError("Conflicting index paths")
        node[parts[-1]] = (mode, oid)
        entries.append({"path": name, "mode": mode, "oid": oid})
        if len(entries) > 20000:
            raise ValueError("Staged snapshot exceeds bounded inventory")

    def identity(node):
        items = []
        for name, child in node.items():
            directory = isinstance(child, dict)
            mode, oid = ("40000", identity(child)) if directory else child
            items.append((name.encode() + (b"/" if directory else b""), mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(oid)))
        content = b"".join(value for _, value in sorted(items))
        return hashlib.sha1(b"tree " + str(len(content)).encode() + b"\0" + content, usedforsecurity=False).hexdigest()

    return identity(tree), entries


def trusted_module(source: str, installed: str):
    here = Path(__file__).resolve()
    path = here.parent / installed if here.parent.name == ".proof" else here.parents[1] / source
    spec = importlib.util.spec_from_file_location("checkpoint_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def placement(control: dict) -> list[str]:
    identifier = control["id"]
    subject = control["evidence_subject"]
    if subject == "artifact":
        return ["release", "deployment"]
    if subject == "environment":
        return ["deployment", "runtime"]
    if subject == "pull-request":
        return ["pr", "pre-merge"]
    points = ["post-commit", "pr", "pre-merge", "post-merge"]
    if identifier in {"custom-static-analysis", "secret-detection"}:
        points = ["pre-commit", "pre-push", *points]
    if "review" in identifier or identifier in {"documentation-validation", "repository-ground-truth", "functional-qa"}:
        points = ["coding-finished", *points]
    if control["stage"] in {"release", "change-and-release"}:
        points.append("release")
    return points


def plan(target: Path, checkpoint: str, *, operation: str | None = None) -> dict:
    operation = operation or ("release" if checkpoint in {"release", "deployment", "runtime"} else "change")
    result = {"version": 1, "kind": "checkpoint-plan", "checkpoint": checkpoint, "operation": operation,
              "decision": DECISIONS[checkpoint], "read_only": True, "authorization_granted": False,
              "execution_supported": checkpoint == "pre-commit" and Path(__file__).with_name("staged_checkpoint.py").is_file(), "subject": None,
              "checks": [], "gaps": [], "platform_merge_requirements": "Inspect current platform checks, approvals and review resolution separately.",
              "limits": "Placement and setup are not passing evidence. Local index receipts do not satisfy commit-bound Proof controls or hosted merge requirements."}
    try:
        if Path(git(target, "rev-parse", "--show-toplevel")).resolve() != target.resolve():
            raise ValueError("Target must be repository root")
        head = None
        try:
            head = git(target, "rev-parse", "HEAD^{commit}")
            result["source_revision"] = head
        except subprocess.SubprocessError:
            result["gaps"].append("No committed HEAD is available; commit-bound evidence remains unavailable.")
        if checkpoint == "pre-commit":
            index, _ = index_state(target)
            result["subject"] = {"type": "git-index", "revision": index}
        elif head and checkpoint not in EARLY and checkpoint not in {"release", "deployment", "runtime"}:
            result["subject"] = {"type": "git-commit", "revision": head}
        else:
            result["gaps"].append("Supply the actual working/range, PR, artifact or environment subject; no subject was inferred from HEAD.")
    except (OSError, ValueError, subprocess.SubprocessError):
        result["gaps"].append("Git subject unavailable or unsupported; inspect repository root, HEAD and index conflicts.")
    evaluator = trusted_module("proof/evaluate.py", "evaluate.py")
    activation = trusted_module("tooling/activation.py", "activation.py")
    try:
        from assurance import confined_file, read_document
        documents = [read_document(confined_file(target, ".proof/" + name + ".yaml")) for name in ("policy", "profiles", "control-catalog", "providers")]
        selected, controls, providers = {}, {}, {}
        for subject in ("git-commit", "pull-request", "artifact", "environment"):
            active, controls, providers = evaluator.effective_controls(*documents, operation, subject)
            selected.update(active)
        evidence = {}
        try:
            evidence = read_document(confined_file(target, ".artifacts/proof/evidence.json"))
            evaluator.validate_evidence(evidence, controls, providers)
        except (OSError, ValueError, KeyError, TypeError):
            evidence = {}
        for identifier, control in controls.items():
            selection = selected.get(identifier)
            provider = selection["authoritative"] if selection else None
            hints = activation.hints(control, provider, providers[provider], target=target) if provider else {}
            files = hints.get("installed_files", [])
            existing = evidence.get("results", {}).get(identifier, {}).get(provider, {})
            observed = {"status": existing.get("status", "not_run"), "subject": evidence.get("subject"),
                        "matches_commit": evidence.get("subject") == {"type": "git-commit", "revision": result.get("source_revision")},
                        "provider_authority_authenticated": False,
                        "limits": "Supplied evidence observation only; a file is not authenticated producer execution."}
            result["checks"].append({"id": identifier, "name": control["name"], "purpose": control["purpose"],
                                     "selected": bool(selection), "mode": selection["mode"] if selection else "not_activated",
                                     "authoritative_provider": provider, "evidence_subject": control["evidence_subject"],
                                     "recommended_checkpoints": placement(control), "recommended_here": checkpoint in placement(control),
                                     "guide": hints.get("guide", activation.GUIDE_URL + "#" + identifier),
                                     "prerequisites": files, "missing_files": [p for p in files if not (target / p).resolve().is_relative_to(target.resolve()) or not (target / p).is_file()],
                                     "required_variables": hints.get("variables", []), "credential_names": hints.get("credential_names", []),
                                     "producer_located": bool(shutil.which("docker") or shutil.which("semgrep" if provider == "semgrep-ce" else "gitleaks")) if provider in {"semgrep-ce", "gitleaks"} else None,
                                     "existing_evidence": observed,
                                     "next_action": hints.get("execution", "Explicitly adopt a provider only if relevant; inactive is not a failed check.")})
    except (OSError, ValueError, KeyError, TypeError):
        result["gaps"].append("Installed policy/catalog/provider contracts are unavailable or invalid; this is not a passing plan.")
    if checkpoint != "pre-commit":
        result["gaps"].append("No checkpoint runner is provided here; use the adopted producer and retain its original evidence.")
    return result


def render(value: dict) -> str:
    lines = [f"Checkpoint: {value['checkpoint']}"]
    if value.get("kind") == "checkpoint-plan":
        lines += [value["decision"], "Subject: " + json.dumps(value["subject"]), "Checks (selection does not prove execution):"]
        lines += [f"- {row['name']}: {row['mode']}; {row['authoritative_provider'] or 'inactive'}; {row['next_action']}" for row in value["checks"] if row["recommended_here"]]
        lines += ["Gap: " + gap for gap in value["gaps"]]
    else:
        lines += ["Subject: " + json.dumps(value["subject"]), "Applicable: " + str(value["applicable"])]
        lines += [f"- {row['check']}: {row['status']} ({row['provider']})" for row in value["results"]]
        lines += ["Invalidation: " + reason for reason in value["invalidation_reasons"]]
        lines += ["Merge requirements: " + text for text in value["platform_requirements"]]
    return "\n".join([*lines, "No action is authorized by this report."])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run", "verify"))
    parser.add_argument("--checkpoint", choices=CHECKPOINTS, default="pre-commit")
    parser.add_argument("--target", type=Path, default=Path.cwd())
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--expected-context", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            value = plan(args.target.resolve(), args.checkpoint)
            code = 0 if value["checks"] and value["subject"] else 1
        elif args.action == "verify":
            if not args.receipt:
                parser.error("verify requires --receipt")
            from assurance import read_document
            expected = read_document(args.expected_context) if args.expected_context else None
            value = verify_receipt(args.receipt, expected=expected)
            code = 0 if value["all_reported_checks_passed"] else 1
        else:
            raise ValueError("Checkpoint execution is unavailable in this installation; use adopted producers.")
        print(json.dumps(value, indent=2) if args.json else render(value))
        return code
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"valid": False, "error": str(error)}) if args.json else "Checkpoint unavailable: " + str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
