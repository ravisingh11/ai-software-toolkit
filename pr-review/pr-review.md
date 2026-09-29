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
truthful without granting it merge authority. The shared workflow consolidates
the result files but does not choose an AI provider.

## Consolidation

Reviewers should avoid unnecessary duplication. When multiple reviewers detect
the same root issue, the overall result should consolidate it rather than
creating four nearly identical comments. The consolidated result should retain
the additional lens-specific evidence when it adds value.

Prioritize material findings over volume of findings.
