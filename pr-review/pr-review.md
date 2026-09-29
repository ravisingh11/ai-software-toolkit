# AI PR Review Framework

Every PR should be independently evaluated across four lenses:

1. Engineering
2. QA
3. Security
4. Repository Standards

The reviewers consume the proposed diff and, where available, the application
repository's ground-truth documents. They should not assume that this shared
repository knows application-specific architecture or commands.

## Severity

- `P0` — Critical, blocking.
- `P1` — High, blocking.
- `P2` — Should fix before or near merge; not automatically blocking.
- `P3` — Recommendation or future improvement.

Unresolved `P0` or `P1` findings make the AI review itself unsuccessful and
should be resolved or explicitly triaged. The AI review capability remains
advisory-only: its check or review must not be the sole merge gate.

## Review contract

Each specialist should report:

- What changed.
- What could break.
- Findings with severity, evidence, impact, and a concrete recommendation.
- Whether the finding is blocking.
- Meaningful non-blocking recommendations.
- Verification performed and remaining gaps.

Use the reusable references in `pr-review/references/` for the detailed
finding, verification, deduplication, and rerun conventions. At minimum, each
finding should have a stable ID, severity, status, title, evidence, impact,
recommendation/fix plan, and verification state.

For workflow integration, a reviewer adapter should write one JSON result to
the path in `AI_REVIEW_RESULT`:

```json
{
  "reviewer": "engineering",
  "findings": [
    {
      "id": "ENG-001",
      "severity": "P1",
      "status": "open",
      "blocking": true,
      "summary": "Short description",
      "evidence": "File and line or observable behavior",
      "impact": "What could break and who is affected",
      "recommendation": "Concrete repair",
      "verification": {
        "method": "targeted test",
        "command": "npm test -- route",
        "result": "pending",
        "residualRisk": ""
      }
    }
  ],
  "verification": ["npm test"]
}
```

The Proof scorecard counts each result file by `severity` and by unresolved
`P0`/`P1` findings (any `status` other than `resolved`; a missing status is
open), using the severities and statuses in
`references/finding-format.md`. A file with any other severity or status gets
no counts. Only counts are published, never finding text or evidence.

The adapter must exit non-zero when it cannot complete the review or when
unresolved `P0`/`P1` findings are present. This keeps the review outcome
truthful without granting it merge authority. The shared workflow
(`workflows/ai-pr-review.yml`) runs on `pull_request_target` and runs
`AI_REVIEW_COMMAND` from the default branch, with `ANTHROPIC_API_KEY` from the
`proof-providers` environment, so a pull request cannot change or run code
next to the key. An optional `AI_REVIEW_SETUP_COMMAND` installs the default
branch's dependencies first in a separate step without the key. Fork pull
requests are not reviewed unless `PROOF_PROVIDERS_SCAN_FORKS` is `true`. The workflow gives the
review command `AI_REVIEW_ROLE`, `AI_REVIEW_RESULT`,
`AI_REVIEW_TARGET` (the head checkout), `AI_REVIEW_BASE_SHA`,
`AI_REVIEW_HEAD_SHA`, and `AI_REVIEW_MODEL`. No pull-request code runs in the
review jobs. The consolidation job summarizes the result files and never
fails, so each role's own check carries its outcome.

`tooling/ai_review_claude.py` is an opt-in reference adapter that sends the
merge-base diff, this framework's role instructions, and the base branch's
ground truth (the root `AGENTS.md`, the documents in
`.proof/ground-truth-ai.yaml` or, only when that file is absent, the
repository-standards list, plus any `AGENTS.md` above a changed file) to
Claude with a structured-output schema matching the finding format,
including each finding's verification state. It treats the diff as
untrusted data, refuses a diff above its size limit instead of truncating it,
uses server-side refusal fallbacks on models that accept them, and writes no
result when the review cannot be completed.

## Consolidation

Reviewers should avoid unnecessary duplication. When multiple reviewers detect
the same root issue, the overall result should consolidate it rather than
creating four nearly identical comments. The consolidated result should retain
the additional lens-specific evidence when it adds value.

Prioritize material findings over volume of findings.
