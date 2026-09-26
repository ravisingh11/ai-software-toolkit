# Test plans, findings, and regression follow-up

The generated `qa` skill reads two version-controlled directories beside its
`config.yaml`. Both are optional; when absent, the orchestrator behaves as
before and derives scenarios from the diff and the sub-skill flow menus.

```text
<skills-dir>/qa/
  plans/<app>.yaml        # editable test plans, one per app
  findings/<id>.md        # human-reported and confirmed defects
```

## Plans: `plans/<app>.yaml`

A plan captures what the team agreed to verify for an app: acceptance
criteria, risks, personas, negative cases, and exploratory prompts. QA
participates in writing it before implementation, not only after.

```yaml
version: 1
app: web
acceptance:
  - id: checkout.total                 # [a-z0-9][a-z0-9.-]{0,63}
    statement: The order total equals the sum of line items plus shipping.
    personas: [member, guest]
    flows: [F3]                        # sub-skill flow ids, when one exists
risks:
  - id: checkout.currency
    statement: Rounding differs between display and charge in non-USD carts.
    likelihood: medium                 # low | medium | high
    impact: high
negative:
  - id: checkout.negative-1
    statement: A cart with zero items cannot check out.
    expect: The checkout button is disabled and no order is created.
exploratory:
  - id: checkout.explore-discounts
    prompt: Stack every discount type and look for totals below zero.
    time_box_minutes: 10
```

Rules the orchestrator follows:

- A change run selects the plan entries whose `flows` or `personas` touch
  the affected app; a smoke or release run selects every `acceptance` and
  `negative` entry marked in the sub-skill as `Smoke: yes` or the whole plan
  when the user asks for a full run.
- Every executed plan entry produces a result row with `scenario: <id>`.
  Entries that could not be exercised produce a BLOCKED or INCONCLUSIVE row
  with the reason; they are never silently skipped.
- Exploratory prompts are time-boxed. Their rows carry `origin: agent` and
  describe what was tried; a defect found there becomes a finding.
- Existing unit, API, and browser suites are reused, not reimplemented: a
  plan entry may set `command: npm test -- checkout` and the orchestrator
  records that row with `origin: deterministic` and the command's exit code.

## Findings: `findings/<id>.md`

A finding is a defect a person or an agent observed. Humans add findings by
hand; the orchestrator adds agent findings only as `action_required`
suggestions until a person confirms them.

```markdown
---
id: qa-0007
status: confirmed          # reported | confirmed | fixed | wont-fix
app: web
scenario: checkout.negative-1
origin: human              # human | agent
reported: 2026-09-26
regression: tests/e2e/checkout-empty-cart.spec.ts   # test that now protects this
rerun: pending             # pending | pass | fail
---

# Empty cart can reach the payment step

Steps, expected, actual, environment.
```

Rules:

- A `confirmed` finding with a `regression` path is rerun on every change run
  that affects its app. The result row carries `finding: <id>`, `origin:
  deterministic` when it is an automated test or `origin: agent` when the
  orchestrator reproduces the steps, and the orchestrator reports the rerun
  result in its summary; it never edits the finding file.
- A finding without `regression` produces an `action_required` entry naming
  the missing test until one is added.
- Marking a finding `fixed` is a human decision made after a passing rerun.

## Result rows

Each `summary.json` row may carry three optional fields in addition to the
required ones: `origin` (`deterministic`, `agent`, or `human`; default
`agent`), `scenario` (a plan entry id), and `finding` (a finding id). The
trusted renderer shows Origin and Scenario / Finding columns so deterministic,
agent, and human evidence appear together and remain distinguishable.

## Status semantics at the Guardrails boundary

`overall` precedence is `fail`, then `blocked` (any BLOCKED **or FLAKY** row),
then `inconclusive`, then `pass`. A pass on retry is not proof, so a FLAKY row
blocks the run; the report states `Overall: BLOCKED — analysis-incomplete`.
The `QA / report` check therefore succeeds only for a fully passing run, and
the Guardrails `functional-qa` capability records `passed` only from that
check. Functional QA stays advisory.
