# Verification: `fix-security-finding`

A skill is **verified** only when a real agent has completed the seeded task
below in each supported client at the current toolkit revision and the
resulting behavior was demonstrated. Fixtures and prose are not verification.

## Seeded task

Fixture: `tooling/tests/fixtures/skills/fix-security-finding/` (see its `TASK.md`).

Semgrep reports `python.lang.security.audit.subprocess-shell-true` at `runner.py:6`: user-controlled `name` reaches `subprocess.run(..., shell=True)`. Confirm reachability, remediate without `shell=True`, and add a regression test that fails on the old code.

## Protocol (per client)

1. Copy the fixture into a fresh Git repository and commit it.
2. Install this skill for the client (`ai-toolkit skills install --skill fix-security-finding --client <client>`).
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
