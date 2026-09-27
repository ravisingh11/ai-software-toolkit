---
name: fix-ci
description: "Diagnose a failing CI check or local validation command, reproduce it, apply the smallest safe fix, and prove the check passes again. Use when a build, test, lint, or workflow job is red and the task is to make it green without hiding the failure."
---

# Fix CI

Make a red check green by fixing the cause, never by weakening the check.
This is an action skill: it changes code and proves the change. Review-only
analysis belongs to `github-actions-hardening` (workflow posture) and
`full-test-suite` (broad scan-fix loops); reuse their guidance instead of
restating it.

## Inputs

- The failing check: its name, the workflow or command, and the log or the
  `ai-toolkit check` row (status `failed`, reason, evidence link).
- The repository's validation commands (`GUARDRAILS_*_COMMAND` values,
  `AGENTS.md`, or `ai-toolkit discover` output).
- The base revision the check last passed on, when known.

## Permitted changes

- Application code, tests, and build or lint configuration that caused the
  failure.
- Workflow files only when the failure is in the workflow itself (wrong
  command, missing setup step, wrong runner tool) and the fix keeps the check's
  name, trigger, permissions, and pinned action versions unchanged.

Not permitted without an explicit instruction from the user: skipping or
deleting tests, marking checks `continue-on-error`, loosening lint or coverage
thresholds, pinning to a broken dependency version to silence a failure, or
changing `.guardrails/` policy modes.

## Method

1. Reproduce locally with the exact command the check runs; if it cannot be
   reproduced, say so and stop at diagnosis.
2. Find the first failure, not the last symptom; read the log upward.
3. Classify: product bug, test bug, environment or dependency drift, or
   workflow misconfiguration.
4. Apply the smallest change that addresses the classified cause.
5. Rerun the exact command; then run the repository's other required checks
   that the change could affect.

## Stop conditions

Stop and report instead of guessing when: the failure is intermittent and does
not reproduce twice; the fix would need a dependency major upgrade (hand off to
`dependency-upgrade`); the failing check is a security scanner (hand off to
`fix-security-finding`); or the correct behavior is ambiguous and a test and
the code disagree.

## Verification

- The exact failing command now exits 0 in a clean worktree.
- Related checks still pass; list the commands run.
- `ai-toolkit check` (when installed) shows the capability `passed` for the
  new revision.

## Outcome report

```text
Check: <name> — was failing at <sha>; passes at <new sha>
Cause: <one sentence, classified>
Change: <files touched, why minimal>
Verified: <commands run and results>
Not done / risk: <anything deferred or uncertain>
```
