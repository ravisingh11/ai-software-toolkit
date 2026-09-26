# Verification: `dependency-upgrade`

A skill is **verified** only when a real agent has completed the seeded task
below in each supported client at the current toolkit revision and the
resulting behavior was demonstrated. Fixtures and prose are not verification.

## Seeded task

Fixture: `tooling/tests/fixtures/skills/dependency-upgrade/` (see its `TASK.md`).

Advisory `GHSA-SEED-0001` affects `requests<2.32.0`. Upgrade `requests` in `requirements.txt` to a version that resolves the advisory using pip's own resolution, keep other pins unchanged, run the tests, and write the rollback note.

## Protocol (per client)

1. Copy the fixture into a fresh Git repository and commit it.
2. Install this skill for the client (`ai-toolkit skills install --skill dependency-upgrade --client <client>`).
3. Ask the agent to perform the task using the skill by name.
4. Capture: the agent's outcome report, `git diff` of the result, and the
   output of the verification commands the report names.
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
