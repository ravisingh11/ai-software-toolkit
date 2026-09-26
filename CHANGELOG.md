# Changelog

All notable changes to AI Software Toolkit are documented here.

The project follows [Semantic Versioning](https://semver.org/). Starting with
1.0, incompatible changes to the documented public runtime, configuration,
or evidence contracts require a major release and migration guidance.

## [Unreleased]

- Add the shared `ai-toolkit` CLI (`tooling/ai_toolkit`) with `discover`,
  `init`, `doctor`, `check`, `providers`, `skills`, `qa`, and `update`. The CLI
  dispatches to the existing installer, diagnostics, scanner, configuration,
  and skill sources; it does not reimplement evaluation, and installed
  repositories never import it at evaluation time. `init` detects Python and
  Node projects, candidate commands, existing workflows and provider
  integrations, and agent clients; previews before writing; installs selected
  components; and records `toolkit.toml` (components, agent clients, paths to
  the authoritative `.guardrails/` files) and `toolkit.lock.json` (revision
  and managed-file hashes). Discovered repository commands are proposed as
  GitHub repository variables and never written to committed files. `doctor`
  adds installed / configured / verified states, where `verified` comes only
  from existing revision-bound evidence. `check` groups results into what ran,
  what failed, what remains unverified, and the next action, naming the repair
  skill for failed capabilities. `update` refreshes unmodified managed files,
  preserves modified ones as reported conflicts, keeps a backup, and supports
  `--rollback`. Add `tooling/build_archive.py` for a checksummed
  `ai-toolkit.pyz`, the `toolkit-setup` skill, the `AI Toolkit Setup` starter
  workflow, and the install guide. The `.guardrails/` runtime contract,
  installer behavior, and existing check identities are unchanged.

- Format the public PR scorecard as a responsive dashboard with clear policy
  status, separate enforced/advisory counts, readable timestamps, and source
  evidence links. Preserve the bounded public metadata, badge URLs, and
  evaluation semantics.

- Group current Guardrails guides under `docs/guardrails/`, delivery standards
  under `docs/standards/`, and historical design plans under `docs/archive/`.
  Add a documentation index and a repository self-check entry point. Update
  documentation links and ground-truth mappings. Remove the unused pre-v2 staged
  attestation script, broken hook template, transient agent reports, and
  superseded unpublished v0.3.0 draft. Supported installer output, `.guardrails/`
  runtime paths, policy modes, and Spec Kit preset identifiers are unchanged.
- Bind repository self-checks to the installed policy rather than shared
  advisory defaults, and isolate diagnostic tests from inherited command
  settings. Verify the Docker-mounted Git repository before accepting Gitleaks
  evidence so an unavailable mount cannot produce a false passing scan.

- Rename the GitHub repository to `ravisingh11/ai-software-toolkit` and update
  clone, release, security reporting, and Pages links. Add a migration guide
  for existing clones, forks, workflows, and badges. Runtime contracts and
  existing release tags are unchanged.

- Introduce AI Software Toolkit as the umbrella identity for shared skills,
  QA workflows, standards, and Guardrails. Add a lifecycle vision and maturity
  map, with DORA measurement marked as aspirational. Preserve the existing
  engineering-standards repository URLs and Guardrails runtime contracts.

- Align CodeQL v4.38.1 and SonarQube scan v8.2.2 action pins across repository,
  reusable, and demo workflows.

- Add the `qa-bootstrap` shared skill: analyzes a product repository, asks only
  what it cannot detect, and generates a `qa` orchestrator, per-app `qa-<app>`
  sub-skills, a report template, and optional GitHub Actions workflows that
  run QA with read-only repository permissions and publish validated results
  from a trusted default-branch reporting workflow. Learned failure modes
  survive regeneration. Missing or blocked
  results fail the advisory check. Functional QA cannot be promoted to enforced
  while its result job is PR-editable; failure learning remains suggestion-only.
  Reports are rendered from validated result rows; rejected artifacts replace
  stale success comments, and superseded runs cannot publish.
- Add the opt-in `functional-qa` capability and `qa-bootstrap-workflow` provider.
  The provider has no shipped template: the consumer-owned `qa.yml` that
  `qa-bootstrap` generates is the producer, and its `QA / report` check is the
  exact-head evidence. It is outside the default profiles and inactive until a
  consumer sets `functional-qa=advisory`, so existing scorecards are unchanged.
- Expand the security and AI development policies with coding-agent trust
  boundaries, scoped tool access, isolation, delegation, memory protection,
  data handling, dependency verification, release evidence, and incident
  response requirements. Add OWASP and GitHub reference guidance and clarify
  disclosure and support limitations. These policy updates do not activate
  runtime controls or change advisory-only AI review enforcement.
- Correct Snyk and FOSSA provider metadata so unavailable workflow templates
  are not advertised, and reject every declared available template that is
  missing from the distribution.
- Isolate setup-diagnostic CLI tests from ambient Guardrails command variables
  so the self-hosted unit-test producer remains deterministic.
- Promote this repository's validated repository, build, unit-test, lint, and
  migration controls to enforced mode after representative passing and failing
  GitHub runs.
- Make Build and Unit Tests fail visibly when their repository command is
  missing so required checks cannot pass through a skipped job.
- Improved coverage run titles and step labels while preserving the
  `Changed Code Coverage` check context. This repository's coverage command
  now publishes a summary with outcomes, measured details, and an explanation
  when no changed lines can be measured; pass/fail behavior is unchanged.

## [1.0.0] - 2026-09-17

First stable release. Includes the work previously planned as v0.3.0;
no v0.3.0 release was published. The Guardrails v2 runtime/evidence schema
version stays at 2. See [release notes](docs/releases/v1.0.0.md).

### Changes since v0.2.0

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

- Added GitHub Sponsors funding configuration (#31).
- Pinned installation examples to v1.0.0 and documented the stable public
  contract, upgrade path, and remaining integration boundaries.

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

[0.1.0]: https://github.com/ravisingh11/ai-software-toolkit/releases/tag/v0.1.0
[0.2.0]: https://github.com/ravisingh11/ai-software-toolkit/releases/tag/v0.2.0
[1.0.0]: https://github.com/ravisingh11/ai-software-toolkit/releases/tag/v1.0.0
[Unreleased]: https://github.com/ravisingh11/ai-software-toolkit/compare/v1.0.0...HEAD
