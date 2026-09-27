# Verification: `generate-unit-tests`

A skill is **verified** only when a real agent has completed the seeded task
below in each supported client at the current toolkit revision and the
resulting behavior was demonstrated. Fixtures and prose are not verification.

## Seeded task

Fixture: `tooling/tests/fixtures/skills/generate-unit-tests/` (see its `TASK.md`).

`parse_duration` in `durations.py` has no tests. Add tests in the repository's unittest convention that cover the happy path, each failure path, and boundary values, so that breaking any branch fails a test.

## Protocol (per client)

1. Copy the fixture into a fresh Git repository and commit it.
2. Install this skill for the client (`ai-toolkit skills install --skill generate-unit-tests --client <client>`).
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

The synthetic fixture has no coverage producer or target. Record coverage as
unavailable (not passed); judge this seeded run by meaningful behavior tests
and mutation checks, with that coverage limitation explicit in the ledger.

A verified row must include an actual ISO date, agent version, concrete outcome,
and an HTTPS evidence link or `withheld: <reason>` explaining why retained
evidence cannot be shared. Placeholder metadata cannot support a yes claim.
