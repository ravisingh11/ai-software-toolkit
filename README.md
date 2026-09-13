# Engineering Standards

**Engineering standards for an AI world.**

[![Version](https://img.shields.io/github/v/release/ravisingh11/engineering-standards?label=version)](https://github.com/ravisingh11/engineering-standards/releases/latest)
[![License](https://img.shields.io/github/license/ravisingh11/engineering-standards?label=license)](LICENSE)
[![Scorecard Workflow](https://github.com/ravisingh11/engineering-standards/actions/workflows/guardrails-scorecard.yml/badge.svg?event=pull_request_target)](https://github.com/ravisingh11/engineering-standards/actions/workflows/guardrails-scorecard.yml)
[![Latest PR Scorecard](https://ravisingh11.github.io/engineering-standards/guardrails-badge.svg)](https://ravisingh11.github.io/engineering-standards/)

AI changed the economics of software.

We can create more code, touch more files, and ship more change than ever
before. That is a huge unlock. It also creates a new problem: **velocity without
discipline becomes chaos.**

The answer is not more meetings, more process, or a handbook nobody reads. It
is lightweight guardrails that run with the work.

This repository turns practical engineering habits into executable checks:

- Keep changes small enough to understand.
- Test what you change.
- Review the code, including the code AI writes.
- Do not ship known security problems.
- Keep the repository's ground truth current.
- Make the build tell you whether a change is ready.

The philosophy is simple:

> **Move fast. Prove it works.**

Guardrails, not gates. The tools that do the work remain the source of their
own findings; this repository connects those results to the exact change being
shipped and makes the state visible. A missing check is not a pass.

Make the safe path the easy path. Application repositories keep their own
architecture and operating details; this project supplies a common engineering
backbone without inventing repository-specific ground truth.

## Guardrails model

A **capability** is a vendor-neutral engineering outcome such as unit testing or
secret detection. A **provider** is the tool that produces evidence for that
capability. Each selected capability has exactly one authoritative provider.
Supplemental providers remain visible and advisory; they cannot satisfy or
block the capability.

A provider may use GitHub check-run contracts for some capabilities and GitHub
review contracts for others. It cannot declare both contract types for the same
capability; Guardrails rejects that configuration before collecting evidence.

```text
profile -> capability -> authoritative provider -> exact-subject evidence
                  \---- supplemental providers ----> advisory evidence
```

Configuration expresses intent. Only fresh evidence for the exact commit,
pull-request state, artifact, or environment proves that a provider ran.

## Start here

- Use the [quick start](docs/quickstart.md) for installation and the first scan.
- Read [architecture](docs/architecture.md) for the contract and evidence flow.
- Use [control setup](docs/control-setup.md) for variables, tokens, profiles,
  providers, and promotion to enforcement.
- Use [control status](docs/control-status.md) to interpret colors and outcomes.
- Read the [producer contract](docs/producer-contract.md) before adding an
  adapter or external evidence.
- Use [workflow guidance](workflows/README.md) and [ruleset guidance](rulesets/README.md)
  before making any check required.
- Run the embedded [Python demo](examples/python-demo/) for a complete consumer.

## Profiles

| Profile | Selection | Capabilities |
| --- | --- | --- |
| `core` | Default | Repository and documentation validation, repository ground truth, change scope, PR metadata, format/lint, migration validation, build, unit tests, changed-code coverage, Semgrep CE, and Gitleaks CLI |
| `github` | Optional additive overlay | CodeQL, Dependency Review, GitHub Secret Protection, Dependabot verification, plus a release-attestation workflow that is not yet scorecard evidence |

Both profiles are advisory by default. Other vendors are providers, not
runnable profiles.

Core includes `PR Change Scope`, with repository-configurable thresholds in
`.guardrails/change-scope.yaml`. It reports total, meaningful, and excluded
change volume. The default 300-added-line and 500-changed-line thresholds are
advisory: oversized PRs stay visible without blocking until a repository
deliberately promotes the capability to `enforced`.

Core also includes mutable `PR Metadata` evidence. Configure title and body
requirements in `.guardrails/pr-metadata.yaml`; editing either field creates a
new pull-request fingerprint even when the head commit does not change. This
control runs only in the trusted GitHub pull-request workflow, not in a local
repository scan. The trusted workflow publishes a separate `PR Metadata` check
against the exact candidate head SHA, so repositories may promote that context
after observing it on representative pull requests. Runs are serialized per
pull request and newer metadata events cancel older in-progress runs. The check
cannot pass unless its run-bound evidence artifact uploads successfully.

## What runs on GitHub

Installing Guardrails with Actions adds independent workflows. Opening or
updating a pull request starts the applicable producers; the scorecard then
collects their results for the exact PR head. A workflow file means the check
is available, not that it passed.

This repository uses itself as a working example:

| Controls | GitHub behavior in this repository |
| --- | --- |
| Repository, documentation, and ground-truth validation | Active on every PR. An exact-head pass renders 🟢 **GREEN**. |
| PR change scope and PR metadata | Active on every PR update. Passing evidence renders 🟢 **GREEN**; an oversized PR remains advisory. |
| Format and lint | Active through `tooling/lint.sh`. Ruff, yamllint, and committed/staged/unstaged whitespace checks run on every PR. |
| Unit tests | Active through `tooling/test.sh`; all four Python test suites below run in the `Unit Tests` workflow. |
| Semgrep CE and Gitleaks | Active on every PR with repository-owned configuration. An exact-head pass renders 🟢 **GREEN**. |
| Build | Active through `tooling/build.sh`, which compiles the shipped Python sources into an isolated temporary bytecode tree. |
| Changed-code coverage | Active through `tooling/changed_code_coverage.sh`; coverage.py and diff-cover enforce at least 90% coverage on changed Python lines across the runtime, tooling, demo, skills, and security harness. |
| Migration validation | Active through `tooling/validators/validate_no_migrations.py`. This repository has no database, so the check recursively rejects common migration paths until a real framework-specific validator replaces it. |
| GitHub CodeQL, Dependency Review, and Secret Protection | GitHub profile enabled. These run on PRs after their repository variables and platform settings are verified. |
| Dependabot remediation | Deliberately not activated in this repository's change policy; Dependabot update PRs are managed separately. |
| Artifact provenance | Selected for release operations, not PR change scorecards. |
| SonarQube, Snyk, FOSSA, and AI review providers | Not selected as authoritative providers. A complete catalog report renders their capabilities ⚪ **GRAY**. |
| Future artifact, deployment, and runtime capabilities | Evidence contracts only; they remain ⚪ **GRAY** until implemented and activated. |

Consumer repositories receive the same workflow contracts, but must provide
their own real build, test, lint, coverage, and migration commands. See
[control setup](docs/control-setup.md).

## Two useful badges

The badges answer different questions:

- **Scorecard Workflow** is GitHub's native status for the Guardrail Scorecard
  workflow. The `event=pull_request_target` filter selects its PR executions
  explicitly and avoids GitHub's default-branch fallback showing `no status`.
- **Latest PR Scorecard** is an optional static badge showing the newest
  accepted PR evaluation, such as `GREEN 14/14` or `ORANGE 12/14`. It is a
  readiness signal for that PR, not an attestation of current `main`.

A successful workflow can still produce an advisory `ORANGE` score. Badge
publication is a post-scorecard reporting path; it never changes `allow`,
`block`, or required-check behavior.

Install the optional publisher during a clean install:

```sh
python3 /path/to/engineering-standards/tooling/install.py \
  --target /path/to/repo --scorecard-badge --dry-run
python3 /path/to/engineering-standards/tooling/install.py \
  --target /path/to/repo --scorecard-badge
```

For an existing Guardrails installation, add `--refresh-existing`. Then set
GitHub Pages to **GitHub Actions** and create these repository variables:

```text
GUARDRAILS_SCORECARD_BADGE_ENABLED=true
GUARDRAILS_SCORECARD_BADGE_PAGES_MODE=dedicated
```

The standalone publisher owns the repository's complete Pages deployment. If
the repository already publishes a Pages site, integrate its generated output
into that existing site workflow instead of enabling `dedicated` mode.

Use these URLs after the first successful publication:

```markdown
[![Scorecard Workflow](https://github.com/OWNER/REPOSITORY/actions/workflows/guardrails-scorecard.yml/badge.svg?event=pull_request_target)](https://github.com/OWNER/REPOSITORY/actions/workflows/guardrails-scorecard.yml)
[![Latest PR Scorecard](https://OWNER.github.io/REPOSITORY/guardrails-badge.svg)](https://OWNER.github.io/REPOSITORY/)
```

For an `OWNER.github.io` repository, omit `/REPOSITORY` from both Pages URLs.
The public site contains only aggregate status/counts, source-run metadata, and
a revision digest. Controls, findings, evidence, reasons, provider data, check
URLs, raw revisions, and source Markdown are excluded from Pages and remain in
the source Actions artifact, subject to the repository's normal artifact access.
See the [quick start](docs/quickstart.md#publish-the-optional-scorecard-badge).

## Install

Install Core runtime and Core GitHub Actions:

```sh
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo
```

Add the GitHub profile:

```sh
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo --profile github
```

Install without Actions, or add local pre-commit hooks:

```sh
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo --no-actions
python3 /path/to/engineering-standards/tooling/install.py --target /path/to/repo --local-hooks
```

`--local-hooks` requires `pre-commit` and refuses to overwrite an existing
`.pre-commit-config.yaml`. Use `--dry-run`, `--merge-existing`, or
`--refresh-existing` when adopting or updating an existing clean install.
The installer never copies credentials.

## Configure and run

```sh
python3 .guardrails/scan.py --help
python3 .guardrails/configure.py --help
python3 .guardrails/configure.py --list
python3 .guardrails/scan.py
```

The scanner writes nested JSON evidence and a timestamped Markdown scorecard to
`.artifacts/guardrails/`. It binds local evidence to a clean, exact `HEAD`.
Unavailable local tools and unconfigured local commands report `not_run` /
`NO RESULT`.

This repository's own command producers are in `tooling/`. Install the pinned CI
tools, then run the same build, test, coverage, lint, and migration commands used
by GitHub Actions:

```sh
python3 -m pip install --disable-pip-version-check \
  -r tooling/requirements-ci.txt
tooling/build.sh
tooling/test.sh
GUARDRAILS_COVERAGE_BASE_REF=origin/main tooling/changed_code_coverage.sh
tooling/lint.sh
python3 tooling/validators/validate_no_migrations.py
```

`tooling/lint.sh` checks committed, staged, and unstaged changes, so the local
command also catches whitespace defects before commit. The coverage command
uses the exact base commit supplied by the workflow and applies the policy's
90% target only to changed Python lines. Generated `.guardrails/` copies, test
files, and security fixtures are excluded; their canonical sources and real
testable code remain included. Python subprocesses inherit coverage collection,
and their parallel data files are combined before the changed-line gate runs.

For the embedded Python demo, these are real repository commands:

```sh
export GUARDRAILS_BUILD_COMMAND='python3 -m compileall -q app.py test_app.py tools .guardrails'
export GUARDRAILS_UNIT_TEST_COMMAND="python3 -m unittest discover -s . -p 'test_*.py'"
export GUARDRAILS_WORKING_DIRECTORY='.'
python3 .guardrails/scan.py
```

The same names are GitHub Actions repository variables. Set command variables
only when the repository has real commands for those capabilities. Unset build,
test, and coverage commands do not create passing evidence. Format/lint and
migration validation are stricter: their installed Actions jobs fail visibly
when the corresponding command is absent, preventing a promoted required check
from being satisfied by a skipped job. Configure both before the first pull
request after installing those workflows; never use `true` or an unrelated
command to manufacture a pass.

Core runs Semgrep Community Edition with repository-owned tested rules via
`semgrep scan`, and runs the Gitleaks CLI against complete Git history. Local
execution uses the pinned containers or exactly matching host versions.

## Modes and providers

```sh
python3 .guardrails/configure.py --enable-profile github --dry-run
python3 .guardrails/configure.py --set unit-tests=enforced --dry-run
python3 .guardrails/configure.py --select-provider changed-code-coverage=sonarqube --dry-run
python3 .guardrails/configure.py --add-supplemental deep-sast=snyk-code --dry-run
```

Remove `--dry-run` after reviewing the policy and provider changes. Use
`--operation release` for release policy or `--all-operations` when the
capability applies to both operations. The configurator rejects a capability
whose catalog stage does not apply to every selected operation, without writing
the invalid override.

Optional providers include SonarQube, Snyk, Semgrep AppSec Platform, FOSSA, and
Codex Code Review.
Each requires its own workflow or adapter, configuration, credentials, exact
evidence binding, and explicit authoritative or supplemental selection. A token
alone does not activate or pass a capability.

AI review controls are contractually `advisory-only`: configuration rejects
attempts to promote them to `enforced`. They may add review evidence, but they
must not become the sole merge gate. For Codex, enable native automatic reviews
in Codex settings (recommended) or request one with `@codex review`, then enable
`ai-engineering-review=advisory`. No repository secret is required.

## Status vocabulary

| Symbol | Readiness | Meaning |
| --- | --- | --- |
| 🟢 | **GREEN** | The authoritative provider passed for the exact subject. |
| 🟠 | **ORANGE** | An advisory capability lacks a passing authoritative result. The operation may still be allowed. |
| 🔴 | **RED** | An enforced capability lacks a passing authoritative result, or evidence targets the wrong subject. The operation is blocked. |
| ⚪ | **GRAY** | The capability is not activated for this operation and subject type. |

Raw producer statuses are `passed`, `failed`, `blocked`, and `not_run`. Public
scorecards display `not_run` or missing evidence as `no_result`. Supplemental
results never change the decision. Default scorecards omit inactive and
`evidence-only` catalog controls. Pass `--all-catalog-controls` to include them
as `GRAY` / `not_activated` rows.

## Local and pull-request flow

```text
local scan -> fix findings -> open PR -> independent provider checks
           -> exact-head evidence collection -> scorecard -> ruleset decision
```

Local scans provide feedback from the current machine. Pull-request checks are
the authoritative merge evidence because they run in the repository's trusted
workflow environment and bind results to the PR head. Check evidence must also
match the declared GitHub App or Actions workflow contract, as applicable. The
installed
`Artifact Provenance` workflow is release-attestation-only and never runs as a
PR check. It does not emit nested artifact evidence for a Guardrails release
scorecard, so artifact provenance is not yet a fully runnable Guardrails
capability and must not be added to PR required checks.

Do not require a status check until it has produced reliable, revision-bound
results with a stable name and a remediation owner. See [rulesets/README.md](rulesets/README.md).

## Ground truth and future capabilities

Consuming repositories own their architecture, standards, testing, security,
deployment, and contribution documents. List any existing relative paths in
`.guardrails/ground-truth-ai.yaml`; filenames and directories are configurable
and do not have to be repository-root conventions.

Container vulnerability, IaC misconfiguration, SBOM, artifact vulnerability,
deployment policy, dynamic application security, and runtime assurance are
catalog and evidence contracts only. Guardrails does not install or operate
tools for those future lifecycle capabilities.

## Repository map

| Path | Purpose |
| --- | --- |
| `policies/` | Capability catalog, profiles, provider definitions, and engineering policy |
| `guardrails/` | Schemas, evaluator, baseline, and repository-neutral validator |
| `tooling/` | Installer, configurator, producers, scanner, scorecard, and validators |
| `workflows/` | Core, GitHub-profile, and optional provider templates |
| `rulesets/` | GitHub default-branch protection template and activation guidance |
| `skills/` | Reusable agent workflows |
| `examples/` | Runnable consumer examples |
| `.guardrails/` | Installed runtime and repository-owned configuration in a consumer |

## License and validation

This repository is MIT licensed. Third-party tools, Actions, services, and rule
packs retain their own terms; see [licensing](docs/licensing.md).

The repository test and validation surfaces are deliberately visible:

| Surface | What it proves | GitHub check |
| --- | --- | --- |
| `guardrails/tests` | Evaluator, schema, policy, and evidence behavior | `Unit Tests` |
| `tooling/tests` | Installer, configurator, scanner, scorecard, workflow, and integration behavior | `Unit Tests` |
| `tooling/validators/tests` | Catalog, documentation, repository, scope, and metadata validation behavior | `Unit Tests` |
| `examples/python-demo` | A real consumer can install and execute Guardrails | `Unit Tests` |
| `tooling/build.sh` | Every distributed Python source compiles without polluting the worktree | `Build` |
| `tooling/changed_code_coverage.sh` | Changed Python lines meet the 90% target, including tested subprocesses | `Changed Code Coverage` |
| `tooling/validators/validate_no_migrations.py` | The repository's declared no-database ground truth remains true | `Migration Validation` |
| `tooling/validate-skills.py` | Shared skills and their focused tests are valid | `Validate / standards source` |
| Repository and documentation validators | Distributed contracts, internal links, and declared documentation targets are valid | `Validate / repository`, `Validate / standards source`, `Validate / docs` |
| `tooling/lint.sh` | Python correctness baseline, YAML structure, and whitespace rules | `Format and Lint` |

Run the four unit-test suites with the same entry point used by GitHub:

```sh
tooling/test.sh
```

Run the complete local validation before opening or updating a PR:

```sh
python3 -m pip install --disable-pip-version-check -r tooling/requirements-ci.txt
tooling/build.sh
tooling/test.sh
GUARDRAILS_COVERAGE_BASE_REF=origin/main tooling/changed_code_coverage.sh
python3 examples/python-demo/tools/validate_demo.py --documentation
python3 tooling/validate-skills.py
python3 tooling/validators/validate_repository.py
python3 tooling/validators/validate_documentation.py
python3 tooling/validators/validate_no_migrations.py
tooling/lint.sh
git diff --check
```
