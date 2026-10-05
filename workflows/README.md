# Proof workflows

These workflows provide Proof evidence within [AI Software Toolkit](../docs/vision.md).
For consumer-specific functional QA workflows, start with
[QA bootstrap](../skills/qa-bootstrap/SKILL.md).

The installer deploys independent producer workflows and an aggregate
scorecard. A workflow file is configuration; only exact-subject provider
evidence can pass a capability.

AI review consolidation uses pinned `actions/download-artifact` v8.0.1.
Self-hosted runners need version 2.327.1 or later for its Node 24 runtime.
The existing artifact pattern, destination, and merged download layout remain
supported. Digest mismatches fail the download; retain that integrity check
when upgrading. Reviewer uploads use the upload action's default archived
format. A successful live AI consolidation run is still required to verify
the provider integration.

SonarQube analysis uses pinned `SonarSource/sonarqube-scan-action` v8.3.0,
which fixes GPG key retrieval through HTTPS proxies and updates its bundled
`actions/cache` to v5.1.0. Inputs and `SONAR_TOKEN` handling are unchanged.
A successful live SonarQube run is still required to verify the provider
integration.

## Install sets

```sh
python3 /path/to/ai-software-toolkit/tooling/install.py --target /path/to/repo
python3 /path/to/ai-software-toolkit/tooling/install.py --target /path/to/repo --profile github
python3 /path/to/ai-software-toolkit/tooling/install.py --target /path/to/repo --scorecard-badge
python3 /path/to/ai-software-toolkit/tooling/install.py --target /path/to/repo --no-actions
```

The default installs Core runtime and Core workflows. `--profile github` adds
the GitHub overlay. `--scorecard-badge` adds the optional Pages publisher.
`--no-actions` installs no workflows and cannot be combined with badge
publishing.

### Core workflows

| Installed file | Workflow / check names | Activation |
| --- | --- | --- |
| `proof-scorecard.yml` | `Proof Scorecard` | Always for supported PR events and manual dispatch |
| `repository-validation.yml` | `Validate / repository`, `Validate / docs`, `Validate / ground truth` | Installed validators and repository configuration |
| `change-scope.yml` | `PR Change Scope` | **PR Size / Files & LOC** workflow: measured/limit tables, counted/excluded totals; neutral while advisory, failing when enforced |
| `pr-metadata.yml` | `PR Metadata` | Trusted mutable PR title/body evidence plus a run-bound custom check on the exact candidate head SHA |
| `format-and-lint.yml` | `Format and Lint` | `PROOF_FORMAT_LINT_COMMAND`; the job fails visibly when unset |
| `migration-validation.yml` | `Migration Validation` | `PROOF_MIGRATION_VALIDATION_COMMAND`; the job fails visibly when unset |
| `build.yml` | `Build` | `PROOF_BUILD_COMMAND`; the job fails visibly when unset |
| `unit-tests.yml` | `Unit Tests` | `PROOF_UNIT_TEST_COMMAND`; the job fails visibly when unset |
| `changed-code-coverage.yml` | `Changed Code Coverage` | `PROOF_CHANGED_COVERAGE_COMMAND` |
| `semgrep-ce.yml` | `Semgrep CE` | Installed tested rules; no secret |
| `gitleaks.yml` | `Gitleaks` | Full Git history; no secret |

Repository command workflows use optional `PROOF_SETUP_COMMAND` and
default `PROOF_WORKING_DIRECTORY` to `.`. Build, unit tests, format/lint,
and migration validation always create their named job; an absent command
fails the job so a promoted required context cannot be satisfied by a skipped
producer. Changed-code coverage remains inactive until configured and
advisory. Local scans continue to represent absent commands as `NO RESULT`.

Coverage runs use a readable title such as `Coverage check · PR #32`; the
check context stays `Changed Code Coverage` so provider contracts and rulesets
keep matching. A custom coverage command can write its measured results to
`GITHUB_STEP_SUMMARY` to show them on the Actions Summary page. This repository's
`tooling/changed_code_coverage.sh` does that, including failed comparisons and
diffs without measured lines. A successful docs-only run is not a claim of
100% coverage. Changing a workflow updates future runs, not historical titles.

The Unit Tests and Changed Code Coverage workflows set `PROOF_MEASUREMENTS_FILE`.
A command that writes it (for example with `.proof/measurements.py unittest`,
`junit`, or `diff-cover`) gets its test totals or changed-line coverage
packaged and uploaded as the `proof-measurements-<run_id>-<run_attempt>`
artifact. The Validate workflow's repository, docs, and ground-truth jobs do the
same with their own validator counts, uploaded as
`proof-measurements-repository-`, `proof-measurements-docs-`, and
`proof-measurements-ground-truth-` artifacts for that run and attempt. The
Migration Validation workflow also sets `PROOF_MEASUREMENTS_FILE`; a migration
command that writes `{"version": 1, "source": "pull-request-workflow",
"migrations": {"checked": N, "failed": M}}` gets those counts shown. Each job of the `ai-pr-review.yml` template counts
its reviewer's result file with the default branch's `.proof/measurements.py review-findings`
(findings by severity and unresolved `P0`/`P1`) and puts the counts in its
run-bound `proof-<provider>-<run_id>` evidence artifact. The Semgrep CE and Gitleaks workflows count their own JSON reports with
`.proof/measurements.py semgrep` or `gitleaks` and upload only the finding
counts (`findings`: total, critical, high, medium, low, unrated). The CodeQL
workflow counts its SARIF output with `.proof/measurements.py sarif` and
uploads `proof-measurements-codeql-`. The Snyk
workflow's trusted adapter writes the same counts for Snyk Code and Snyk Open
Source into its run-bound evidence artifact. The scorecard dashboard shows these as self-reported, because the
numbers describe the pull request's own code or come from its own commands; they never change a check's
result. Packaging and upload failures only warn, and commands that do not
write the file are unaffected.

Semgrep CE runs its repository-owned rule tests, then `semgrep scan --error`
from the exact pinned container with networking disabled. Gitleaks runs the MIT
CLI from its exact pinned container against complete Git history. Core does not
use a platform token for Semgrep or the separately licensed Gitleaks Action.

### GitHub profile workflows

| Installed file | Workflow / check | Activation |
| --- | --- | --- |
| `codeql.yml` | `CodeQL` | `PROOF_CODEQL_LANGUAGES` |
| `dependency-review.yml` | `Dependency Review` | `PROOF_DEPENDENCY_REVIEW_ENABLED=true` |
| `github-secret-protection.yml` | `Secret Scan` / published `GitHub Secret Scan` | Optional `SECURITY_SETTINGS_TOKEN` and enabled platform settings |
| `dependabot-verification.yml` | `Dependabot Verification` | Optional `SECURITY_SETTINGS_TOKEN` and enabled platform settings |
| `artifact-provenance.yml` | `Artifact Provenance` | Release/dispatch attestation only; not PR or scorecard evidence |

### Optional reporting workflow

| Installed file | Workflow | Activation |
| --- | --- | --- |
| `proof-scorecard-badge.yml` | `Proof Scorecard Badge` | GitHub Pages uses GitHub Actions; `PROOF_SCORECARD_BADGE_ENABLED=true`; `PROOF_SCORECARD_BADGE_PAGES_MODE=dedicated`; private or internal repositories also set `PROOF_SCORECARD_BADGE_PAGES_ACCESS=private` |

This workflow is not a provider, capability, or required check. It owns the
complete Pages deployment in `dedicated` mode; integrate the renderer into an
existing site workflow instead when the repository already uses Pages.

The workflow passes `PROOF_SCORECARD_BADGE_PAGES_ACCESS` to the
reconciler, which checks live repository visibility before reading evidence or
rendering. Public repositories leave the variable unset or set to `public`.
Private and internal repositories require the variable set to `private` and a
GitHub Pages API response confirming the site is not public; unknown visibility
or an unverifiable destination blocks publication. The variable requests a
check; it does not create or secure a Pages site. See the
[private repository guidance](../docs/quickstart.md#reporting-for-private-repositories)
for setup and migration steps.

The settings probes use trusted, no-checkout `pull_request_target` workflows.
Give `SECURITY_SETTINGS_TOKEN` only repository Administration read and Secret
scanning alerts read access. Missing or insufficient access publishes skipped
exact-head checks; it never passes the capability.

The release attestation workflow requires an artifact supplied by dispatch
input or `PROOF_ARTIFACT_PATH`. `PROOF_ARTIFACT_BUILD_COMMAND` is
optional. The workflow does not emit the nested artifact evidence contract or
invoke a release scorecard, so it is not yet a fully runnable Proof
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

`proof-scorecard.yml` runs as trusted `pull_request_target` code. It checks
out executable runtime only from the exact base SHA, sparse-checks out the exact
PR-head policy/configuration as fixed-path non-symlink data, and never executes
candidate code with the GitHub token. It waits up to 1,800 seconds, writes paired
timestamped scorecard JSON and Markdown plus timestamped evidence, appends the
Markdown to the job summary, and uploads `.artifacts/proof` as
`proof-scorecard-<run-id>`. Both scorecard commands pass
`--all-catalog-controls`, so a control the policy explicitly sets to
`not_activated` is published as **Not activated** on the dashboard rather than
collapsing to **Not reported**; those `GRAY` rows never count toward totals.
For pull-request events, the workflow also runs the trusted base PR metadata
validator on the event's title and body. It scores that result on the
`pull-request` subject beside the commit, and it also runs when the PR is
`edited`, so the dashboard's PR Metadata row reflects the current title and
body.

The native **Scorecard Workflow** badge reports whether this workflow ran. The
optional **Latest PR Scorecard** badge reports readiness and passed/active count
from the newest accepted PR artifact. A successful workflow may publish
`ORANGE / ALLOW`; the latest PR badge does not attest current `main`. The Pages
projection includes only aggregate status/counts, PR-size measurements and thresholds, source-run metadata, and a
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

SonarQube, Snyk, Semgrep AppSec Platform, FOSSA, Codex Code Review, and AI review
adapters are not installed as runnable profiles. A repository must copy a
template (where one is shipped) or supply its own workflow, add the required
credentials/configuration, verify exact check/evidence binding, and make an
explicit provider selection. A credential alone does not activate or satisfy a
capability.

Shipped vendor templates (copy into `.github/workflows/`; see
[docs/providers](../docs/providers/README.md)):

| Template | Workflow / check names | Command ownership |
| --- | --- | --- |
| `sonar.yml` | `SonarQube` / `SonarQube Quality Gate` | Scanner action, then the quality-gate wait action; `SONAR_TOKEN` |
| `snyk.yml` | `Snyk` / `Snyk Code`, `Snyk Open Source` | `pull_request_target`: `.proof/adapter.py --data-only` from the default branch runs `snyk code test`, and `snyk test` per static lockfile, against the head checkout read as data; consumers set `SNYK_CODE_ARGS` / `SNYK_OPEN_SOURCE_ARGS`; `SNYK_TOKEN` from the `proof-providers` environment |
| `fossa.yml` | `FOSSA` / `FOSSA` | `pull_request_target`: `.proof/adapter.py --data-only` from the default branch runs `fossa analyze --static-only-analysis` then `fossa test` against the head checkout read as data, for the exact revision; consumers set `FOSSA_ARGS` and optionally `FOSSA_ENDPOINT`; `FOSSA_API_KEY` from the `proof-providers` environment; CLI pinned by version and SHA-256 |

The Snyk, FOSSA, and AI PR Review templates never run pull-request code in a
job that holds a provider credential; see
[credential isolation](../docs/providers/README.md#credential-isolation). Each
job posts the provider check for the pull-request head and uploads the same
result as the run-bound `proof-<provider>-<run_id>` artifact with
`.proof/provider_check.py`. It fails its own, differently named job for every
non-passing outcome and puts the standard reason code (`credential-missing`,
`credential-withheld`, `authentication-failed`, `analysis-incomplete`,
`execution-error`, `unsupported-project`, `requires-dependency-resolution`,
`timed-out`, `revision-mismatch`, `configuration-missing`) in the job summary
and the check output.

This repository runs the templates it ships from `.github/workflows/` with
identical content, except those listed in `NOT_INSTALLED` in
`tooling/sync_workflow_templates.py` (`ai-toolkit-setup.yml`,
`security-scanning.yml`, and `soak.yml`), which Dependabot does not see; the
Python demo's installed workflows must also match. Every action uses one pin
across all of them, including the excluded templates.
Dependabot bumps only `.github/workflows/`, so after a pin bump run
`python3 tooling/sync_workflow_templates.py --write` (it parses workflows
with PyYAML from `tooling/requirements-lint.txt`); it copies pin-only changes
into the templates and refuses any other difference or symlinked workflow. The unit tests
fail on drift.

Other templates that are shipped but not installed by any profile:

| Template | Workflow / check names | Activation |
| --- | --- | --- |
| `ai-pr-review.yml` | `AI PR Review` / `AI Engineering Review`, `AI QA Review`, `AI Security Review`, `AI Repo Standards Review` | The `ai-engineering-adapter`, `ai-qa-adapter`, `ai-security-adapter`, and `ai-repository-standards-adapter` providers; `pull_request_target`: a repository-owned `AI_REVIEW_COMMAND`, run from the default branch against the head revision read as data, with only `ANTHROPIC_API_KEY` from the `proof-providers` environment, writes each role's result (reference adapter: `tooling/ai_review_claude.py`); jobs are skipped until `AI_REVIEW_COMMAND` is set; each job posts its role's check and puts self-reported finding counts in its run-bound evidence artifact; the consolidation job summarizes and never fails; advisory-only and never promotable |
| `security-scanning.yml` | `Security Scanning` / `CodeQL`, `Dependency Review`, `Semgrep`, `FOSSA`, `Snyk Open Source`, `Secret Scan` | Requires `CODEQL_LANGUAGES` (or reusable input `codeql-languages`); organization-style bundle that runs consumer-supplied `FOSSA_COMMAND` / `SNYK_OPEN_SOURCE_COMMAND` strings on `pull_request`, in jobs that hold `FOSSA_API_KEY` or `SNYK_TOKEN` next to pull-request code; prefer the adapter templates above, which own the command shape and isolate the credential |
| `soak.yml` | `Soak Check` / `Soak Check` | The `repository-soak` provider for the `runtime-soak` capability; runs `SOAK_COMMAND` on a schedule or dispatch; awaiting an environment-evidence producer and collection path; scheduled checks alone do not activate the control |

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
proof. The run-bound artifact also carries the validator's `pr_metadata` detail
(title match and required-section counts, no PR text) when the trusted base
validator emits it.

For `Format and Lint` and `Migration Validation`, configure the repository
command first and verify both success and failure behavior. The job remains
present and fails when its command is absent; this is deliberate protection
against a required context being satisfied by GitHub's skipped-job behavior.

See [ruleset guidance](../rulesets/README.md) before adding contexts.

## Starter workflow

`ai-toolkit-setup.yml` is not installed by the installer. Copy it into a
consuming repository's `.github/workflows/` and run it manually
(`workflow_dispatch`). It downloads `ai-toolkit.pyz` from the pinned release
tag you supply, verifies it against the SHA-256 you supply, runs
`ai-toolkit init --preview` into the job summary, and, when `apply=true`,
commits the installation to an `ai-toolkit/setup-<tag>` branch and opens a
pull request with `gh`. Discovered repository commands appear in the preview
as `gh variable set` lines; the workflow never writes them into the tree.
