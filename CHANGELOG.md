# Changelog

All notable changes to Engineering Standards are documented here.

The project follows [Semantic Versioning](https://semver.org/). Until version
1.0, minor releases may refine public configuration and workflow contracts;
migrations will be documented.

## [Unreleased]

Target: v0.3.0. These changes are not part of the published v0.2.0 release.
See the [v0.3.0 release draft](docs/releases/v0.3.0.md).

### Implemented since v0.2.0

- Hardened exact-head GitHub PR evidence collection and matching by provider
  App identity (#19, #21).
- Activated this repository's lint and other guardrail producers and clarified
  check provenance (#16, #20, #22).
- Added guardrail change-workflow skills (#18).
- Added optional aggregate-only scorecard badge publication, reconciliation,
  installer integration, and live README badge links (#24–#26).

- Added read-only `.guardrails/doctor.py` on install/refresh, with
  `--target` (default: current directory), `--json`, and optional
  `--github OWNER/REPO` metadata probes through `gh`, and
  `--operation change|release` (default: change). Exit 1 reports setup gaps,
  including invalid installed configuration; 0 no actionable gaps (possibly
  unverified); and 2 invalid CLI arguments, nonexistent targets, or runtime-helper
  load failures. Setup states are `configured`, `action_needed`, and `unverified`.
  Configuration is not passing evidence; diagnostics do not execute scans or
  repository commands. Optional GitHub probes inspect repository-level variables,
  secret names, and applicable secret-protection settings, not inherited
  organization/environment settings or token validity.
- Improved first-run onboarding with a release-pinned, copyable Python demo,
  explicit clean-HEAD requirements, a labeled illustrative scorecard, and a
  single badge-setup guide.
- Made the Semgrep rule harness scan fixtures outside Semgrep's default
  ignored test directories and reject empty scans or scanner errors.
- Added three real consumer lifecycle tests covering install/configure/scan,
  advisory failure, enforced blocking, repair, missing-command evidence, and
  repeated merge/refresh preservation.

### Release preparation

- Verified fresh consumers and upgrade from v0.2.0, including runtime-only
  diagnostic distribution. See the [release validation record](docs/releases/v0.3.0.md#validation-on-2026-09-17)
  for results and limitations. These notes do not publish a release.

## [0.2.0] - 2026-09-01

Based on tag `v0.2.0` at `5bfb5e7`; the date is the tagged commit date.

- Moved the public runtime configuration from `.ai/` to `.guardrails/` (#5).
- Shipped Guardrails v2 capability/profile/provider policy, nested evidence,
  installer, configurator, scanner, and Python consumer example (#7).
- Distinguished Secret Scan evidence from workflow health and rejected
  operation-inapplicable policy overrides (#6, #8).
- Added trusted PR change-scope evaluation and complete-history collection
  (#9, #11).
- Added extensible Core controls: documentation and ground-truth validation,
  PR metadata, format/lint, and migration validation; hardened metadata and
  missing-producer behavior (#15).
- Refreshed README, lifecycle, and setup guidance (#1–#4, #10).

## [0.1.0] - 2026-08-27

Initial public release.

- Added organization-ready engineering, testing, security, pull-request, and
  AI-development policies.
- Added the Guardrails evaluator, evidence schema, local scanner, scorecard,
  installer, and provider configuration.
- Added reusable GitHub Actions workflows and default-branch ruleset templates.
- Added engineering, QA, security, and repository-standards AI review guidance.
- Added reusable engineering skills and an embedded Python consumer example.

[0.1.0]: https://github.com/ravisingh11/engineering-standards/releases/tag/v0.1.0
[0.2.0]: https://github.com/ravisingh11/engineering-standards/releases/tag/v0.2.0
[Unreleased]: https://github.com/ravisingh11/engineering-standards/compare/v0.2.0...HEAD
