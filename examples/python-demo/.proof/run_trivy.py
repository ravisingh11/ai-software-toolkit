#!/usr/bin/env python3
"""Run one independent Trivy scan; empty or unusable reports never pass."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile


def target_path(root: Path, value: str) -> Path:
    root = root.resolve()
    target = (root / value).resolve(strict=True)
    target.relative_to(root)
    if target.is_dir():
        if any(path.is_symlink() for path in target.rglob("*")):
            raise ValueError("scan target contains a symlink; choose a regular source subtree")
    return target


def inspect_report(report: dict, mode: str) -> dict:
    if not isinstance(report, dict) or report.get("SchemaVersion") != 2 or not isinstance(report.get("Results"), list):
        raise ValueError("Trivy report is missing its version or results")
    if any(report.get(key) for key in ("Error", "Errors", "error", "errors")):
        raise ValueError("scanner reported incomplete execution")
    inspected = findings = 0
    for row in report["Results"]:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) and row[key] for key in ("Target", "Class", "Type")):
            raise ValueError("invalid Trivy result")
        if mode == "iac":
            if row["Class"] != "config":
                raise ValueError("expected an IaC scan result")
            summary = row.get("MisconfSummary", {})
            if not isinstance(summary, dict):
                raise ValueError("invalid misconfiguration summary")
            for key in ("Successes", "Failures"):
                count = summary.get(key, 0)
                if type(count) is not int or count < 0:
                    raise ValueError("invalid misconfiguration count")
                inspected += count
            entries = row.get("Misconfigurations") or []
        else:
            if row["Class"] not in {"os-pkgs", "lang-pkgs"}:
                raise ValueError("expected a package vulnerability scan")
            packages = row.get("Packages") or []
            if not isinstance(packages, list) or any(not isinstance(package, dict) or not isinstance(package.get("Name"), str) or not package["Name"] for package in packages):
                raise ValueError("invalid package inventory")
            inspected += len(packages)
            entries = row.get("Vulnerabilities") or []
        if any(row.get(key) for key in ("Error", "Errors", "error", "errors")):
            raise ValueError("scanner target reported incomplete execution")
        if not isinstance(entries, list):
            raise ValueError("invalid findings")
        if mode == "iac" and sum(isinstance(entry, dict) and entry.get("Status") == "FAIL" for entry in entries) != summary.get("Failures", 0):
            raise ValueError("IaC findings do not match the failure count")
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("Severity") not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("invalid finding severity")
            if mode == "iac" and entry.get("Status") not in {"PASS", "FAIL", "EXCEPTION"}:
                raise ValueError("invalid IaC result status")
            if mode != "iac" or entry.get("Status") == "FAIL":
                findings += entry["Severity"] in {"HIGH", "CRITICAL"}
    if not inspected:
        raise ValueError("no supported inputs were inspected; an empty scan is not a pass")
    return {"inspected": inspected, "high_or_critical": findings,
            "status": "failed" if findings else "passed"}


def run_scan(mode: str, target: str, root: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=False)
    if mode == "image":
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]*@sha256:[a-f0-9]{64}", target):
            raise ValueError("image must be a registry reference pinned by sha256 digest")
        resolved = target
    else:
        resolved = str(target_path(root, target))
    with tempfile.TemporaryDirectory(prefix="proof-trivy-") as directory:
        config = Path(directory) / "trivy.yaml"
        config.write_text("{}\n")
        command = ["trivy", "--config", str(config), "--cache-dir", str(Path(directory) / "cache")]
        version = json.loads(subprocess.check_output([*command, "version", "--format", "json"], timeout=60))
        if version.get("Version") != "0.76.0":
            raise ValueError("expected pinned Trivy 0.76.0")
        base_command = list(command)
        command += [{"dependencies": "fs", "iac": "config", "image": "image"}[mode]]
        command += ["--ignorefile", "", "--format", "json", "--exit-code", "0",
                    "--output", str(output / "report.json")]
        if mode == "iac":
            command += ["--include-non-failures"]
        else:
            command += ["--scanners", "vuln", "--list-all-pkgs", "--ignore-unfixed=false"]
        if mode == "image":
            command += ["--image-src", "remote"]
        subprocess.run([*command, resolved], check=True, timeout=900)
        if mode != "iac":
            version = json.loads(subprocess.check_output([*base_command, "version", "--format", "json"], timeout=60))
            updated = datetime.fromisoformat(version["VulnerabilityDB"]["UpdatedAt"].replace("Z", "+00:00"))
            if not 0 <= (datetime.now(timezone.utc) - updated).total_seconds() <= 172800:
                raise ValueError("vulnerability database is not current")
        (output / "trivy-version.json").write_text(json.dumps(version, indent=2) + "\n")
        result = inspect_report(json.loads((output / "report.json").read_text()), mode)
        if mode == "image":
            subprocess.run([*base_command, "image", "--image-src", "remote",
                            "--format", "cyclonedx", "--output", str(output / "sbom.cdx.json"), resolved],
                           check=True, timeout=900)
            sbom = json.loads((output / "sbom.cdx.json").read_text())
            if sbom.get("bomFormat") != "CycloneDX" or not sbom.get("components"):
                raise ValueError("image SBOM is empty or invalid")
    (output / "summary.json").write_text(json.dumps({"mode": mode, "target": target, **result}, indent=2) + "\n")
    print(json.dumps(result))
    return 1 if result["high_or_critical"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dependencies", "iac", "image"), required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run_scan(args.mode, args.target, args.root, args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"BLOCKED: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
