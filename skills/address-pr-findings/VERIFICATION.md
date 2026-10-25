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

For a `yes` row, set Outcome to `passed` only after every required check passes.
Keep failed, blocked, or inconclusive runs marked `no`.

| Client | Verified | Date | Toolkit revision | Agent version | Outcome | Evidence link |
| --- | --- | --- | --- | --- | --- | --- |
| codex | yes | 2026-10-24 | 984f34aecfb1aa57b96fb3b2823d79d5b06717dd | codex-cli 0.163.0 | passed | withheld: maintainer retains raw client transcripts and fixture bundles; sanitized output and hosted outcome evidence in docs/verification/action-skills/codex/README.md |
| claude-code | no | — | — | — | not run; Codex-only verification selected | — |

A row is stale once `SKILL.md` or the fixture changes after the recorded
revision; `tooling/validate-skills.py` requires both rows to exist.

A verified row must include an actual ISO date, agent version, concrete outcome,
and an HTTPS evidence link or `withheld: <reason>` explaining why retained
evidence cannot be shared. Placeholder metadata cannot support a yes claim.

See the [shared real-client protocol](../../docs/skill-verification.md) and [captured Codex output](../../docs/verification/action-skills/codex/README.md). Invocation and hosted outcome evidence are separate.
