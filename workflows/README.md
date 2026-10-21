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

The scorecard normally waits for selected providers to report the exact head.
For Snyk jobs disabled by `SNYK_CODE_ENABLED=false` or
`SNYK_OPEN_SOURCE_ENABLED=false` (case-insensitive, matching the producer job
conditions), its trusted workflow supplies `--no-wait-provider` polling hints.
Absent checks still produce visible `not_run` evidence; selected controls keep
their modes, so an advisory gap stays ORANGE and an enforced gap still blocks.
Already queued/running checks and other selected providers retain normal
waiting and provenance validation. No secret is read for this decision.
Refresh the runtime and workflow together. The scorecard executes the trusted
default-branch runtime, so a fix PR can still show the old wait until merged.
See [Snyk polling and evidence](../docs/providers/snyk.md#outcomes) for details.

Repository command workflows accept nonempty `PROOF_*` environment variables
first, then optional repository-owned `.proof/commands.json`. The checked-in
file supports fork PR runs where repository variables are unavailable. Its
`commands` keys are `build`, `unit-tests`, `format-and-lint`,
`migration-validation`, and `changed-code-coverage`; optional `setup` and
`working_directory` correspond to `PROOF_SETUP_COMMAND` and
`PROOF_WORKING_DIRECTORY` (default `.`). The installer does not create or
overwrite this file. The [command configuration guide](../docs/quickstart.md#checked-in-producer-commands-for-fork-ci)
shows the versioned JSON format and validation rules.

Commands execute only in ordinary `pull_request` jobs with a read-only token.
Setup failures and producer failures retain their nonzero exit status.
Setup and producer run as separate Actions steps using the runner's
`--phase setup` and `--phase producer`, so setup writes to `GITHUB_PATH` and
`GITHUB_ENV` take effect before the producer. Local invocations default to both
phases in order. `PROOF_SETUP_COMMAND` is scoped to the setup subprocess and removed from the
producer environment, so nested fixture or consumer checks do not repeat the
outer repository's setup. Build, unit tests, format/lint,
and migration validation always create their named job; an absent command
fails the job so a promoted required context cannot be satisfied by a skipped
producer. Changed-code coverage uses a separate configuration-discovery job;
its producer remains skipped when neither source supplies a command. Selecting
commands does not change repository-selected advisory modes or required checks. Local scans continue to represent absent commands as `NO RESULT`.

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

PR scope and scorecard metadata jobs use the workflow-file commit
(`github.workflow_sha`) for their trusted runtime and policy on
`pull_request_target` and manual runs. This keeps newly installed helpers
available even when a PR event still reports an older base commit. Both jobs
accept PR `edited` events so metadata can be refreshed after a runtime update.
The scorecard's `pull_request_review` trigger retains the event base commit:
review workflows run on a PR merge ref, which is not a trusted runtime source.
See GitHub's [workflow context](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context)
and [event semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target).

Each job records the actual checked-out runtime/policy SHA in its summary.
Event base/head SHAs remain comparison inputs; source-binding `base_sha` and
the evidence collector's `--trusted-base-revision` retain their existing PR
comparison and provider-verification meaning, independently of runtime checkout.
The trusted metadata helper fetches full Git ancestry into a fresh bare
repository through the base repository's PR ref and verifies the exact event
base/head commits. It uses ephemeral authentication for private repositories
without persisting credentials or checking out candidate code.

Scope inspection reads Git objects directly. Candidate policy validation reads
only `.proof/policy.yaml`, after verifying its parent tree, regular
non-executable blob mode, and 1 MiB size bound. The trusted parser validates the
materialized data; scorecard enforcement continues to use the trusted base
policy. Candidate hooks, submodules, and executable runtime are not run by
these metadata jobs. A moving PR head fails the binding check and requires a
new event or rerun.


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
| `security-scanning.yml` | `Security Scanning` / `CodeQL`, `Dependency Review`, `Semgrep`, `Secret Scan` | Requires `CODEQL_LANGUAGES` (or reusable input `codeql-languages`); organization-style bundle that runs consumer-supplied `SEMGREP_COMMAND` / `SECRET_SCAN_COMMAND` strings against pull-request code on `pull_request` and therefore declares and reads no secrets; FOSSA and Snyk Open Source are not part of it, so use the `fossa.yml` and `snyk.yml` adapter templates above |
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

## Artifact attestation action maintenance

Installed workflows, reusable templates, and the Python demo pin
`actions/attest` v4.2.2 consistently. The existing explicit `subject-path`
inputs and lifecycle bundle output remain supported. This update does not
change permissions, workflow triggers, provider selection, or enforcement.
After Dependabot updates an installed pin, run
`python3 tooling/sync_workflow_templates.py --write` to refresh shipped copies.

## CodeQL action maintenance

Keep the CodeQL initialization and analysis steps on the same pinned release.
The installed workflow and reusable template both use CodeQL v4.39.0;
regenerate templates with `python3 tooling/sync_workflow_templates.py --write`
when changing installed action pins. This maintenance does not change workflow
permissions or a consuming repository's enforcement choices.

Dependabot groups CodeQL action version updates in one pull request using the
`github/codeql-action/*` dependency pattern. This keeps initialization, analysis
and any autobuild action updates together. Template regeneration is still
needed because Dependabot updates installed GitHub Actions workflows only.
The group controls update packaging, not approval, automatic merging or
required-check policy.

## Artifact upload action maintenance

The installed workflows and reusable templates use the pinned
`actions/upload-artifact` v7.0.2 patch release. Regenerate templates with
`python3 tooling/sync_workflow_templates.py --write` after changing an installed
action pin so consumers receive the same release. Permissions and enforcement
choices remain owned by each repository.

## Artifact download action maintenance

The installed workflows and reusable templates use the pinned
`actions/download-artifact` v8.0.2 patch release. Regenerate templates with
`python3 tooling/sync_workflow_templates.py --write` after changing an installed
action pin so consumers receive the same release. Permissions and enforcement
choices remain owned by each repository.

## Cosign installer action maintenance

Installed lifecycle verification, its reusable template, and the Python demo
pin `sigstore/cosign-installer` v4.1.2 consistently. The workflow deliberately
retains the explicit `cosign-release: v2.6.0` verifier; installer v4 supports
Cosign v2, so this action update does not adopt Cosign v3 or change verification
commands. The installer uses its checksum-pinned bootstrap to verify the
requested release. Permissions, manual lifecycle activation, and policy modes
are unchanged. Run `python3 tooling/sync_workflow_templates.py --write` after
installed action pin updates.

## Optional lifecycle verification

`lifecycle-verification.yml` is installed as a manual (`workflow_dispatch`)
workflow. It builds an isolated verification artifact, runs real Trivy scans,
CycloneDX generation, local ZAP, deployment/runtime probes and a bounded soak,
then separately attests the image and typed receipt. It changes no required
checks or policy defaults. `PROOF_LIFECYCLE_ENABLED=true` opts the trusted PR
scorecard into exact-subject receipt import. Missing evidence and actual failed
results remain visible. See [lifecycle setup and trust](../docs/providers/lifecycle.md)
for BuildKit, pinned fixture, sandbox, signature and bootstrap requirements.

### Published scorecard identity and evidence gaps

`proof-scorecard.yml` records a version 2 source binding containing the exact
checked-out trusted runtime SHA alongside the PR head and base. The default-branch
publisher validates that runtime's ancestry and passes only bounded PR/revision
identity to the renderer. Version 1 historical artifacts remain supported; their
unrecorded runtime is labeled unknown instead of inferred from the PR head.

The public page identifies the evaluated PR, commit, PR base, policy/runtime,
page renderer, and source evaluation start. Publishing does not rerun historical
checks. Known missing, skipped, pending and revision-mismatched evidence conditions
have safe public explanations; arbitrary provider reasons remain private.
Validated PR metadata evidence retains a direct producer-result link.

Manual lifecycle checks are grouped separately in the attention list and labeled
on their cards. This presentation changes neither their selection nor their
contribution to totals. Checks remain optional to adopt, polyglot verification
remains manual, and GitHub required merge checks remain separate from the toolkit
policy decision. On mobile the freshness notice stays in normal document flow.

This repository explicitly selects every built-in check as advisory for its
applicable change/release stage. This repository setting does not change the
consumer baseline. Unconfigured providers remain unverified. Collection samples
manual QA and native reviews without waiting for absent results; it also avoids
waiting for optional providers whose workflow activation flags are off. A review
submission can refresh the scorecard through the existing review event. Provider
credentials and external service activation are separate repository decisions.

The repository's event policy also permits the scorecard's existing
`pull_request_review` trigger. Lifecycle PR-context rejection can mean that the
PR has closed or that its head/base changed; the public explanation does not
claim which condition failed when the collector reports them together.

Release-stage advisory selection also covers the catalog's `pre-release`,
`deployment`, `post-deployment`, and `runtime` stages. Runtime Soak, Deployment
Policy, Dynamic Application Security, and Runtime Assurance therefore remain
selected as advisory alongside the other built-in controls. A missing manual
verification result stays unverified, and does not deactivate its policy mode.
