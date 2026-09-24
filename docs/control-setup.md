# Control setup

Guardrails selects capabilities through profiles and records the provider that
produced each result. Configure the producer first, verify exact-subject
evidence, then consider enforcement.

For missing commands, runtime files, tools, or GitHub setup visibility, use
the [read-only setup diagnostic](quickstart.md#diagnose-installation).
It gives next actions without running providers or treating configuration as
passing evidence. Local environment variables and GitHub Actions variables
are inspected separately.

## Core profile

Core is selected by default. A normal install deploys its runtime and workflows.

| Capability | Authoritative provider | Check | Repository setup |
| --- | --- | --- | --- |
| Repository validation | Repository Validators | `Validate / repository` | Installed validator; no credential |
| Documentation validation | Repository Validators | `Validate / docs` | Maintain `.guardrails/documentation.yaml` |
| Repository ground truth | Repository Validators | `Validate / ground truth` | Maintain `.guardrails/ground-truth-ai.yaml` |
| PR change scope | PR Change Scope | `PR Change Scope` | Maintain `.guardrails/change-scope.yaml`; defaults are advisory |
| PR metadata | Repository PR Metadata | `PR Metadata` | Maintain `.guardrails/pr-metadata.yaml`; binds mutable title/body state independently of the head SHA |
| Format and lint | Repository Format and Lint Command | `Format and Lint` | Set `GUARDRAILS_FORMAT_LINT_COMMAND` |
| Migration validation | Repository Migration Validation Command | `Migration Validation` | Set `GUARDRAILS_MIGRATION_VALIDATION_COMMAND` |
| Build | Repository Build Command | `Build` | Set `GUARDRAILS_BUILD_COMMAND` |
| Unit tests | Repository Unit Test Command | `Unit Tests` | Set `GUARDRAILS_UNIT_TEST_COMMAND` |
| Changed-code coverage | Repository Changed Code Coverage Command | `Changed Code Coverage` | Set `GUARDRAILS_CHANGED_COVERAGE_COMMAND` |
| Custom static analysis | Semgrep Community Edition | `Semgrep CE` | Installed tested rule pack; no token |
| Secret detection | Gitleaks CLI | `Gitleaks` | Complete Git history; no token |

### Repository command variables

Local and Actions producers use the same names:

| Variable | Required for | Behavior when absent |
| --- | --- | --- |
| `GUARDRAILS_SETUP_COMMAND` | Optional setup before repository commands | Setup step is omitted. |
| `GUARDRAILS_BUILD_COMMAND` | Build | The Actions job fails visibly; a local scan reports `NO RESULT`. |
| `GUARDRAILS_UNIT_TEST_COMMAND` | Unit tests | The Actions job fails visibly; a local scan reports `NO RESULT`. |
| `GUARDRAILS_CHANGED_COVERAGE_COMMAND` | Changed-code coverage | Coverage reports `NO RESULT`. |
| `GUARDRAILS_FORMAT_LINT_COMMAND` | Format and lint | The Actions job fails visibly; a local scan reports `NO RESULT`. |
| `GUARDRAILS_MIGRATION_VALIDATION_COMMAND` | Migration validation | The Actions job fails visibly; a local scan reports `NO RESULT`. |
| `GUARDRAILS_WORKING_DIRECTORY` | All repository commands | Defaults to `.`; must stay inside the repository. |

Use repository variables in GitHub and environment variables locally. Commands
run through `bash -euo pipefail -c` in the selected working directory. Configure
build, unit tests, format/lint, and migration validation before enabling their
workflows on active pull requests. Their Actions jobs intentionally fail when
the command is absent, preventing a promoted required check from passing
through a skipped job. Do not use a no-op command to make any check green: each
command must exercise the repository's actual engineering contract.

This repository uses a deliberately narrow, debt-aware baseline:

```sh
python3 -m pip install --disable-pip-version-check \
  -r tooling/requirements-ci.txt
tooling/build.sh
tooling/test.sh
GUARDRAILS_COVERAGE_BASE_REF=origin/main tooling/changed_code_coverage.sh
tooling/lint.sh
python3 tooling/validators/validate_no_migrations.py
```

Its GitHub repository variables are:

```text
GUARDRAILS_SETUP_COMMAND=python3 -m pip install --disable-pip-version-check -r tooling/requirements-ci.txt
GUARDRAILS_BUILD_COMMAND=tooling/build.sh
GUARDRAILS_CHANGED_COVERAGE_COMMAND=tooling/changed_code_coverage.sh
GUARDRAILS_CODEQL_LANGUAGES=python,actions
GUARDRAILS_DEPENDENCY_REVIEW_ENABLED=true
GUARDRAILS_FORMAT_LINT_COMMAND=tooling/lint.sh
GUARDRAILS_MIGRATION_VALIDATION_COMMAND=python3 tooling/validators/validate_no_migrations.py
GUARDRAILS_UNIT_TEST_COMMAND=tooling/test.sh
```

This repository enforces repository validation, build, unit tests, format and
lint, and migration validation for pull requests. Their exact observed check
contexts are required by the live default-branch ruleset. Other selected
capabilities remain advisory unless this repository's policy says otherwise.

`tooling/lint.sh` checks whitespace errors in committed, staged, and unstaged
content, Python syntax and name errors through Ruff, and YAML structure and
duplicate keys through yamllint.
The pinned configuration intentionally does not make historical Python or YAML
style debt a prerequisite for unrelated changes. Tighten the checked rules in
small, separately reviewed changes.

`tooling/test.sh` is this repository's canonical unit-test entry point. It runs
the Guardrails runtime, tooling, validator, and embedded consumer-demo suites;
the `Unit Tests` GitHub workflow invokes the same command.

`tooling/build.sh` byte-compiles the shipped Python source into a temporary
directory and leaves the worktree unchanged. `tooling/changed_code_coverage.sh`
uses coverage.py plus diff-cover to require at least 90% coverage on Python
lines changed from `GUARDRAILS_COVERAGE_BASE_REF` across the runtime, tooling,
demo, skills, and security harness. Generated copies, tests, and fixtures are
excluded. `tooling/coverage.ini` enables subprocess collection and parallel
data files. The script exposes a repository-owned `sitecustomize` bootstrap so
this also works where coverage.py cannot write into the Python installation's
site-packages directory, then combines parent and child data before evaluating
changed lines.

In Actions, the coverage command also writes a job summary with the outcome,
configured target, and diff-cover's measured results. If no measured changed
lines exist, it explains why no percentage applies instead of implying 100%
coverage. All test suites still run; this messaging change does not make
docs-only runs faster or change the exit status. Failed comparisons retain
their failure and publish details when available.

The migration command encodes this repository's actual ground
truth: it has no database, so recursively introducing a common migration path
fails until the command is replaced with validation for the chosen migration
framework. Dependency, generated, and worktree directories are excluded from
that search.

### Pull-request metadata

`.guardrails/pr-metadata.yaml` defines a title regular expression and required
body markers:

```json
{
  "version": 2,
  "title_pattern": "^ENG-[0-9]+ ",
  "required_body_markers": ["## Summary", "## Testing"]
}
```

The trusted workflow runs when a pull request is opened, edited, synchronized,
or reopened. Its `pull-request` subject hashes repository, PR number, head SHA,
update time, title, and body. A title/body edit invalidates older metadata
evidence without invalidating commit-bound build or test evidence. Local scans
do not fabricate pull-request context, so they do not evaluate this control.
Because `pull_request_target` jobs belong to the trusted base workflow suite,
the workflow also publishes a run-bound `PR Metadata` check explicitly against
the candidate head SHA. Require that custom context—not the base-SHA job—when
promoting the control. New events cancel older in-progress runs for the same
pull request. The custom check fails if its required run-bound evidence artifact
cannot be uploaded.

### Semgrep CE

Core runs `semgrep scan --error` with `.guardrails/semgrep-rules.yml`. The
workflow first runs Semgrep's rule tests against the installed positive and
negative fixtures. It does not use cloud-managed rules or require an AppSec
Platform token.

The pinned container is:

```text
semgrep/semgrep@sha256:b94b53d02fd4a022f9eac4e2af1380f5c3c4c21400e79d3336bdff1d1db5e796
```

Local scans prefer Docker with networking disabled. Without Docker they require
host Semgrep `1.175.0` exactly. Missing rules, unavailable Docker, or a host
version mismatch reports `NO RESULT`.

Repository-owned and third-party Semgrep rules can have licenses independent of
the Semgrep engine. Review every rule pack before copying it.

### Gitleaks CLI

Core runs `gitleaks git --redact --no-banner .` from this pinned container:

```text
ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
```

The workflow checks out full history. Local scans require complete Git history
and either Docker or host Gitleaks `8.30.1` exactly. Guardrails uses the MIT
Gitleaks CLI, not the separately licensed Gitleaks Action.

## GitHub profile

Install or add the profile with:

```sh
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo --profile github
```

| Capability | Provider/check | Required repository setup |
| --- | --- | --- |
| Deep SAST | GitHub CodeQL / `CodeQL` | Set `GUARDRAILS_CODEQL_LANGUAGES`; ensure GitHub code-scanning support. |
| Dependency change review | GitHub Dependency Review / `Dependency Review` | Set `GUARDRAILS_DEPENDENCY_REVIEW_ENABLED=true`; ensure the repository is eligible for Dependency Review. |
| Platform secret protection | GitHub Secret Protection / `GitHub Secret Scan` | Enable Secret Scanning and push protection; optional settings token below. |
| Dependency remediation | GitHub Dependabot / `Dependabot Verification` | Enable vulnerability alerts and automated security fixes; optional settings token below. |
| Release attestation helper | GitHub Artifact Attestations / `Artifact Provenance` | Supply a release artifact path and any build command; this is not yet Guardrails scorecard evidence. |

### GitHub variables and token

| Name | Kind | Used by |
| --- | --- | --- |
| `GUARDRAILS_CODEQL_LANGUAGES` | Variable | CodeQL language input |
| `GUARDRAILS_DEPENDENCY_REVIEW_ENABLED` | Variable | Dependency Review activation; exact value `true` |
| `GUARDRAILS_ARTIFACT_BUILD_COMMAND` | Variable | Optional release artifact build |
| `GUARDRAILS_ARTIFACT_PATH` | Variable | Release artifact path when not supplied by dispatch input |
| `SECURITY_SETTINGS_TOKEN` | Secret | GitHub Secret Protection and Dependabot setting probes |

`SECURITY_SETTINGS_TOKEN` is optional. Without it, both setting probes publish
exact-head skipped checks and the scorecard reports `NO RESULT`. When used, give
it only repository Administration read and Secret scanning alerts read access.
The trusted `pull_request_target` workflows do not check out PR code or expose
the protected token to PR-controlled commands.

A configured token proves only that the probe can attempt the API calls. A
passing result still requires the relevant settings and alert state.

### Release attestation boundary

The installed `Artifact Provenance` workflow runs on a published release or
manual dispatch and attests the exact artifact selected by the dispatch input
or `GUARDRAILS_ARTIFACT_PATH`. It is release-attestation-only: it does not run
on pull requests, emit the nested artifact evidence contract, or invoke a
Guardrails release scorecard. Until those paths exist and are tested, artifact
provenance is not a fully runnable Guardrails capability and its workflow/job
name must not be configured as a PR required check.

## Ground-truth paths

`.guardrails/ground-truth-ai.yaml` accepts repository-relative paths to files
that actually exist:

```json
{
  "version": 1,
  "documents": [
    {"path": "README.md"},
    {"path": "docs/design/architecture.md"},
    {"path": "engineering/security/controls.md"}
  ]
}
```

The consuming repository chooses the names and locations. Guardrails does not
copy application ground truth into this standards repository.

## Optional badge publishing

The native **Scorecard Workflow** badge reports the GitHub workflow conclusion.
The optional **Latest PR Scorecard** badge reports the newest accepted PR
readiness and passed/active count. Workflow success may still contain an
advisory `ORANGE` result, and the latest PR badge does not attest current
`main`.

Install the publisher with `--scorecard-badge`; add `--refresh-existing` for an
existing installation. Configure GitHub Pages to build with GitHub Actions and
set both repository variables:

```text
GUARDRAILS_SCORECARD_BADGE_ENABLED=true
GUARDRAILS_SCORECARD_BADGE_PAGES_MODE=dedicated
```

No secret is required. `dedicated` mode owns the complete Pages deployment, so
repositories with an existing Pages site must integrate the generated output
into that site's workflow instead. Public output is limited to aggregate
status/counts, source-run metadata, and a revision digest. Detailed controls,
findings, evidence, reasons, provider data, check URLs, raw revisions, and source
Markdown are excluded from Pages and remain in the source Actions artifact
under normal repository access. The publisher is reporting only; do
not add it to required checks. See the complete commands and badge URLs in the
[quick start](quickstart.md#publish-the-optional-scorecard-badge).

## Provider selection

List current modes and provider selections:

```sh
python3 .guardrails/configure.py --list
```

Change the authoritative provider or add a supplemental provider:

```sh
python3 .guardrails/configure.py \
  --select-provider changed-code-coverage=sonarqube \
  --set changed-code-coverage=advisory \
  --dry-run

python3 .guardrails/configure.py \
  --add-supplemental deep-sast=snyk-code \
  --dry-run
```

Supplemental evidence is always advisory. It cannot satisfy or block the
capability. A provider cannot be both authoritative and supplemental for the
same capability.

## Optional vendor providers

These definitions are available but are not runnable profiles and are not
installed as active integrations. Snyk, FOSSA, and the QA Bootstrap Workflow have
no shipped workflow template; consumers must supply their own reviewed workflow
or adapter.

| Provider | Capabilities | Declared credential | Activation responsibility |
| --- | --- | --- | --- |
| SonarQube | Static quality, changed-code coverage | `SONAR_TOKEN` | Configure project/host settings and a workflow or adapter that emits exact-head `SonarQube Quality Gate` evidence. |
| Snyk Code | Deep SAST | `SNYK_TOKEN` | Supply a repository or organization workflow/adapter and exact-head `Snyk Code` evidence. |
| Snyk Open Source | Dependency vulnerability | `SNYK_TOKEN` | Supply a repository or organization workflow/adapter and exact-head `Snyk Open Source` evidence. |
| Semgrep AppSec Platform | Custom static analysis, deep SAST | `SEMGREP_APP_TOKEN` | Supply an organization-approved integration and exact-head `Semgrep` evidence. |
| FOSSA | Dependency vulnerability, license compliance | `FOSSA_API_KEY` | Supply a repository or organization workflow/adapter and exact-head `FOSSA` evidence. |
| QA Bootstrap Workflow | Functional QA | None (the agent API key and app test credentials are repository secrets named in `config.yaml`) | Generate the read-only `.github/workflows/qa.yml` advisory check and trusted `.github/workflows/qa-report.yml` reporter with the `qa-bootstrap` skill, verify the `QA / report` check on a representative pull request, then set `functional-qa=advisory`. Guardrails records the exact-head check result; it does not run the agent. |
| Codex Code Review | AI engineering review | None | Connect the repository to Codex, enable native automatic reviews in Codex settings (recommended) or comment `@codex review`, then set `ai-engineering-review=advisory`. Guardrails accepts only an exact-head review from `chatgpt-codex-connector[bot]`. |

Functional QA is advisory-only. The PR can edit its execution workflow and
result source, so `QA / report` must not be required for merge or promoted to
`enforced`. The trusted reporter protects posting credentials; it does not
make PR-authored execution authoritative. A protected producer architecture
would require separate design and verification. Learning suggestions use
structured `action_required` entries for human review; automatic learning PRs
and commits are not implemented.

Do not add a credential until the adapter is ready. Do not select a vendor as
authoritative until its evidence contract and failure behavior are verified.

Codex posts a standard GitHub review and can follow repository `AGENTS.md`
guidance. The provider marks exact-head review completion; it does not claim
that AI found every defect. If your GitHub installation uses a different bot
login, update `review_author` in `.guardrails/providers.yaml` to the exact
observed login. AI review controls remain advisory-only and cannot be promoted.
See [OpenAI's Codex GitHub review setup](https://learn.chatgpt.com/docs/third-party/github)
for connection, automatic-review, and `@codex review` instructions.

## Promote to enforcement

1. Run the provider on representative pull requests.
2. Confirm evidence binds to the exact subject.
3. Confirm the exact stable check name and failure behavior. Remove or invalidate
   required configuration and verify the check does not pass; `Format and Lint`
   and `Migration Validation` must fail when their command variable is absent.
4. Assign a remediation owner.
5. Set the capability to `enforced`.
6. Add that exact check context to the repository ruleset.

```sh
python3 .guardrails/configure.py --set unit-tests=enforced --dry-run
python3 .guardrails/configure.py --set unit-tests=enforced
```

Policy enforcement without a matching ruleset does not protect merge. A
required status check without a reliable provider can deadlock merge.
The promotion sequence applies only to controls whose catalog
`enforcement_policy` is `promotable`; AI review and functional QA controls are
`advisory-only`.

## Evidence-only lifecycle controls

Container vulnerability, IaC misconfiguration, artifact SBOM, artifact
vulnerability, deployment policy, dynamic application security, and runtime
assurance are future evidence contracts only. Guardrails does not install or
operate container scanners, SBOM generators, policy engines, DAST tools, or
observability stacks for them.
