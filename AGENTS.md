# Repository instructions

This repository defines shared engineering policy and the Proof runtime.
Keep changes small, evidence-backed, and reusable across application
repositories.

## Source-of-truth boundaries

- `policies/` defines engineering requirements and the control catalog.
- `pr-review/` defines AI review behavior.
- `workflows/` and `.github/workflows/` define reusable and repository CI.
- `proof/` and `tooling/` implement deterministic evaluation and setup.
- `rulesets/` defines GitHub enforcement templates.
- `skills/` contains reusable agent instructions.
- `examples/` demonstrates consumption without becoming organization policy.

Do not add application-specific architecture, credentials, customer data, or
private repository details here. A consuming repository owns its own
`AGENTS.md`, architecture, testing, security, deployment, and contribution
ground truth.

This repository has no application database or migration framework. Adding a
database migration surface requires replacing the no-migrations validator with
the chosen framework's real migration validation command in the same change.

## Change contract

- Use a pull request for every normal change to the default branch.
- No approving review is required for a solo maintainer unless the repository
  ruleset is intentionally strengthened.
- Keep controls advisory until their producer, evidence, status-check name,
  failure behavior, and owner have been verified on representative changes.
- Never report a missing, skipped, stale, or unconfigured producer as passed.
- Keep provider credentials in GitHub secrets or the provider platform; never
  commit them.
- Preserve the `.proof/` public runtime contract and document migrations.

## Choose a skill for the task

Read the applicable canonical `skills/<name>/SKILL.md` before using its procedure.
This is the toolkit source repository; installed consumers use their selected
`.agents/skills/` (Codex) or `.claude/skills/` (Claude Code) copies instead.

| Task | Skill |
| --- | --- |
| Establish repository boundaries and evidence | `prepare-safe-change` |
| Review a change | `code-review` |
| Assess dependency risk; implement an upgrade | `dependency-risk-review`; `dependency-upgrade` |
| Repair documentation or onboarding | `docs-sync` |
| Diagnose and fix failing CI | `fix-ci` |
| Assess release readiness | `release-readiness` |
| Review cleanup and repository metadata | `repo-admin-hygiene` |
| Review overall repository health | `project-health-check` |

Select only skills relevant to the task. User limits on tests and external
actions take precedence over a skill's generic procedure. When local tests are
excluded, use hosted CI and report unavailable verification honestly. Reading a
skill or installing its files is not evidence of successful execution; report
the skill revision, task revision, actual actions and linked results separately.
See [skill onboarding](docs/skill-onboarding.md).

## Verification

Run the smallest relevant checks while working. Before opening or updating a
pull request, run the complete repository validation:

```sh
tooling/build.sh
tooling/test.sh
PROOF_COVERAGE_BASE_REF=origin/main tooling/changed_code_coverage.sh
python3 examples/python-demo/tools/validate_demo.py --documentation
python3 tooling/validate-skills.py
python3 tooling/validators/validate_repository.py
python3 tooling/validators/validate_documentation.py
python3 tooling/validators/validate_no_migrations.py
tooling/lint.sh
git diff --check
```

Update the canonical policy or documentation whenever behavior changes. State
which controls are advisory, enforced, not activated, or awaiting a real
producer; do not imply that a workflow file alone proves activation.

<!-- BEGIN WORKSPACE HYGIENE:20261018 -->
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
<!-- END WORKSPACE HYGIENE:20261018 -->
