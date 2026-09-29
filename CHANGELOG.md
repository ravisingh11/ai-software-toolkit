# Changelog

All notable changes to AI Software Toolkit are documented here.

The project follows [Semantic Versioning](https://semver.org/). Starting with
1.0, incompatible changes to the documented public runtime, configuration,
or evidence contracts require a major release and migration guidance.

## [Unreleased]

- Show repository validator counts on the scorecard dashboard. The Validate
  workflow's repository, docs, and ground-truth jobs now record self-reported
  measurements: contract groups passed, failed, and not run; Markdown files,
  local links checked, broken links, and documentation mapping failures; and
  ground-truth documents declared, found, and missing. The evidence schema
  gains the `contracts`, `documentation`, and `documents` measurement kinds,
  each limited to its control and checked for arithmetic and status
  consistency. The installed repository validator now runs named contract
  groups in order. The dashboard's assessment text now states that ground
  truth checks only that each declared document exists. Refresh the runtime,
  `providers.yaml`, and `repository-validation.yml` together.

- Score PR Metadata on the scorecard dashboard. `Proof Scorecard` now also
  runs when a pull request is edited, runs the trusted base PR metadata
  validator on the current title and body, and passes the result to
  `.proof/scorecard.py` with the new `--pull-request-revision` and
  `--pull-request-evidence` options. The evaluator's new `companions`
  argument scores that `pull-request` subject beside the commit, and it
  counts toward the same totals. A missing result reports **Unverified**. The scorecard JSON gains an optional
  `companion_subjects` list. A control that policy activates on a subject the
  evaluation did not score keeps `not_activated`, but adds `inactive_reason:
  other_subject` and `evidence_subject`; the dashboard labels it
  **Checked on the PR** instead of **Not activated**. This repository's
  `.proof/pr-metadata.yaml` now requires Conventional Commit titles and a
  `## Verification` body section; the installed consumer default is unchanged.
  Refresh the runtime and `proof-scorecard.yml` together; the workflow skips
  PR metadata scoring when the trusted runtime lacks the new options.

- Explain how the scorecard totals relate to the check table. A sentence under
  the totals states how many active checks they count and how many of the
  listed built-in checks are active, not activated, or not reported, so
  "13/14" no longer looks inconsistent with 33 listed checks.

- Show self-reported test totals and changed-line coverage on the scorecard
  dashboard. The `Unit Tests` and `Changed Code Coverage` workflow templates
  set `PROOF_MEASUREMENTS_FILE`, package a file the configured command writes
  with the new `.proof/measurements.py` helper (unittest logs, JUnit XML, or
  diff-cover JSON), and upload a non-fatal, attempt-bound
  `proof-measurements-<run_id>-<run_attempt>` artifact. Evidence results gain an optional, display-only `measurements`
  field accepted only on `unit-tests` and `changed-code-coverage`; provider
  checks gain optional `measurements_artifact_prefix` and
  `measurements_member`. The collector attaches measurements only when the
  run, repository, head SHA, and control bind and the numbers agree with the
  check status; otherwise they are omitted. `tooling/test.sh` now runs every
  suite before returning a failure, so failed runs also record totals. Because the numbers come from the
  pull request's own code, the dashboard labels them as not independently
  verified, and they never change a result. Refresh the runtime, schemas,
  provider config, and both workflows together; older evaluators reject the
  new fields. Commands that do not write the file are unaffected.

- Make the public PR scorecard page easier to scan. A **Needs attention** list
  above the totals names failed, blocked, and unverified checks, most severe
  first. Detail sections put those checks first, show execution time as a
  readable duration, fold assessment criteria behind a disclosure, and group
  not-activated and not-reported checks in a compact section, roughly halving
  page length. On narrow screens the checks table keeps each result beside its
  check name. When no controls are enforced, the status panel says the ALLOW
  decision is not gated by any control and marks it **Advisory only**; a BLOCK
  decision no longer shows the ALLOW explanation. Published metadata,
  evaluation semantics, and badge output are unchanged.

- Run the Snyk and FOSSA adapter from the trusted base revision. The
  `workflows/snyk.yml` and `workflows/fossa.yml` templates check out
  `.proof/adapter.py` from the pull request's base SHA into `trusted/`
  (sparse, non-symlink) and run it against the head checkout in `candidate/`,
  so a pull request cannot change the code that receives `SNYK_TOKEN` or
  `FOSSA_API_KEY`. The `snyk-code`, `snyk-open-source`, and `fossa` contracts
  list the adapter as a trusted path, so the scorecard records `not_run` for a
  pull request whose adapter differs from the base. The trusted checkout is
  the last step before the adapter runs, and the adapter step uses a reset
  environment with the interpreter and `PATH` recorded before the setup
  command, so candidate setup cannot replace the adapter or poison its
  environment. Check names, evidence fragments, and reason codes are
  unchanged.

- **Breaking:** rename the Guardrails component to Proof as a hard cutover.
  The installed runtime moves from `.guardrails/` to `.proof/`, repository
  variables from `GUARDRAILS_*` to `PROOF_*`, the `Guardrail Scorecard` check
  and workflows to `Proof Scorecard` / `proof-scorecard*.yml`, the Pages badge
  to `proof-badge.svg`, artifact and external-ID prefixes to `proof-` /
  `proof:`, and the `toolkit.toml` component and table to `proof`. Nothing
  reads the old names. The installer refuses a Guardrails layout before
  writing and prints the exact `git mv`/`git rm`/refresh commands for that
  installation; the CLI rejects a Guardrails `toolkit.toml`. Evaluation
  semantics, control IDs, evidence schemas, policy modes, and other check
  names are unchanged. The next release must be a major version. See
  [migrating from Guardrails](docs/proof/migrating-from-guardrails.md).

- Fix three `ai-toolkit` review follow-ups: re-running `init` for another
  component no longer installs the default skill set over a narrower
  selection; a project `skills install` (or `qa bootstrap`) adds its component
  to `toolkit.toml` and the lock so the next `update` keeps the files; and
  `update` validates both record destinations before mutating managed files
  and restores files, configuration, and lock together when a record write
  fails.

- Expand the public scorecard with a compact table linking to check-specific
  assessment details, validated optional check execution timings, and explicit
  measurement gaps. Every check shows its canonical catalog ID next to its
  name, and the scorecard workflow evaluates with `--all-catalog-controls`
  so a control the policy explicitly leaves `not_activated` is published as
  **Not activated** instead of **Not reported**. Keep all active controls
  advisory in this repository's Proof policy; GitHub required-check rules
  remain separate.

- Harden action-skill verification: reject stale or duplicate client ledger
  claims, package review contracts, and keep seeded scans self-contained.
  QA publishes sanitized non-passing reasons while remaining unsuccessful,
  restricts agent-authored provenance, and rejects PR-supplied commands.

- Brand the public PR scorecard page as AI Software Toolkit instead of
  Guardrails, matching the toolkit identity. Page content, badge URLs, bounded
  metadata, and evaluation semantics are unchanged.
- Default installation guidance to Actions scorecard summaries and artifacts,
  with read-only detection of the target repository's visibility. Keep Pages
  publication opt-in. Block publication when live visibility is unknown or a
  private/internal repository lacks an explicitly configured and verified
  private Pages destination (`GUARDRAILS_SCORECARD_BADGE_PAGES_ACCESS=private`).
  Existing nonpublic publishers must configure private Pages and this variable
  before their next publication; normal CI scorecards remain available.
  Private publishing selects retained CI evidence without fetching the previous
  authenticated report. Previously deployed public reports are not removed.

- Make PR size reporting explicit with the `PR Size / Files & LOC` workflow,
  measured-versus-limit tables, and counted/excluded totals. Preserve the
  `PR Change Scope` check identity and existing advisory/enforced behavior.
  Carry optional validated aggregate measurements into the public scorecard
  dashboard; older evidence without measurements displays unavailable.
- Reorganize documentation around six entry points (Install, Guardrails,
  Skills, QA, Providers, Reference app), add the reference-app page, and
  rewrite the maturity matrix with shipped / opt-in / planned labels checked
  against the source tree. The source repository validator now fails when a
  shipped workflow template, skill, provider, or tooling script is not
  mentioned in published documentation; the audit it enabled documented the
  `ai-pr-review.yml`, `security-scanning.yml`, and `soak.yml` templates, the
  AI review adapters and soak provider, the `prepare-safe-change` skill, and
  the release asset scripts, and corrected the architecture guide's account of
  vendor providers.

- Implement the five action skills `fix-ci`, `generate-unit-tests`,
  `fix-security-finding`, `dependency-upgrade`, and `address-pr-findings`,
  replacing their placeholders. Each defines inputs, permitted changes, stop
  conditions, verification, and an outcome report; reuses the canonical review
  skills; ships a seeded fixture; and keeps a per-client `VERIFICATION.md`
  ledger that `tooling/validate-skills.py` now requires. No action skill is
  labelled verified until a live run in Codex and Claude Code is recorded.
  `tooling/install-skills.sh` gains `--client codex|claude-code`.
- QA: `qa-bootstrap` documents version-controlled test plans
  (`plans/<app>.yaml`), findings with regression links (`findings/<id>.md`),
  and rerun reporting; result rows may carry `origin`, `scenario`, and
  `finding`, rendered in the trusted report. FLAKY now maps to `blocked`
  (`analysis-incomplete`) instead of passing, so a pass on retry can never
  satisfy the advisory `QA / report` check; non-passing reports state the
  overall status and reason. Functional QA remains advisory-only.

- Ship adapter-owned Snyk and FOSSA workflow templates (`workflows/snyk.yml`,
  `workflows/fossa.yml`) and install `.guardrails/adapter.py`, which runs
  `snyk code test`, `snyk test`, and `fossa analyze` followed by `fossa test`
  for the exact revision, maps exit codes and output to the four evidence
  statuses, and writes nested v2 evidence fragments that `scan.py` merges.
  Consumers supply arguments (`SNYK_CODE_ARGS`, `SNYK_OPEN_SOURCE_ARGS`,
  `FOSSA_ARGS`), never the verb, so an upload alone cannot pass, and any
  argument whose path resolves outside the checkout is rejected as
  `revision-mismatch` before the provider runs. Non-passing
  results carry a standard reason code as the prefix of `reason`
  (`configuration-missing`, `credential-missing`, `authentication-failed`,
  `execution-error`, `analysis-incomplete`, `revision-mismatch`,
  `unsupported-project`, `timed-out`); the evidence schema is unchanged. The
  FOSSA CLI is pinned by version and SHA-256. `doctor` adds adapter, local
  credential, and template rows for selected external providers; `ai-toolkit
  check` turns reason codes into next actions. Add provider guides, a reason
  code reference, contract tests for every outcome, and a live verification
  ledger; no adapter is labelled verified until a live run is recorded there.
  Existing `snyk-code`, `snyk-open-source`, and `fossa` check identities are
  unchanged.

- Ship adapter-owned Snyk and FOSSA workflow templates (`workflows/snyk.yml`,
  `workflows/fossa.yml`) and install `.guardrails/adapter.py`, which runs
  `snyk code test`, `snyk test`, and `fossa analyze` followed by `fossa test`
  for the exact revision, maps exit codes and output to the four evidence
  statuses, and writes nested v2 evidence fragments that `scan.py` merges.
  Consumers supply arguments (`SNYK_CODE_ARGS`, `SNYK_OPEN_SOURCE_ARGS`,
  `FOSSA_ARGS`), never the verb, so an upload alone cannot pass, and any
  argument whose path resolves outside the checkout is rejected as
  `revision-mismatch` before the provider runs. Non-passing
  results carry a standard reason code as the prefix of `reason`
  (`configuration-missing`, `credential-missing`, `authentication-failed`,
  `execution-error`, `analysis-incomplete`, `revision-mismatch`,
  `unsupported-project`, `timed-out`); the evidence schema is unchanged. The
  FOSSA CLI is pinned by version and SHA-256. `doctor` adds adapter, local
  credential, and template rows for selected external providers; `ai-toolkit
  check` turns reason codes into next actions. Add provider guides, a reason
  code reference, contract tests for every outcome, and a live verification
  ledger; no adapter is labelled verified until a live run is recorded there.
  Existing `snyk-code`, `snyk-open-source`, and `fossa` check identities are
  unchanged.

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
