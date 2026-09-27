# Verification: `fix-ci`

A skill is **verified** only when a real agent has completed the seeded task
below in each supported client at the current toolkit revision and the
resulting behavior was demonstrated. Fixtures and prose are not verification.

## Seeded task

Fixture: `tooling/tests/fixtures/skills/fix-ci/` (see its `TASK.md`).

The seeded repository's unit test fails because `calc.divide` returns the wrong value for negative divisors. Make `python3 -m unittest discover` pass with a code fix, not a test change.

## Protocol (per client)

1. Copy the fixture into a fresh Git repository and commit it.
2. Install this skill for the client (`ai-toolkit skills install --skill fix-ci --client <client>`).
3. Ask the agent to perform the task using the skill by name.
4. Commit the fix, then rerun the checks in the clean worktree. Capture the
   initial and fixed SHAs, `git diff <initial-sha>..<fixed-sha>`, the agent's
   outcome report, and check output bound to the fixed SHA.
5. Judge the demonstration against the skill's Verification section; record
   the row below with `yes` only when every listed check passed.

Store transcripts and diffs outside the repository (they may contain
environment details); link them from the row when they are shareable.

## Ledger

| Client | Verified | Date | Toolkit revision | Agent version | Outcome | Evidence link |
| --- | --- | --- | --- | --- | --- | --- |
| codex | no | — | — | — | — | — |
| claude-code | no | — | — | — | — | — |

A row is stale once `SKILL.md` or the fixture changes after the recorded
revision; `tooling/validate-skills.py` requires both rows to exist.
