# Guardrails v2 implementation plan

## Goal

Deliver a clean-break v2 that evaluates vendor-neutral engineering capabilities
while showing the actual provider that produced every result. A fresh install
selects a portable Core profile in advisory mode; a GitHub profile is optional.

## Global constraints

- Never report configuration, a workflow file, a skipped job, stale evidence,
  or a missing provider as a pass.
- Bind evidence to the exact commit, artifact, or environment under evaluation.
- Permit exactly one authoritative provider per capability. Supplemental
  providers are visible and advisory but cannot satisfy or block the capability.
- Keep Core and GitHub as the only runnable v2 profiles. Other lifecycle areas
  are catalog/evidence contracts only.
- Keep every profile advisory by default; enforcement is an explicit repository
  override.
- Use tokenless Semgrep CE with tested local rules and the Gitleaks CLI, not the
  separately licensed Gitleaks Action.
- Do not automatically rewrite v1 consumer configuration.

## Task 1: v2 contracts

Define v2 control, profile, provider, policy, and nested evidence schemas.
Add Core and GitHub profile definitions, provider mappings, and future
evidence-only capabilities. Add validator and schema tests first.

## Task 2: runtime

Update evaluator, scorecard, scanner, GitHub check collector, and configuration
CLI for profile defaults, operation overrides, authoritative provider selection,
supplemental evidence, and exact-subject validation. Remove producer-manifest
synchronization. Add behavior tests first.

## Task 3: installation and producers

Make a normal install deploy the Core runtime and workflows. Add an optional
GitHub profile, `--no-actions`, and safe `--local-hooks`. Implement tokenless
Semgrep CE and Gitleaks CLI producers with immutable execution references.
Repository build, test, and changed-code coverage commands must report NO RESULT
when unconfigured. Add installation and workflow tests first.

## Task 4: documentation and examples

Update architecture, quickstart, setup, status, licensing, ruleset guidance,
examples, and the demo to describe capability/provider separation and the two
runnable profiles. Remove active v1 and producer-manifest guidance.

## Task 5: verification and release readiness

Run all unit, validator, demo, skill, documentation, JSON/YAML, link, and diff
checks. Scan this repository and the demo. Perform a whole-branch code review,
resolve material findings, and prepare three reviewable commits that can be
published as the approved contract/runtime, producer/installer, and
documentation/demo pull-request slices without merging them.
