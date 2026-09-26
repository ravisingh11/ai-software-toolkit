#!/usr/bin/env python3
"""Run an external provider with the adapter-owned command shape and emit revision-bound evidence.

The adapter, not the consumer, decides which commands run (for example
``fossa analyze`` followed by ``fossa test``) and how exit codes and output map
to the four evidence statuses. Consumers supply arguments and configuration,
never the verb. Non-passing outcomes carry a standard reason code so reports
can distinguish a missing credential from findings or an incomplete analysis.

Installed as ``.guardrails/adapter.py``. Writes a nested v2 evidence fragment
that ``scan.py`` merges from ``.artifacts/guardrails/evidence/`` and that the
provider workflow templates upload and summarize. Exit status is 0 only when
the provider returned ``passed``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REASON_CODES = {
    "configuration-missing": "A required tool, file, or setting is absent; nothing was scanned.",
    "credential-missing": "The provider credential is not available to this run; nothing was scanned.",
    "authentication-failed": "The provider rejected the credential; nothing was evaluated.",
    "execution-error": "The provider command failed before producing a result.",
    "analysis-incomplete": "The scan was uploaded or started but the provider did not finish evaluating it.",
    "revision-mismatch": "The evidence is not bound to the revision under evaluation.",
    "unsupported-project": "The provider found nothing it can analyze in this repository.",
    "timed-out": "The provider command exceeded the adapter timeout.",
}

PROVIDERS: dict[str, dict[str, Any]] = {
    "snyk-code": {
        "display_name": "Snyk Code",
        "capabilities": ["deep-sast"],
        "binary": "snyk",
        "credential": "SNYK_TOKEN",
        "arguments_variable": "SNYK_CODE_ARGS",
    },
    "snyk-open-source": {
        "display_name": "Snyk Open Source",
        "capabilities": ["dependency-vulnerability"],
        "binary": "snyk",
        "credential": "SNYK_TOKEN",
        "arguments_variable": "SNYK_OPEN_SOURCE_ARGS",
    },
    "fossa": {
        "display_name": "FOSSA",
        "capabilities": ["dependency-vulnerability", "license-compliance"],
        "binary": "fossa",
        "credential": "FOSSA_API_KEY",
        "arguments_variable": "FOSSA_ARGS",
    },
}

AUTHENTICATION_PATTERN = re.compile(
    r"(authentication failed|unauthori[sz]ed|invalid (?:api )?token|api key|api token|status: 40[13]|http 40[13]|\(40[13]\)|not authenticated|missing auth)",
    re.IGNORECASE,
)
TIMEOUT_PATTERN = re.compile(r"(timed? ?out|timeout|still (?:being )?(?:analy[sz]ed|scanned|processed)|not (?:yet )?finished)", re.IGNORECASE)
NO_TARGET_PATTERN = re.compile(r"(could not detect supported target files|no supported (?:files|projects|manifests)|nothing to analy[sz]e|no analysis targets)", re.IGNORECASE)


class Outcome:
    __slots__ = ("status", "code", "message", "evidence")

    def __init__(self, status: str, message: str, *, code: str | None = None, evidence: list[str] | None = None):
        if status not in {"passed", "failed", "blocked", "not_run"}:
            raise ValueError(f"invalid status {status}")
        if status in {"blocked", "not_run"} and code not in REASON_CODES:
            raise ValueError(f"non-passing outcome requires a known reason code, got {code}")
        self.status = status
        self.code = code
        self.message = message
        self.evidence = evidence or []

    def result(self, producer: str) -> dict[str, Any]:
        result: dict[str, Any] = {"producer": producer, "status": self.status}
        if self.status in {"passed", "failed"}:
            result["evidence"] = [bounded(item) for item in (self.evidence or [self.message])]
        else:
            result["reason"] = bounded(f"{self.code}: {self.message}")
        return result


def bounded(text: str, maximum: int = 1000) -> str:
    text = " ".join(text.split())
    return text if len(text) <= maximum else text[: maximum - 3] + "..."


def reason_code(reason: str | None) -> str | None:
    """The standard code at the start of a reason string, if any."""
    if not isinstance(reason, str):
        return None
    head = reason.split(":", 1)[0].strip()
    return head if head in REASON_CODES else None


def run_command(command: list[str], *, cwd: Path, timeout: int, environment: dict[str, str]) -> tuple[int | None, str]:
    try:
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, env=environment)
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") if isinstance(error.stdout, str) else ""
        return None, output
    except OSError as error:
        return -1, str(error)
    return completed.returncode, (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def json_document(output: str) -> Any:
    """The first JSON object or array in the output, when the tool printed one."""
    text = output.strip()
    for start in (text.find("{"), text.find("[")):
        if start < 0:
            continue
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            continue
    return None


def classify_failure(output: str, *, exit_code: int | None, tool: str) -> Outcome:
    """Map a non-zero exit into blocked / not_run with a reason code."""
    text = strip_ansi(output)
    if exit_code is None:
        return Outcome("blocked", f"{tool} exceeded the adapter timeout.", code="timed-out")
    if exit_code == -1:
        return Outcome("not_run", f"{tool} could not be executed: {bounded(text, 200)}", code="configuration-missing")
    if AUTHENTICATION_PATTERN.search(text):
        return Outcome("blocked", f"{tool} rejected the credential (exit {exit_code}).", code="authentication-failed")
    if NO_TARGET_PATTERN.search(text):
        return Outcome("not_run", f"{tool} found no supported targets (exit {exit_code}).", code="unsupported-project")
    if TIMEOUT_PATTERN.search(text):
        return Outcome("blocked", f"{tool} did not finish evaluating the revision (exit {exit_code}).", code="analysis-incomplete")
    return Outcome("blocked", f"{tool} failed with exit {exit_code}: {bounded(text, 300)}", code="execution-error")


def snyk_outcome(exit_code: int | None, output: str, *, command: str, findings_key: str) -> Outcome:
    """Snyk CLI: 0 no issues, 1 issues, 2 error, 3 no supported projects."""
    if exit_code == 0:
        return Outcome("passed", f"{command}: no issues", evidence=[f"{command}: exit 0, no issues"])
    if exit_code == 1:
        document = json_document(output)
        count = None
        if isinstance(document, dict):
            if findings_key == "sarif":
                runs = document.get("runs")
                if isinstance(runs, list) and runs and isinstance(runs[0], dict) and isinstance(runs[0].get("results"), list):
                    count = len(runs[0]["results"])
            elif isinstance(document.get(findings_key), list):
                count = len(document[findings_key])
        detail = f"{count} findings" if count is not None else "findings reported"
        return Outcome("failed", f"{command}: {detail}", evidence=[f"{command}: exit 1, {detail}"])
    if exit_code == 3:
        return Outcome("not_run", f"{command}: no supported projects were found (exit 3).", code="unsupported-project")
    return classify_failure(output, exit_code=exit_code, tool=command)


def run_snyk(provider_id: str, target: Path, *, arguments: list[str], timeout: int, environment: dict[str, str]) -> Outcome:
    if provider_id == "snyk-code":
        command, label, findings_key = ["snyk", "code", "test", "--json", *arguments], "snyk code test", "sarif"
    else:
        command, label, findings_key = ["snyk", "test", "--json", *arguments], "snyk test", "vulnerabilities"
    exit_code, output = run_command(command, cwd=target, timeout=timeout, environment=environment)
    return snyk_outcome(exit_code, output, command=label, findings_key=findings_key)


def fossa_outcome(analyze: tuple[int | None, str], test: tuple[int | None, str] | None) -> Outcome:
    """FOSSA: ``analyze`` uploads; only a completed ``test`` yields a policy result."""
    analyze_code, analyze_output = analyze
    if analyze_code != 0:
        return classify_failure(analyze_output, exit_code=analyze_code, tool="fossa analyze")
    if test is None:
        return Outcome("blocked", "fossa analyze uploaded the scan but fossa test did not run.", code="analysis-incomplete")
    test_code, test_output = test
    if test_code == 0:
        return Outcome("passed", "fossa test: no policy issues", evidence=["fossa analyze: uploaded", "fossa test: exit 0, no issues"])
    text = strip_ansi(test_output)
    if test_code is None:
        return Outcome("blocked", "fossa test exceeded the adapter timeout while waiting for analysis.", code="analysis-incomplete")
    if AUTHENTICATION_PATTERN.search(text):
        return Outcome("blocked", f"fossa test rejected the credential (exit {test_code}).", code="authentication-failed")
    if TIMEOUT_PATTERN.search(text):
        return Outcome("blocked", f"fossa test timed out waiting for the FOSSA analysis (exit {test_code}).", code="analysis-incomplete")
    document = json_document(text)
    issues = document.get("issues") if isinstance(document, dict) else None
    if isinstance(issues, list) or "issue" in text.lower():
        count = len(issues) if isinstance(issues, list) else None
        detail = f"{count} issues" if count is not None else "issues reported"
        return Outcome("failed", f"fossa test: {detail}", evidence=["fossa analyze: uploaded", f"fossa test: exit {test_code}, {detail}"])
    return classify_failure(text, exit_code=test_code, tool="fossa test")


def run_fossa(target: Path, *, revision: str, arguments: list[str], timeout: int, environment: dict[str, str]) -> Outcome:
    analyze = run_command(["fossa", "analyze", "--revision", revision, *arguments], cwd=target, timeout=timeout, environment=environment)
    if analyze[0] != 0:
        return fossa_outcome(analyze, None)
    test = run_command(
        ["fossa", "test", "--revision", revision, "--format", "json", "--timeout", str(timeout)],
        cwd=target, timeout=timeout + 30, environment=environment,
    )
    return fossa_outcome(analyze, test)


def head_revision(target: Path) -> str | None:
    if not shutil.which("git"):
        return None
    completed = subprocess.run(["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=target, text=True, capture_output=True)
    return completed.stdout.strip() if completed.returncode == 0 and completed.stdout.strip() else None


def run_provider(provider_id: str, target: Path, *, revision: str | None, arguments: list[str], timeout: int,
                 environment: dict[str, str] | None = None) -> tuple[str, Outcome]:
    if provider_id not in PROVIDERS:
        raise ValueError(f"unknown provider {provider_id}")
    provider = PROVIDERS[provider_id]
    environment = dict(os.environ) if environment is None else environment
    head = head_revision(target)
    if revision and head and revision != head:
        return revision, Outcome("not_run", f"requested revision {revision[:12]} is not the checked-out HEAD {head[:12]}.", code="revision-mismatch")
    revision = revision or head
    if not revision:
        return "unknown", Outcome("not_run", "the target is not a Git checkout with a resolvable HEAD.", code="revision-mismatch")
    if not environment.get(provider["credential"], "").strip():
        return revision, Outcome("blocked", f"{provider['credential']} is not set for this run.", code="credential-missing")
    if not shutil.which(provider["binary"], path=environment.get("PATH")):
        return revision, Outcome("not_run", f"the {provider['binary']} CLI is not on PATH.", code="configuration-missing")
    if provider_id == "fossa":
        return revision, run_fossa(target, revision=revision, arguments=arguments, timeout=timeout, environment=environment)
    return revision, run_snyk(provider_id, target, arguments=arguments, timeout=timeout, environment=environment)


def fragment(provider_id: str, revision: str, outcome: Outcome) -> dict[str, Any]:
    provider = PROVIDERS[provider_id]
    result = outcome.result(provider["display_name"])
    return {
        "version": 2,
        "subject": {"type": "git-commit", "revision": revision},
        "results": {capability: {provider_id: dict(result)} for capability in provider["capabilities"]},
    }


def write_fragment(document: dict[str, Any], evidence_dir: Path, provider_id: str) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{provider_id}.json"
    if path.is_symlink():
        raise ValueError(f"refusing to write through a symlink: {path}")
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def summary_line(provider_id: str, outcome: Outcome) -> str:
    display = PROVIDERS[provider_id]["display_name"]
    if outcome.status in {"passed", "failed"}:
        return f"{display}: {outcome.status.upper()} — {outcome.message}"
    return f"{display}: {outcome.status.upper()} [{outcome.code}] — {outcome.message}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=sorted(PROVIDERS))
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument("--revision", default="", help="exact revision the evidence must bind to (default: HEAD)")
    parser.add_argument("--args", default=None, help="extra provider arguments; defaults to the provider's *_ARGS variable")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds per provider command")
    parser.add_argument("--evidence-dir", type=Path, default=None, help="default: <target>/.artifacts/guardrails/evidence")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    target = args.target.resolve()
    if not target.is_dir():
        print(f"ERROR target is not a directory: {target}", file=sys.stderr)
        return 2
    provider = PROVIDERS[args.provider]
    raw_arguments = args.args if args.args is not None else os.environ.get(provider["arguments_variable"], "")
    try:
        arguments = shlex.split(raw_arguments)
    except ValueError as error:
        print(f"ERROR invalid {provider['arguments_variable']}: {error}", file=sys.stderr)
        return 2
    revision, outcome = run_provider(args.provider, target, revision=args.revision or None, arguments=arguments, timeout=args.timeout)
    document = fragment(args.provider, revision, outcome)
    evidence_dir = args.evidence_dir.resolve() if args.evidence_dir else target / ".artifacts" / "guardrails" / "evidence"
    try:
        path = write_fragment(document, evidence_dir, args.provider)
    except (OSError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"provider": args.provider, "revision": revision, "status": outcome.status, "reason_code": outcome.code,
                          "message": outcome.message, "fragment": str(path)}, indent=2))
    else:
        print(summary_line(args.provider, outcome))
        print(f"Evidence fragment: {path}")
    return 0 if outcome.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
