---
name: "toolkit-setup"
description: "Set up or refresh AI Software Toolkit in a repository through the ai-toolkit CLI: discover the project, preview the installation, apply Guardrails, skills, and QA bootstrap, then verify with doctor and check. Use when asked to install, set up, onboard, upgrade, or diagnose the toolkit or Guardrails."
---

# Toolkit Setup

Install or refresh the toolkit with the shared `ai-toolkit` CLI. This skill
runs the CLI and reports its output; it contains no discovery or installation
logic of its own, so the GitHub, CLI, and agent entry points behave the same.

## Locate the CLI

Use the first that applies:

1. `ai-toolkit.pyz` in the repository or a release download:
   `python3 ai-toolkit.pyz <command>`.
2. A checkout of the toolkit source:
   `python3 <toolkit-root>/tooling/ai_toolkit <command>`.

Python 3.11+ is the only prerequisite. Never install the archive from an
unpinned URL; verify `ai-toolkit.pyz.sha256` against the release asset first.

## Workflow

1. **Discover** (read-only): `ai-toolkit discover --target .`
   Report detected languages, proposed repository variables, existing
   integrations, and detected agent clients. Do not guess commands the
   discovery could not find; ask.
2. **Preview**: `ai-toolkit init --target . --preview`
   Show the user the planned files, skills, and variables. Nothing is written.
3. **Apply** only after the user confirms:
   `ai-toolkit init --target . --yes [--clients codex,claude-code] [--profile github]`
   Add `--apply-variables` only when `gh` is authenticated and the user wants
   the discovered commands stored as GitHub repository variables. Commands are
   never written to committed files.
4. **Diagnose**: `ai-toolkit doctor --target .`
   Explain each component and capability as installed, configured, or
   verified. `doctor` never executes producers; a `verified` state comes only
   from existing revision-bound evidence.
5. **Check**: `ai-toolkit check --target .`
   Report what ran, what failed, what remains unverified, and the next action
   for each. Failed capabilities name a repair skill; running it is a separate,
   explicit step.
6. **Refresh** an existing installation: `ai-toolkit update --target . --dry-run`
   then `ai-toolkit update --target .`. Modified managed files are preserved
   and listed as conflicts; `--rollback` restores the recorded backup.

## Decision rules

- Existing workflows and provider integrations are reported, not duplicated.
- `.guardrails/policy.yaml` and `providers.yaml` stay authoritative; change
  them with `.guardrails/configure.py` or `ai-toolkit providers select`.
- Commit `toolkit.toml`, `toolkit.lock.json`, `.guardrails/`, installed
  skills, and workflows together. Do not commit `.artifacts/`.
- An installation is not a pass. Say which capabilities remain unverified.
