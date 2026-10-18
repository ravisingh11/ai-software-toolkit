# Codex Standards

These standards keep Codex-generated work useful, auditable, and safe across
repositories.

## File Structure

Use repo-local guidance when behavior depends on that repository:

- `AGENTS.md`: canonical repo instructions for Codex and humans.
- `CODEX.md`: optional Codex-specific quick reference when a repo needs one.
- `.codex/`: optional local Codex workflows, prompts, or generated notes that
  should be versioned for the repo.
- `docs/ai/`: longer AI operating notes, prompt packs, and review checklists.
- `.specify/`: optional Spec Kit project state for spec-driven feature work.

Use centralized guidance only for defaults that apply across repositories.

Reusable templates live in this repository:

- `templates/AGENTS.md`
- `templates/CODEX.md`
- `skills/`
- `prompts/`
- `docs/agent-workflows/`

## Recommended Repo-Level Sections

Each production repo should eventually have an `AGENTS.md` with:

- Project purpose and deployable surfaces.
- Required setup commands.
- Build, test, lint, and smoke-test commands.
- Branch, commit, and change-summary expectations.
- Security and secret-handling rules.
- Known validation gaps or environment limitations.
- Do-not-touch areas and generated files.

## Agent Operating Rules

- Inspect the repo before making assumptions.
- Preserve unrelated user changes.
- Keep commits scoped to a single coherent outcome.
- Run the narrowest meaningful verification first, then broader checks when
  risk justifies it.
- Treat CI as an explicit repository decision. Do not add workflow files or
  hosted runner dependencies unless the repository has selected that model.
- Prefer the narrowest reproducible verification that matches the repository's
  documented release process.
- Pull requests are the normal change path, including for solo-developer
  repositories. Repository rulesets may require additional approvals as the
  team grows.
- Never commit secrets, local credentials, customer data, or private logs.
- Do not rewrite history or delete branches unless explicitly requested.
- Prefer product-safe copy and production UI over demo/spec language.
- Use Spec Kit for substantial feature work when the repository has opted into
  spec-driven development.

### Workspace Hygiene Lifecycle

Adopt the Workspace Hygiene section of `templates/AGENTS.md` in consuming
repositories, preserving their existing instructions and generated markers.
Keep repository-specific paths, ownership, artifact retention, and verified
cleanup commands in the consuming repository. `AGENTS.md` guides behavior;
it is not an autonomous scheduler or an enforcement mechanism. Any automated
cleanup needs a separately configured owner, execution mechanism, and verified
safety checks.

At task start, inspect status, branches, registered worktrees, relevant open
PRs, and active ownership. Preserve primary/default, locked, shared, and active
checkouts. Record task-owned scratch paths and processes, and choose a named
artifact location for reusable outputs and release evidence. Temporary names
and age alone do not establish disposability.

When cleanup is requested, fetch fresh upstream state and verify current PR
ownership. Require exact commit reachability from the intended upstream target
before ordinary local branch/worktree removal. Committed or pushed work may
still be unmerged. Preserve local-only commits and check tracked, untracked,
and ignored state, nested Git repositories/submodules, local databases and
configuration, active processes, and task ownership. Recheck immediately before
acting. Every Git/API error blocks the affected cleanup; an empty failed query
must never count as proof of safety.

Record paths, before/after refs, preservation evidence, retained blockers, and
recovery refs or archive manifests. Prefer application-managed archival for
managed worktrees; otherwise use `git worktree remove` without force. Keep
squash/cherry-pick equivalents for explicit review or a verified recoverable
archive. Patch equivalence and empty `git cherry` output never justify force
deletion. Avoid broad temporary-directory deletion and global `git clean`.
Archival must preserve needed ignored files explicitly; do not assume a Git
snapshot captures them.

At completion, stop task-owned processes and remove only task-created,
disposable scratch after consumers stop. Report the disposition of branches,
PRs, worktrees, scratch, and retained release evidence. The explicit-request
requirement for branch deletion remains in force. Remote branch deletion and
PR merge/closure require explicit task authority and fresh applicable checks;
local cleanup does not imply permission for those actions.

## Prompt And Skill Files

- This toolkit publishes reusable prompts in `prompts/`, skills in `skills/`,
  and workflow guides in `docs/agent-workflows/`.
- Consuming repositories choose their own documentation hierarchy; `docs/ai/`
  is one option. Install executable skills in the agent tool's discovery path,
  such as `.agents/skills/`, rather than duplicating their instructions.
- Include inputs, expected outputs, and verification steps in every reusable
  workflow.
- Avoid storing one-off chat transcripts unless they are curated into a durable
  decision record.
