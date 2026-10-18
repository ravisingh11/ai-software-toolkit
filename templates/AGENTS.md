# AGENTS.md

## Project Purpose

Describe what this repository owns, who uses it, and which surfaces are
deployable.

## Repository Layout

- `apps/`: deployable applications.
- `packages/`: shared packages.
- `docs/`: product, architecture, and operational documentation.
- `.github/`: repo-local GitHub automation and templates.

Update this section to match the actual repository.

## Setup

```bash
# Add repo-specific install/setup commands here.
```

## Verification

List the narrowest useful checks first.

```bash
# Example:
# pnpm test
# pnpm build
```

## Commit Standard

Use concise, auditable commit messages:

```text
<type>: <imperative summary>
```

Examples:

```text
fix: preserve document ownership on admin edits
feat: add tenant-level billing controls
chore: mark repo private
docs: document deployment rollback path
```

## Agent Rules

- Inspect the repo before making assumptions.
- Preserve unrelated local changes.
- Keep commits scoped to one coherent outcome.
- Reference the owning issue in commits or handoff notes when useful.
- Pull requests are required for default-branch changes. A single-developer
  repository may use zero required approvals; teams can raise the approval
  count as their review needs grow.
- Do not commit secrets, credentials, customer data, or private logs.
- Prefer targeted verification before broad test suites.
- Do not rewrite history or delete branches unless explicitly requested.
- Document skipped checks and the reason they were skipped.

## Workspace Hygiene

- At task start, inspect status, the current branch, registered worktrees,
  relevant open PRs, and active task ownership. Reuse a suitable checkout;
  preserve primary/default, locked, shared, and actively used worktrees.
- Record task-owned scratch paths and processes. Retain release evidence and
  reusable outputs in a named artifact location; unknown temporary files are
  not disposable merely because of their age or name.
- When cleanup is requested, fetch the intended upstream and verify current
  PR state. Committed or pushed does not mean merged: require exact commit
  reachability from the intended upstream target before ordinary removal.
  Fail closed on Git or API errors; missing results are not safety evidence.
- Before removal, check tracked, untracked, and ignored files, nested Git
  repositories/submodules, active processes, and checkout ownership. Preserve
  local-only commits, local databases/configuration, and evidence. A clean
  tracked-file status alone is insufficient; recheck immediately before acting.
- Record paths, before/after refs, preservation evidence, and recovery refs or
  archive manifests. Use the application's archive operation for managed
  worktrees; otherwise use `git worktree remove` without force. Do not use
  broad temporary-directory deletion or global `git clean`. Preserve needed
  ignored files separately; a Git snapshot may omit them.
- Squash/cherry-pick equivalence is not exact reachability. Retain these
  branches/worktrees for explicit review or a verified recoverable archive;
  never force-delete based on patch equivalence or empty `git cherry` output.
- At completion, stop task-owned processes and remove only task-created,
  disposable scratch after its consumers stop. Report branch, PR, worktree,
  scratch, and retained-evidence disposition, including blockers. Branch
  deletion still requires an explicit request; remote deletion and PR
  merge/closure require explicit task authority and current checks.

These instructions guide agent behavior; they do not schedule cleanup or
enforce retention automatically. Verify repo-specific cleanup commands before
using them.

## Security Notes

- Treat auth, permissions, billing, customer data, and deployment config as
  high-risk surfaces.
- Use `type:security` for confirmed security/privacy work.
- Never paste secrets into issue bodies, PR text, commits, or logs.

## Known Gaps

Document repo-specific validation gaps, flaky tests, missing credentials, or
deployment limitations here.
