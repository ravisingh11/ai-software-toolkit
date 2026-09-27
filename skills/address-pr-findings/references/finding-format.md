# PR Review Finding Format

Use one finding per distinct root cause. Findings should be concrete enough
for an engineer to reproduce, fix, and verify.

```json
{
  "id": "SEC-001",
  "severity": "P1",
  "status": "open",
  "blocking": true,
  "title": "Short actionable title",
  "surface": "API authorization",
  "evidence": ["src/routes/admin.ts:42"],
  "impact": "Unauthenticated users can reach an administrative operation.",
  "fixPlan": "Require the repository-approved authorization policy.",
  "verification": {
    "method": "targeted test",
    "command": "npm test -- admin-route",
    "result": "pending",
    "residualRisk": ""
  }
}
```

Allowed severities are `P0`, `P1`, `P2`, and `P3`. Allowed statuses are
`open`, `resolved`, `accepted`, `deferred`, and `needs-context`.

Use `P0`/`P1` for material blocking defects, not for code-style preferences.
Choose severity by impact and confidence.
