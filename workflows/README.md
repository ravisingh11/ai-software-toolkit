# Guardrails v2 workflows

The installer deploys independent producer workflows and an aggregate
scorecard. A workflow file is configuration; only exact-subject provider
evidence can pass a capability.

## Install sets

```sh
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo --profile github
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo --scorecard-badge
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo --no-actions
```

The default installs Core runtime and Core workflows. `--profile github` adds
the GitHub overlay. `--scorecard-badge` adds the optional Pages publisher.
`--no-actions` installs no workflows and cannot be combined with badge
publishing.

### Core workflows

| Installed file | Workflow / check names | Activation |
| --- | --- | --- |
| `guardrails-scorecard.yml` | `Guardrail Scorecard` | Always for supported PR events and manual dispatch |
| `repository-validation.yml` | `Validate / repository`, `Validate / docs`, `Validate / ground truth` | Installed validators and repository configuration |
| `change-scope.yml` | `PR Change Scope` | Trusted exact-revision PR size evidence; neutral while advisory, failing when enforced |
| `pr-metadata.yml` | `PR Metadata` | Trusted mutable PR title/body evidence plus a run-bound custom check on the exact candidate head SHA |
| `format-and-lint.yml` | `Format and Lint` | `GUARDRAILS_FORMAT_LINT_COMMAND`; the job fails visibly when unset |
| `migration-validation.yml` | `Migration Validation` | `GUARDRAILS_MIGRATION_VALIDATION_COMMAND`; the job fails visibly when unset |
| `build.yml` | `Build` | `GUARDRAILS_BUILD_COMMAND` |
| `unit-tests.yml` | `Unit Tests` | `GUARDRAILS_UNIT_TEST_COMMAND` |
| `changed-code-coverage.yml` | `Changed Code Coverage` | `GUARDRAILS_CHANGED_COVERAGE_COMMAND` |
| `semgrep-ce.yml` | `Semgrep CE` | Installed tested rules; no secret |
| `gitleaks.yml` | `Gitleaks` | Full Git history; no secret |

Repository command workflows use optional
`GUARDRAILS_SETUP_COMMAND` and default `GUARDRAILS_WORKING_DIRECTORY` to `.`.
Build, test, and coverage jobs remain inactive until configured. Format/lint and
migration validation always create their named job; an absent command fails the
job so a promoted required context cannot be satisfied by a skipped producer.
Local scans continue to represent absent commands as `NO RESULT`.

Coverage runs use a readable title such as `Coverage check · PR #32`; the
check context stays `Changed Code Coverage` so provider contracts and rulesets
keep matching. A custom coverage command can write its measured results to
`GITHUB_STEP_SUMMARY` to show them on the Actions Summary page. This repository's
`tooling/changed_code_coverage.sh` does that, including failed comparisons and
diffs without measured lines. A successful docs-only run is not a claim of
100% coverage. Changing a workflow updates future runs, not historical titles.

Semgrep CE runs its repository-owned rule tests, then `semgrep scan --error`
from the exact pinned container with networking disabled. Gitleaks runs the MIT
CLI from its exact pinned container against complete Git history. Core does not
use a platform token for Semgrep or the separately licensed Gitleaks Action.

### GitHub profile workflows

| Installed file | Workflow / check | Activation |
| --- | --- | --- |
| `codeql.yml` | `CodeQL` | `GUARDRAILS_CODEQL_LANGUAGES` |
| `dependency-review.yml` | `Dependency Review` | `GUARDRAILS_DEPENDENCY_REVIEW_ENABLED=true` |
| `github-secret-protection.yml` | `Secret Scan` / published `GitHub Secret Scan` | Optional `SECURITY_SETTINGS_TOKEN` and enabled platform settings |
| `dependabot-verification.yml` | `Dependabot Verification` | Optional `SECURITY_SETTINGS_TOKEN` and enabled platform settings |
| `artifact-provenance.yml` | `Artifact Provenance` | Release/dispatch attestation only; not PR or scorecard evidence |

### Optional reporting workflow

| Installed file | Workflow | Activation |
| --- | --- | --- |
| `guardrails-scorecard-badge.yml` | `Guardrail Scorecard Badge` | GitHub Pages uses GitHub Actions; `GUARDRAILS_SCORECARD_BADGE_ENABLED=true`; `GUARDRAILS_SCORECARD_BADGE_PAGES_MODE=dedicated` |

This workflow is not a provider, capability, or required check. It owns the
complete Pages deployment in `dedicated` mode; integrate the renderer into an
existing site workflow instead when the repository already uses Pages.

The settings probes use trusted, no-checkout `pull_request_target` workflows.
Give `SECURITY_SETTINGS_TOKEN` only repository Administration read and Secret
scanning alerts read access. Missing or insufficient access publishes skipped
exact-head checks; it never passes the capability.

The release attestation workflow requires an artifact supplied by dispatch
input or `GUARDRAILS_ARTIFACT_PATH`. `GUARDRAILS_ARTIFACT_BUILD_COMMAND` is
optional. The workflow does not emit the nested artifact evidence contract or
invoke a release scorecard, so it is not yet a fully runnable Guardrails
artifact-provenance path.

## Scorecard flow

```text
provider workflows in parallel
        -> selected check contracts
        -> exact-head and workflow-run provenance verification
        -> nested provider evidence
        -> deterministic scorecard
        -. optional trusted reconciliation .-> bounded Pages badge/report
```

`guardrails-scorecard.yml` runs as trusted `pull_request_target` code. It checks
out executable runtime only from the exact base SHA, sparse-checks out the exact
PR-head policy/configuration as fixed-path non-symlink data, and never executes
candidate code with the GitHub token. It waits up to 1,800 seconds, writes paired
timestamped scorecard JSON and Markdown plus timestamped evidence, appends the
Markdown to the job summary, and uploads `.artifacts/guardrails` as
`guardrail-scorecard-<run-id>`.

The native **Scorecard Workflow** badge reports whether this workflow ran. The
optional **Latest PR Scorecard** badge reports readiness and passed/active count
from the newest accepted PR artifact. A successful workflow may publish
`ORANGE / ALLOW`; the latest PR badge does not attest current `main`. The Pages
projection includes only aggregate status/counts, source-run metadata, and a
revision digest. Controls, findings, evidence, reasons, provider data, check
URLs, raw revisions, and source Markdown are excluded from Pages and remain in
the source Actions artifact under normal repository access.

The collector requires the exact check name/head/app, workflow run name/path,
pull-request event, and exact PR-head association. Native Actions checks retain
workflow-suite binding. Custom setting checks instead require their configured
external-ID prefix and details run ID; their PR-head check suite is not equated
with the `pull_request_target` workflow's base-SHA suite. Missing, skipped,
stale, ambiguous, or unverifiable checks become `NO RESULT`. Same-name checks
from a different GitHub App are ignored; multiple matches from the declared app
remain ambiguous and do not satisfy the control.

## Local versus PR operation

Local scans run the same Core provider contracts against a clean local `HEAD`.
They are fast feedback, not merge authority. Pull-request workflows run in the
repository's controlled Actions environment and provide the evidence consumed
by branch protection.

Do not treat scorecard job success as a pass for every capability. Inspect the
overall `GREEN`, `ORANGE`, or `RED` status and every capability/provider row.

## Optional providers

SonarQube, Snyk, Semgrep AppSec Platform, FOSSA, Codex Code Review, AI review adapters, and soak
testing are not installed as runnable profiles. A repository must supply a
workflow or adapter, required credentials/configuration, exact check/evidence
binding, and an explicit provider selection. A credential alone does not
activate or satisfy a capability.

Codex Code Review is a native GitHub review provider rather than a check-run
workflow. The collector requires the configured bot login and exact reviewed
head SHA. Enable native automatic review in Codex settings; do not create a
workflow that posts synthetic `@codex` comments. AI review controls are
advisory-only and must never be the sole required merge context.

Provider definitions declare these secret names where applicable:

```text
SONAR_TOKEN
SNYK_TOKEN
SEMGREP_APP_TOKEN
FOSSA_API_KEY
```

Keep optional integrations advisory until representative pull requests prove
their availability, exact-subject binding, stable check names, and failure
behavior.

## Required checks

Require only exact observed check names. Core examples are `Validate / repository`,
`Validate / docs`, `Validate / ground truth`, `PR Change Scope`, `Build`,
`PR Metadata`, `Format and Lint`, `Migration Validation`, `Unit Tests`,
`Changed Code Coverage`, `Semgrep CE`, and `Gitleaks`. GitHub
profile examples are `CodeQL`, `Dependency Review`, `GitHub Secret Scan`,
and `Dependabot Verification`. `Artifact Provenance` is release-only and must
not be configured as a pull-request required check.

For PR metadata, require the custom exact-head `PR Metadata` context published
by the workflow. The workflow job itself runs in the trusted base-SHA check
suite and is not the merge context. Workflow-level concurrency is scoped to the
pull-request number, and a newer event cancels any older in-progress metadata
run. The evidence upload outcome is part of the custom-check decision; upload
failure always publishes a failing exact-head check rather than success without
proof.

For `Format and Lint` and `Migration Validation`, configure the repository
command first and verify both success and failure behavior. The job remains
present and fails when its command is absent; this is deliberate protection
against a required context being satisfied by GitHub's skipped-job behavior.

See [ruleset guidance](../rulesets/README.md) before adding contexts.
