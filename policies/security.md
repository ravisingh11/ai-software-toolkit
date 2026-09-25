# Security Policy

## Status

This is an initial, evolving standard. The shared baseline reports these
controls as advisory so teams can adopt them without stopping delivery. Move a
control to enforced only after it meets the promotion rule in
[the guardrails standard](../docs/guardrails/README.md#promotion-rule).

## Security expectations

- SAST is expected on every PR and starts in advisory mode.
- Secret scanning is expected. GitHub secret scanning and push protection are
  platform configuration; workflows must not claim to enable them. Keep the
  control advisory while the platform capability and producer evidence are
  verified.
- Dependency vulnerability scanning and dependency review are expected. Keep
  them advisory while their producers and policies are verified.
- Snyk is an approved and recommended external provider for dependency and/or
  source-code scanning. Snyk starts in advisory mode so repositories can adopt
  it and learn from its findings before enforcing it. A repository must define
  which Snyk product is authoritative for each finding class and must not
  create duplicate blocking gates without a documented defense-in-depth
  decision.
- FOSSA or an equivalent open-source governance producer is expected when the
  repository adopts that integration; it covers dependency, license, and
  supply-chain policy rather than replacing SAST.
- Critical/high-risk dependency introduction should be blocked according to
  the organization's approved severity and exception policy.
- Authentication and authorization changes require elevated scrutiny.
- Tenant isolation must be preserved wherever tenant-scoped data exists.
- Sensitive data, credentials, authentication tokens, and unnecessary PII
  must not be logged.
- Security controls must not be bypassed to make tests, builds, or releases
  pass.
- High-risk code may require human, domain-owner, or security approval.

## Organization-specific guardrails

For coding agents, model context, prompt injection, tool permissions, and
generated dependencies, apply the [AI development policy](ai-development.md)
alongside this standard. The repository's [security policy](../SECURITY.md)
defines its trust boundaries and private reporting process.

These are candidate rules for Semgrep or equivalent enforcement. They are
intentionally documented in [security/semgrep/README.md](../security/semgrep/README.md)
rather than represented by unreliable pattern-only rules.

- Never access tenant data without `tenantId` where SaaS tenant isolation
  applies.
- Never construct SQL from user-controlled strings.
- Never log authentication tokens.
- Never disable TLS validation.
- Never introduce unauthenticated administrative endpoints.

Repeated security review findings should become automated rules whenever
practical. A rule must be validated against representative code before it is
made blocking.
