# AI Software Toolkit

**Move fast. Prove it works.** Shared skills, QA workflows, and Proof checks for
planning, building, testing, securing, and releasing software with AI.

AI Software Toolkit supports development, QA, security, and release teams.
Skills guide repeatable work, functional QA exercises application behavior,
and Proof connects verification results to policy through revision-bound
checks and readable scorecards. Your repository owns its architecture,
acceptance criteria, and commands.

**All toolkit checks are optional to adopt.** Your repository chooses which
checks run, their tools and thresholds, and whether to enforce them. Examples
demonstrate language-specific implementations; they do not impose required
checks or branch rules on consuming repositories.

I built this because AI lets me create more code and ship changes faster than
ever. I wanted that speed without losing confidence in what I ship: lightweight
skills and checks that run with the work, with quality considered from the
first acceptance criterion through release and feedback.

The repository is **`ravisingh11/ai-software-toolkit`**, formerly
`ravisingh11/engineering-standards`. Existing forks remain connected. See the
[rename migration guide](docs/repository-rename.md) for remote, workflow, and
Pages updates; the repository rename did not change the runtime contract.

## What the toolkit brings together

| Component | Purpose | Start here |
| --- | --- | --- |
| Standards | Define expectations for quality, security, and accountable AI use | [AI development policy](policies/ai-development.md) |
| Skills | Guide agents through repeatable development, QA, security, and release work | [Install shared skills](skills/README.md#install-locally) |
| Verification | Produce evidence from tests, functional QA, and scanners | [Set up functional QA](skills/qa-bootstrap/SKILL.md) |
| Quality recipes | Select real linting, test integrity, defensive tests, changed-code coverage, and architecture checks | [Optional quality checks](#optional-quality-checks) |
| Proof | Evaluate evidence against policy and expose missing results | [Install and configure Proof](docs/quickstart.md) |
| Providers | Use SonarQube scanner and quality-gate actions; use adapter-owned commands and reason codes for Snyk and FOSSA | [Providers](docs/providers/README.md) |
| Reference app | Exercise installation and runtime behavior; inspect separate deployment evidence | [Reference app](docs/reference-app.md) |
| Measurement — aspiration | Learn whether delivery is improving across the lifecycle | [Vision and maturity](docs/vision.md) |

QA helps shape acceptance criteria and risk coverage, explores behavior, and
feeds failures back into future validation. Quality is shared across the
lifecycle; QA expertise is part of planning and improvement as well as testing.

See [the toolkit vision](docs/vision.md) for the Plan → Build → Validate →
Release → Improve direction and the distinction between available components,
optional integrations, and future work.

[![Version](https://img.shields.io/github/v/release/ravisingh11/ai-software-toolkit?label=version)](https://github.com/ravisingh11/ai-software-toolkit/releases/latest)
[![License](https://img.shields.io/github/license/ravisingh11/ai-software-toolkit?label=license)](LICENSE)
[![Scorecard Workflow](https://github.com/ravisingh11/ai-software-toolkit/actions/workflows/proof-scorecard.yml/badge.svg?event=pull_request_target)](https://github.com/ravisingh11/ai-software-toolkit/actions/workflows/proof-scorecard.yml)
[![Latest PR Scorecard](https://ravisingh11.github.io/ai-software-toolkit/proof-badge.svg)](https://ravisingh11.github.io/ai-software-toolkit/)

## Start here

Choose the entry point above for skills or QA. The demo below introduces
Proof (named Guardrails in v1.0.0); it does not include the newer QA bootstrap and functional-QA
integration listed under [Unreleased](CHANGELOG.md#unreleased).

Try the embedded Python demo in an isolated directory with Git, Python 3.11+
and a POSIX shell. No account, token, Docker, or paid service is required to
get a scorecard.

> [!NOTE]
> The demo pins **v1.0.0**, released before Guardrails was renamed Proof, so
> its commands use that release's `.guardrails/` and `GUARDRAILS_*` names. The
> next release switches them to `.proof/` and `PROOF_*`.

```sh
demo_workspace="$(mktemp -d)"
git clone --branch v1.0.0 https://github.com/ravisingh11/ai-software-toolkit.git "$demo_workspace/ai-software-toolkit"
standards_root="$demo_workspace/ai-software-toolkit"
cp -R "$standards_root/examples/python-demo" "$demo_workspace/python-demo"
cd "$demo_workspace/python-demo"

# The embedded demo already has an installation; refresh its shipped runtime.
python3 "$standards_root/tooling/install.py" --target . --refresh-existing --dry-run
python3 "$standards_root/tooling/install.py" --target . --refresh-existing
python3 .guardrails/configure.py --set unit-tests=advisory
export GUARDRAILS_BUILD_COMMAND='python3 -m compileall -q app.py test_app.py tools .guardrails'
export GUARDRAILS_UNIT_TEST_COMMAND="python3 -m unittest discover -s . -p 'test_*.py'"
export GUARDRAILS_WORKING_DIRECTORY='.'

# Local evidence requires a committed, clean HEAD. Identity is demo-only.
git init -q
git add .
git -c user.name='Guardrails Demo' -c user.email='demo@example.invalid' commit -qm 'chore: initialize Guardrails demo'
python3 .guardrails/scan.py
```

The scanner executes the configured demo commands and writes JSON evidence and
a timestamped Markdown report under `.artifacts/guardrails/`. It does not push
anything. Build and unit tests can pass locally; unconfigured commands,
unavailable scanner tools, and GitHub-only checks do **not** become passes.
Expect advisory gaps, not an all-green promise.

A small **illustrative** scorecard (not a live scan or badge):

| Readiness | Capability | Evidence |
| --- | --- | --- |
| 🟢 GREEN | Unit tests | Passed for the exact subject |
| 🟠 ORANGE | Changed-code coverage | No result; advisory |
| 🔴 RED | Build, if enforced | No result; blocks |
| ⚪ GRAY | Artifact provenance in a PR | Not activated |

See the [full illustrative report](docs/examples/sample-scorecard.md),
[status meanings](docs/proof/control-status.md), and
[onboarding guide](docs/quickstart.md) for real-repository setup and troubleshooting.

## Proof model

```text
profile -> capability -> authoritative provider -> exact-subject evidence
                  \---- supplemental providers ----> advisory evidence
```

A capability is an engineering outcome; its authoritative provider produces
the evidence. Supplemental providers stay advisory and cannot satisfy or block
it. Configuration expresses intent, not proof of execution. A missing check is
not a pass.

## Install

The shared [`ai-toolkit` CLI](docs/install.md) is the front door for Proof,
skills, and QA bootstrap: `discover` and `init --preview` are read-only,
`init --yes` installs the selected components and records `toolkit.toml` and
`toolkit.lock.json`, `doctor` reports installed / configured / verified state
without executing anything, `check` explains what ran, failed, and remains
unverified, and `update` refreshes managed files while preserving your edits.
The same code serves the CLI, the `toolkit-setup` skill, and the
`AI Toolkit Setup` starter workflow.

For the underlying installer, [preview and install Core](docs/quickstart.md#1-preview-and-install-core),
then [configure real commands](docs/quickstart.md#3-configure-repository-commands)
and [declare ground truth](docs/quickstart.md#4-declare-repository-ground-truth).
Do not substitute demo commands or no-ops for your application's validation.
The installer copies runtime/configuration and workflow files, not credentials.

## Configure and run

Follow [inspect policy and run](docs/quickstart.md#5-inspect-policy-and-run).
Commit installation and configuration before scanning. Dirty worktrees produce
no-result evidence rather than a passing claim about `HEAD`.
[Setup diagnostics](docs/quickstart.md#diagnose-installation)
inspect setup without executing your commands. Their `configured`,
`action_needed`, and `unverified` states describe
setup, not scan results. Exit zero is not a pass.

## Read PR size and LOC

Open the **PR Size / Files & LOC** Actions workflow and its **Files & LOC
report** job. The report compares the counted changes with the repository's
configured limits and separates excluded changes from the total diff.
The check listed on a PR retains the name **PR Change Scope**.

Large PRs can overwhelm human reviewers. Prefer smaller, focused PRs so
feedback is easier to act on and each change is easier to verify. Size limits
are review aids; staying below them does not establish correctness.

| Measurement | Toolkit default limit |
| --- | ---: |
| Counted files | 12 |
| Added lines | 300 |
| Added + deleted lines | 500 |
| Most added lines in one file | 150 |

These defaults warn only. The report states whether the consuming repository
uses advisory or enforced mode; a within-limit row is not proof that the PR's
other checks passed. Thresholds and excluded paths are defined in the
consumer's `.proof/change-scope.yaml`.

The [live scorecard dashboard](https://ravisingh11.github.io/ai-software-toolkit/#size-title)
shows the same measurements for its latest accepted PR snapshot. Its repository
label identifies whose changes are being measured; this toolkit dashboard does
not aggregate the reference app's PRs. Older evidence without structured
measurements shows unavailable. See [report details](docs/proof/control-setup.md#reading-the-pr-size-report).

For the other controls, the [evidence results guide](docs/proof/control-setup.md#reading-scorecard-evidence)
explains **passed**, **failed**, **blocked**, and **unverified**. The dashboard
represents every trusted built-in catalog control individually, with its ID,
name, purpose, and validated effective mode and evidence status when available.
Absent rows show **Not reported**, separately from explicit `not_activated`
modes; neither means a pass. An unverified result means usable evidence is
missing, not that the check failed. The source CI run links to detailed
evidence. Provider names link to their configuration at the evaluated revision;
**Latest reported run** links to validated same-repository GitHub check evidence
when present in that snapshot. Private provider details remain in the source
report. The dashboard
is a published PR snapshot; its timestamp does not prove it matches the current
PR head or main. **ALLOW** means enforced controls were satisfied for that
snapshot, not that the change is ready to merge or release.

### Scorecard freshness

The live scorecard checks for a newer publication on load, when returning to the
tab, and every 60 seconds while visible. **Matches the latest published snapshot**
means the displayed results match the site's published snapshot; it does not
verify current `main`, the latest PR head, CI success, or passing controls.

When a newer validated snapshot is published, an older-results notice offers
**Refresh latest**. Refresh is manual and preserves the selected check or section.
It reloads the published page without starting CI or enabling checks. Existing
results, including missing evidence, remain visible until refresh.

If the freshness check fails or metadata cannot be validated, freshness remains
**unknown**. A previously confirmed newer-publication notice stays visible after
a failed recheck. With JavaScript disabled, freshness is explicitly not checked
and a refresh link remains available. Tabs opened before this feature shipped
need one initial reload. Snapshot age alone does not establish staleness.
See the [freshness contract](docs/proof/control-setup.md#reading-scorecard-evidence).
All checks remain optional; freshness does not change activation or enforcement.

The [verified scorecard run, attempt 2](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39288247675/attempts/2)
evaluated PR #112 at [`d0e6753`](https://github.com/ravisingh11/ai-software-toolkit/commit/d0e6753a1085d8bfbf66aecfebea22dd5fbfbd98).
Its [successful publication](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39288744600)
used merged toolkit revision [`9ef9297`](https://github.com/ravisingh11/ai-software-toolkit/commit/9ef929780eaff0f863e9c44c5dbca8911f9f21b0).
Recorded on 2026-10-19, it retained an advisory PR-size failure and missing Snyk
evidence: **ORANGE / ALLOW**, with zero enforced controls. A successful workflow
or publication does not turn those results into passes.

### Recorded live verification and cleanup (2026-10-19)

The live verification after the README updates
([toolkit #113](https://github.com/ravisingh11/ai-software-toolkit/pull/113),
[reference app #34](https://github.com/ravisingh11/ai-software-toolkit-reference-app/pull/34))
confirmed that both public pages matched the HTML and JSON artifacts from their
latest successful publications at the time:

| Scorecard | Evaluated PR run | Pages publication | Recorded advisory result |
| --- | --- | --- | --- |
| Toolkit | [39295749865, attempt 1](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39295749865/attempts/1) | [39297574622](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39297574622) | 14/16 passed; PR metadata failed and dependency vulnerability had no result. |
| Reference app | [39295060071, attempt 1](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/39295060071/attempts/1) | [39296050722](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/39296050722) | 13/16 passed; changed-code coverage, platform secret protection, and dependency remediation had no result. |

Both snapshots were **ORANGE / ALLOW**, with **zero enforced controls**.
Missing evidence remained **Unverified**, never passed. Already-open older tabs
showed the newer-publication notice; mouse and keyboard **Refresh latest** loaded
the publications above and preserved `#size-title`. Neither page reported browser
errors. All **59 toolkit renderer tests** passed, including freshness failure
regressions. This records publication freshness, not current `main`, newer CI,
or the deployed reference Worker. Later publications may supersede these runs.

The local cleanup record covers **two merged local branches and two temporary
worktrees**, preserved in recoverable Git bundles and checkout archives, followed
by **310 ignored cache/junk files** removed (304 toolkit, six reference app).
All **8,589 inventoried evidence/state files** in the latter cleanup remained
unchanged by hash comparison. **183 tracked YAML files** were reviewed; none was
proven obsolete and none was deleted. Optional workflows, templates, historical
docs, QA reports, coverage, and Worker databases were retained. Cleanup manifests,
archives, screenshots, and logs remain in the local verification archive; these
local observations are separate from the linked CI artifacts.

The reference app also reconciled a duplicate CodeQL activation after this live
verification: GitHub default setup stays active, while the optional advanced
workflow opt-in was removed. Its selected advanced-workflow evidence contract
remains unchanged, so default-setup scans do not turn missing Deep SAST evidence
into a pass. See the [reference app configuration note](https://github.com/ravisingh11/ai-software-toolkit-reference-app#recorded-live-verification-and-cleanup-2026-10-19).

All checks remain optional to adopt. The five-language workflow remains **manual
(`workflow_dispatch`) and optional**; this verification did not rerun it or fill
missing PR coverage with the separately recorded example results.

## Optional quality checks

Choose the checks that fit your repository. The
[quality recipes](docs/standards/optional-quality-checks.md) provide runnable
building blocks; repository owners choose tools, source scope, thresholds,
CI triggers, and whether results are advisory or enforced. These recipes add
no default required checks or branch-protection changes.

| Check | What it exercises |
| --- | --- |
| Real linting | Language-aware rules, with formatting and type checking kept as separate commands |
| Test integrity | Fresh JUnit results, actual test cases, and repository-selected skipped-test budgets |
| Defensive tests | Authorization, tenant/resource access, invalid inputs, and other selected failure paths |
| Changed-code coverage | Fresh Cobertura reports compared with an explicit Git base and selected source paths |
| Architecture boundaries | Allowed dependency directions, cycles, and imports across selected boundaries |

The lint and architecture configurations in
[`examples/typescript-quality/`](examples/typescript-quality/README.md) are
**TypeScript examples**. Java, Python, PHP, Scala, and other languages need
their own tools and commands. Extend or replace the relevant recipe for your
language, framework, and source layout; an ESLint configuration cannot analyze
Java classes. See [language-specific choices](docs/standards/optional-quality-checks.md#choose-tools-for-your-language).

The separate [Fieldnotes reference app](https://github.com/ravisingh11/ai-software-toolkit-reference-app) has
[runnable examples for all five languages](https://github.com/ravisingh11/ai-software-toolkit-reference-app/tree/main/examples/polyglot),
using native tools against a shared defensive issue-transition contract:

| Language | Lint/static analysis | Coverage | Architecture check |
| --- | --- | --- | --- |
| Java | Checkstyle | JaCoCo | Compiled dependencies via `jdeps` |
| TypeScript | Type-aware ESLint | c8/V8 | dependency-cruiser |
| Python | Ruff | coverage.py | Conservative AST purity rules |
| PHP | PHPStan | Xdebug | Conservative token-based purity rules |
| Scala | WartRemover | JaCoCo | Compiled dependencies via `jdeps` |

Follow the [polyglot guide](https://github.com/ravisingh11/ai-software-toolkit-reference-app/blob/main/examples/polyglot/README.md)
for runtime requirements, explicit setup, local commands, and coverage scopes.
Its [Optional polyglot examples workflow](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/workflows/polyglot-examples.yml)
runs **only by manual dispatch (`workflow_dispatch`)**, for one language or
all five, with an explicit comparison base and chosen threshold. It does not
run on pushes or PRs and is not a required merge check. All these checks remain
optional; repositories choose their own CI triggers and enforcement.
Evidence covers the selected domain examples; the deployed reference app
remains TypeScript. Each consuming repository owns adoption and enforcement.

### Recorded five-language verification

The latest recorded [2026-10-19 manual run](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/39289785991)
passed all **30 stages** (versions, build, lint, tests, architecture, coverage)
and **115 conformance cases** (23 per language) on reference-app revision
[`e34993a`](https://github.com/ravisingh11/ai-software-toolkit-reference-app/commit/e34993afee31f40492dcacafcb93c5ab8e5782cb),
using toolkit revision [`9ef9297`](https://github.com/ravisingh11/ai-software-toolkit/commit/9ef929780eaff0f863e9c44c5dbca8911f9f21b0).

| Language-specific example | Changed-line coverage in example scope |
| --- | --- |
| Java | 100% |
| TypeScript | 93% |
| Python | 100% |
| PHP | 100% |
| Scala | 92% |

This recorded run used comparison base
[`2932827`](https://github.com/ravisingh11/ai-software-toolkit-reference-app/commit/2932827657d4758cdf030ab693239cfb2a23e258)
and a repository-selected 90% threshold. These are results for the selected
example scopes, not full-application coverage or a deployment attestation.
The same revision passed [Application acceptance](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/39289758236)
and the [configured Snyk workflow](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/39289758563).
The reference app's [PR #33 scorecard](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/39289788846)
is separate PR-head evidence: it retained three missing advisory results
(changed-code coverage, platform secret protection, and dependency remediation).
The manual example coverage does not fill that PR coverage gap.
See the [reference app's latest verification summary](https://github.com/ravisingh11/ai-software-toolkit-reference-app#latest-recorded-verification-2026-10-19)
for source revisions and remaining evidence limits. The
examples use each language's own tools; adapt or replace them for your stack.

## Profiles

Core is the default advisory profile: repository/documentation/ground-truth
validation, scope, PR metadata, lint, migration validation, build, unit tests,
changed-code coverage, Semgrep CE, and Gitleaks CLI. The optional additive
[GitHub profile](docs/quickstart.md#2-add-the-optional-github-profile) includes
CodeQL, Dependency Review, Secret Protection, and Dependabot verification.
Its release-attestation workflow is not PR scorecard evidence.

## Modes and providers

Keep capabilities advisory until their producer, stable check name,
exact-subject evidence, and remediation owner are verified.
[Promote one proven capability](docs/quickstart.md#8-promote-one-proven-capability);
policy mode and GitHub rulesets are separate settings. AI review remains
advisory-only. Agent-driven functional QA is an opt-in capability whose
workflow the [`qa-bootstrap` skill](skills/qa-bootstrap/SKILL.md) generates. See
[provider and control setup](docs/proof/control-setup.md).

For GitHub-managed CodeQL, explicitly select the optional
[`github-codeql-default-setup` provider](docs/providers/codeql.md). It validates
managed-workflow and all-language analysis provenance; the existing advanced
`github-codeql` contract and default selections stay unchanged. Unverifiable
or missing analyses remain unverified, never passed.

## Status vocabulary

🟢 **GREEN**: authoritative pass. 🟠 **ORANGE**: advisory gap.
🔴 **RED**: enforced gap or wrong-subject evidence; blocked.
⚪ **GRAY**: inactive for this operation/subject.
Raw `not_run` or absent evidence is displayed as `no_result`, never a pass.
Each check names its selected provider (for example, **GitHub CodeQL** for
Deep SAST). **Not configured** means no provider is selected; **Not reported**
means selection is unavailable in the snapshot. Provider selection is separate
from activation and evidence: a missing scan still names its selected provider.
Configuration links do not imply activation. A run link identifies the latest
reported check in this snapshot, including failed or skipped checks; it does not
claim a newer run exists or turn missing evidence into a pass.
All checks remain optional to adopt, and this display does not change enforcement.
The default report omits inactive catalog rows; use `--all-catalog-controls`
to include them. See the [status guide](docs/proof/control-status.md).

## What runs on GitHub

Installed workflows make producers available; files alone do not prove
activation. Configure supported providers and real command variables, then
[verify a pull request](docs/quickstart.md#7-open-a-pull-request).
The collector checks the exact PR head and trusted provider provenance.
Do not make a check required until you have observed reliable results.

For unconfigured Snyk integrations, explicitly set `SNYK_CODE_ENABLED=false`
and/or `SNYK_OPEN_SOURCE_ENABLED=false` to match the jobs you disable. The
scorecard skips waiting for those providers' absent checks while retaining
missing evidence as **no result**. Queued/running checks still wait, and a
selected enforced control still blocks without passing evidence. Unset or
empty variables retain normal waiting. See [Snyk setup](docs/providers/snyk.md).

The [verified fix run](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39184673806)
collected evidence in **19 seconds**, compared with **30 minutes 34 seconds**
using the previous trusted runtime on the same PR head. Missing Snyk evidence
remained **ORANGE / no result**; optionality and branch rules did not change.
See [recorded verification](docs/verification/scorecard-wait.md) for revisions,
tests, and the distinction between this repository and the reference app.

## Two useful badges

**Scorecard Workflow** reports workflow execution. **Latest PR Scorecard**
reports the newest accepted PR evaluation, not current `main`; workflow
success can still mean `ORANGE / ALLOW`.
[Badge setup, URLs, Pages ownership, and privacy](docs/quickstart.md#publish-the-optional-scorecard-badge)
live in the onboarding guide. Publication never changes enforcement.

## Local and pull-request flow

```text
local scan -> fix findings -> PR -> independent producers -> exact-head scorecard
```

Local results are machine feedback, not authoritative merge evidence. Follow
[workflow guidance](workflows/README.md) and [ruleset guidance](rulesets/README.md)
before requiring checks.

## Ground truth and future capabilities

Repositories own their architecture, testing, security, deployment, and
contribution docs; map existing paths in `.proof/ground-truth-ai.yaml`.
Artifact, deployment, and runtime capabilities without implemented producers
remain evidence contracts, not runnable assurances. See the
[architecture](docs/proof/architecture.md) and [producer contract](docs/proof/producer-contract.md).

## Repository map

Browse the [documentation index](docs/README.md) for adoption, operating guides,
standards, and retained design history. To run the toolkit against this repository,
use the [self-check guide](docs/self-check.md).

| Path | Purpose |
| --- | --- |
| `policies/` | Capabilities, profiles, providers, and engineering policy |
| `proof/`, `tooling/` | Evaluator, installer, producers, and validators |
| `workflows/`, `rulesets/` | GitHub workflow and enforcement templates |
| `skills/` | Reusable agent instructions |
| `pr-review/`, `prompts/`, `templates/` | Review contracts and reusable guidance |
| `security/` | Tested scanner rules and fixtures |
| `examples/` | Runnable consumers |
| `docs/proof/`, `docs/standards/` | Runtime guides and software delivery standards |
| `docs/archive/` | Historical designs and plans; current behavior is documented elsewhere |
| `.proof/`, `.github/workflows/`, `.agents/` | This repository's installed toolkit and CI |

The source and installed directories are intentional: the toolkit is also its
own consumer. See [source ownership and installed copies](docs/README.md#source-ownership-and-installed-copies)
before changing or refreshing them.

## License and validation

MIT licensed; third-party tools keep their own terms. See
[licensing](docs/licensing.md), [contributing](CONTRIBUTING.md), and the
[complete validation commands](AGENTS.md#verification).
Run `tooling/test.sh` for the repository's four unit-test suites.
Read the [changelog](CHANGELOG.md) and [v1.0.0 release notes](docs/releases/v1.0.0.md)
for supported contracts, upgrade instructions, and limitations.
