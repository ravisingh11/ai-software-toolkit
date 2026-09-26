# Verification: `address-pr-findings`

A skill is **verified** only when a real agent has completed the seeded task
below in each supported client at the current toolkit revision and the
resulting behavior was demonstrated. Fixtures and prose are not verification.

## Seeded task

Fixture: `tooling/tests/fixtures/skills/address-pr-findings/` (see its `TASK.md`).

`findings.json` holds three review findings for `store.py`: a P1 (missing input validation), a P2 (unbounded cache), and a P3 (naming). Resolve P1 and P2 with verified changes, decide P3 with a written reason, and update every finding's status and verification block.

## Protocol (per client)

1. Copy the fixture into a fresh Git repository and commit it.
2. Install this skill for the client (`ai-toolkit skills install --skill address-pr-findings --client <client>`).
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
