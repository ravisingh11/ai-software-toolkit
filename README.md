# Engineering Standards

**Move fast. Prove it works.** Guardrails turns engineering policy into
revision-bound checks and readable scorecards. Keep changes reviewable, test
what changed, and make missing evidence visible. Your repository owns its
architecture and commands; Guardrails connects the results.

I built this because AI lets me create more code and ship changes faster than
ever. I wanted that speed without losing confidence in what I ship: lightweight
checks that run with the work, not another handbook to remember.

[![Version](https://img.shields.io/github/v/release/ravisingh11/engineering-standards?label=version)](https://github.com/ravisingh11/engineering-standards/releases/latest)
[![License](https://img.shields.io/github/license/ravisingh11/engineering-standards?label=license)](LICENSE)
[![Scorecard Workflow](https://github.com/ravisingh11/engineering-standards/actions/workflows/guardrails-scorecard.yml/badge.svg?event=pull_request_target)](https://github.com/ravisingh11/engineering-standards/actions/workflows/guardrails-scorecard.yml)
[![Latest PR Scorecard](https://ravisingh11.github.io/engineering-standards/guardrails-badge.svg)](https://ravisingh11.github.io/engineering-standards/)

## Start here

Try the embedded Python demo in an isolated directory with Git, Python 3.11+
and a POSIX shell. This pins **v1.0.0**; “Guardrails v2” names the runtime
and evidence contract, not the repository release version. No account, token, Docker,
or paid service is required to get a scorecard.

```sh
demo_workspace="$(mktemp -d)"
git clone --branch v1.0.0 https://github.com/ravisingh11/engineering-standards.git "$demo_workspace/engineering-standards"
standards_root="$demo_workspace/engineering-standards"
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
[status meanings](docs/control-status.md), and
[onboarding guide](docs/quickstart.md) for real-repository setup and troubleshooting.

## Guardrails model

```text
profile -> capability -> authoritative provider -> exact-subject evidence
                  \---- supplemental providers ----> advisory evidence
```

A capability is an engineering outcome; its authoritative provider produces
the evidence. Supplemental providers stay advisory and cannot satisfy or block
it. Configuration expresses intent, not proof of execution. A missing check is
not a pass.

## Install

For your own repository, [preview and install Core](docs/quickstart.md#1-preview-and-install-core),
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
advisory-only. See [provider and control setup](docs/control-setup.md).

## Status vocabulary

🟢 **GREEN**: authoritative pass. 🟠 **ORANGE**: advisory gap.
🔴 **RED**: enforced gap or wrong-subject evidence; blocked.
⚪ **GRAY**: inactive for this operation/subject.
Raw `not_run` or absent evidence is displayed as `no_result`, never a pass.
The default report omits inactive catalog rows; use `--all-catalog-controls`
to include them. See the [status guide](docs/control-status.md).

## What runs on GitHub

Installed workflows make producers available; files alone do not prove
activation. Configure supported providers and real command variables, then
[verify a pull request](docs/quickstart.md#7-open-a-pull-request).
The collector checks the exact PR head and trusted provider provenance.
Do not make a check required until you have observed reliable results.

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
contribution docs; map existing paths in `.guardrails/ground-truth-ai.yaml`.
Artifact, deployment, and runtime capabilities without implemented producers
remain evidence contracts, not runnable assurances. See the
[architecture](docs/architecture.md) and [producer contract](docs/producer-contract.md).

## Repository map

| Path | Purpose |
| --- | --- |
| `policies/` | Capabilities, profiles, providers, and engineering policy |
| `guardrails/`, `tooling/` | Evaluator, installer, producers, and validators |
| `workflows/`, `rulesets/` | GitHub workflow and enforcement templates |
| `skills/` | Reusable agent instructions |
| `examples/` | Runnable consumers |
| `.guardrails/` | Installed runtime and consumer-owned configuration |

## License and validation

MIT licensed; third-party tools keep their own terms. See
[licensing](docs/licensing.md), [contributing](CONTRIBUTING.md), and the
[complete validation commands](AGENTS.md#verification).
Run `tooling/test.sh` for the repository's four unit-test suites.
Read the [changelog](CHANGELOG.md) and [v1.0.0 release notes](docs/releases/v1.0.0.md)
for supported contracts, upgrade instructions, and limitations.
