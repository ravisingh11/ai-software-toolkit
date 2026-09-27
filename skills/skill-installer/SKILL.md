---
name: skill-installer
description: "Install Codex or Claude Code skills from this standards repository into the selected client skills directory using the bundled shell installer. Use when asked to install, refresh, list, or sync canonical skills for Codex or Claude Code."
---

# Skill Installer

Use this skill to install or refresh canonical Codex or Claude Code skills from the standards repository.

## Workflow

1. Confirm the repository root contains `tooling/install-skills.sh` and `skills`.
2. List skills before installing when the target set is unclear.
3. Use `--dry-run` before broad installs when the target directory already has local custom skills.
4. Choose an existing-skill policy: prompt interactively, `--skip-existing`, `--merge-existing`, or `--replace-existing`.
5. Choose the client explicitly: `--client codex` installs into
   `${CODEX_HOME:-$HOME/.codex}/skills`; `--client claude-code` installs into
   `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills`. `--target` overrides either.
   Pass the chosen client on every install and dry-run command.
6. Verify the installed skill folders contain `SKILL.md` and, for canonical skills, `agents/openai.yaml`.

## Commands

```bash
# Claude Code installation preview and install.
tooling/install-skills.sh --client claude-code --all --dry-run
tooling/install-skills.sh --client claude-code --all --skip-existing

# See available skills.
tooling/install-skills.sh --list

# Preview a full install without changing the target directory.
tooling/install-skills.sh --all --dry-run

# Install all skills, prompting if a skill already exists.
tooling/install-skills.sh --all

# Non-interactive safe mode: install missing skills and skip existing skills.
tooling/install-skills.sh --all --skip-existing

# Refresh installed skills by adding missing files while preserving local edits.
tooling/install-skills.sh --all --merge-existing

# Install a selected subset.
tooling/install-skills.sh --skill repo-admin-hygiene --skill license-compliance

# Install into an explicit target directory.
tooling/install-skills.sh --all --target "$HOME/.codex/skills"
```

## Decision Rules

- Existing target skills are not overwritten by default.
- In interactive shells, the installer prompts on each existing skill: skip, merge missing files only, or replace.
- In non-interactive shells, existing skills are skipped unless `--merge-existing` or `--replace-existing` is provided.
- `--merge-existing` uses `rsync --ignore-existing`, so existing local files are preserved.
- `--replace-existing` uses `rsync --delete` and should be used only when the canonical copy should fully replace the installed skill.
- `_shared-project-ops` is installed automatically when present because audit skills depend on it.
- Do not install machine-local or personal-memory skills into this standards bundle.
- Use selected installs when a repo or machine should not receive the full skill set.
- Use `--all --dry-run --skip-existing` to see which local skills would be newly installed versus skipped.

## Verification

- Run `tooling/install-skills.sh --list` from the standards repo.
- Run a dry run before a broad install.
- Test collision handling with `--skip-existing` or `--merge-existing` before using `--replace-existing`.
- After install, verify a representative target skill contains `SKILL.md` in
  the selected client directory; verify it is discoverable by that client.

## Troubleshooting

- If a skill does not appear after install, confirm the selected client and `--target`; check `CODEX_HOME` for Codex or `CLAUDE_CONFIG_DIR` for Claude Code.
- If local edits should be preserved, use `--merge-existing`, not `--replace-existing`.
- If a stale local file must be removed, use `--replace-existing` for that selected skill after reviewing the target directory.
