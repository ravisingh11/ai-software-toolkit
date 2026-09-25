# Release Evidence Standard

Use this standard for production-facing repositories. Each production release
must leave enough evidence for another operator to understand what shipped,
where it shipped, how it was verified, and how to recover if the release fails.

Keep the record lightweight. The goal is a durable release note for operators,
not a heavyweight approval process. Pull requests, GitHub Actions, and any
specific cloud provider are optional.

## When To Record Evidence

Record release evidence after any change that reaches a production or
customer-facing environment, including:

- web, API, admin, mobile app, worker, scheduled job, or infrastructure deploys
- configuration-only changes that affect production behavior
- database migrations, backfills, cache changes, or third-party integration
  updates
- mobile store, beta, or staged rollout submissions

For small static content updates, a concise GitHub issue comment is acceptable.
For multi-surface or risky releases, prefer a dated file such as:

```text
docs/releases/YYYY-MM-DD-<release>.md
```

## Required Evidence

Every production release evidence record must include the following sections.

### 1. Release Identifier

- commit SHA
- tag or version, if present
- source branch
- release date and timezone
- operator or automation that performed the release, if useful

### 2. Released Surfaces

List every deployable surface included in the release, such as:

- web
- API
- admin
- mobile app
- worker or scheduled job
- infrastructure
- configuration
- database migration or backfill

If a related surface was intentionally not released, say so.

### 3. Deployment Target

Record where the release landed:

- environment, such as production, staging, beta, or external test
- service, platform, app store, or hosting target
- region, cluster, project, account, or tenant scope when relevant
- public or internal URL only when it is safe to document
- deployment revision, build number, release id, or artifact id when available

Do not record credentials, secret names that would expose sensitive topology, or
private customer data.

### 4. Verification Evidence

Record exact evidence, not just "tested":

- commands run
- release gate, build, lint, typecheck, unit, integration, contract, smoke, or
  audit commands
- health endpoints checked
- manual checks completed
- mobile store or beta rollout checks completed
- screenshots, logs, links, or issue references when useful and safe

If a check was not run, list it under known gaps instead of implying coverage.

### 5. Configuration Evidence

Record the configuration validation performed without exposing secrets:

- environment or config validation command
- required production variables or config groups checked by name or category
  when safe
- migration, feature flag, cache, storage, queue, webhook, or third-party
  integration checks
- confirmation that no secret values were printed or committed

Never paste secret values, tokens, credentials, private logs, customer payloads,
or unnecessary PII into release evidence.

### 6. Rollback Path

Document the exact recovery path:

- rollback command, redeploy command, store rollout action, or restore procedure
- previous known-good revision, tag, artifact, or build if available
- database or migration rollback posture
- cache, queue, or feature-flag recovery steps

If rollback is not available, document why and identify the safest mitigation.

### 7. Known Gaps

List any incomplete or accepted risk:

- skipped checks
- blocked verification
- unavailable credentials or tooling
- environment limitations
- manual checks still required
- follow-up issue links
- accepted risk and owner

Known gaps should be specific enough for another operator to continue the work.

### 8. Operator Notes

Capture production-specific caveats:

- migrations or backfills
- cache invalidation
- DNS or CDN propagation
- queue draining or replay behavior
- monitoring or alert checks
- expected transient errors
- support or customer-facing considerations

## Storage Guidance

Choose one durable location per repository:

- `docs/releases/YYYY-MM-DD-<release>.md` for file-based release history
- a GitHub issue comment when the issue is the operational source of truth
- a release checklist document under `docs/reviews/` for broader launch reviews

The location must be discoverable from the repository runbook or `AGENTS.md`.

## Review Checklist

- [ ] Release identifier includes commit SHA, branch, date, and version/tag if
      present.
- [ ] Released surfaces and intentionally excluded related surfaces are clear.
- [ ] Deployment target and revision/build/artifact evidence are recorded.
- [ ] Verification commands and manual checks are explicit.
- [ ] Configuration validation is recorded without secrets.
- [ ] Rollback or mitigation path is documented.
- [ ] Known gaps and follow-up issues are listed.
- [ ] Operator notes capture migrations, caches, monitoring, or caveats.
