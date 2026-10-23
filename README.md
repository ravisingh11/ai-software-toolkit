# AI Software Toolkit

**AI is the accelerant. Assurance is mandatory.**

Turn directives into reviewed changes with clear boundaries and evidence for
what actually ran. AI Software Toolkit combines engineering standards, agent
skills, and **Proof**, which binds check results to the evaluated revision.
Your repository owns its commands, acceptance criteria, and release decisions.

[![Version](https://img.shields.io/github/v/release/ravisingh11/ai-software-toolkit?label=version)](https://github.com/ravisingh11/ai-software-toolkit/releases/latest)
[![License](https://img.shields.io/github/license/ravisingh11/ai-software-toolkit?label=license)](LICENSE)
[![Latest PR Scorecard](https://ravisingh11.github.io/ai-software-toolkit/proof-badge.svg)](https://ravisingh11.github.io/ai-software-toolkit/)

**All checks are optional to adopt.** Core selects 12 advisory checks. Installing
files, selecting a check, configuring it, executing it, and obtaining passing
evidence are distinct steps. Installation does not enforce checks or change
branch protection. Advanced lifecycle and polyglot execution stay manual.

## Start here

Use Git, Python 3.11+, and a POSIX shell. Preview a Proof-only installation from
the published release before applying it to your application repository:

```sh
git clone --branch v2.3.0 --depth 1 https://github.com/ravisingh11/ai-software-toolkit.git
cd ai-software-toolkit
python3 tooling/ai_toolkit discover --target /path/to/your-repo
python3 tooling/ai_toolkit init --target /path/to/your-repo --components proof --preview
python3 tooling/ai_toolkit init --target /path/to/your-repo --components proof --yes
python3 tooling/ai_toolkit doctor --target /path/to/your-repo
```

Replace the target path with your repository. Discovery, preview, and doctor
are read-only; doctor does not run producers. Configure your real commands
before executing checks. Code on `main` may be newer than the published release.

[Onboarding](docs/quickstart.md) covers local and CI setup. The
[installation guide](docs/install.md) covers component selection, runtime-only
installs, updates, ownership, and rollback. The
[activation index](docs/activation.md) covers **all 33 checks**, including
prerequisites, execution, evidence, disabling, and optional enforcement.

In v2.3.0, fresh installations default to
`--install-set starter`: Proof, seven starter skills, and 11 Core workflows
covering all 12 advisory Core checks. Existing installations keep their prior
behavior. See [starter and full installation sets](docs/install.md#fresh-starter-installation-v230).

## What you can use

| Component | Purpose | Guide |
| --- | --- | --- |
| Proof | Revision-bound results and readable scorecards | [Runtime and evidence](docs/proof/README.md) |
| Skills | Controlled planning, implementation, review, and release procedures | [Skill catalog and installation](skills/README.md) |
| Functional QA | App-specific acceptance criteria and behavioral exploration | [QA bootstrap](skills/qa-bootstrap/SKILL.md) |
| Providers | Repository commands, GitHub checks, and optional scanners | [Provider setup](docs/providers/README.md) |
| Standards | Human-readable engineering expectations | [Standards index](docs/standards/README.md) |
| Specification-driven development | Durable intent, plans, and acceptance evidence using your chosen tools | [Standard and optional Spec Kit integration](docs/standards/spec-driven-development-standard.md) |

<a id="use-with-claude-code"></a>

For Claude Code, use `--components skills --clients claude-code --skills starter`;
for Codex, use `--clients codex`. The same canonical skills populate the selected
client's project directory. Installing a skill does not execute it. See
[client setup](docs/quickstart.md#claude-code-setup) and
[replacement safety](docs/install.md#installing-and-verifying-action-skills).

## Choose what fits your project

| Group | Meaning | Counts toward this evaluation? |
| --- | --- | --- |
| Selected checks | Policy selects the check for the evaluation stage | Yes, when applicable, including failures and unverifiable results |
| Tools available to adopt | Unselected checks useful at this stage | No |
| Checks relevant later | Unselected release or runtime checks | No |

Keep the [33-check activation index](docs/activation.md) available as you adopt
more checks. Provider selection does not prove configuration or execution.
[Independent provenance and Trivy](docs/providers/independent-security.md) can
be adopted separately from advanced lifecycle verification.

<a id="recorded-live-verification-and-cleanup-2026-10-19"></a>

## Read the scorecard

Illustrative evidence for one revision:

| Selected check | Mode | Result |
| --- | --- | --- |
| Unit tests | Advisory | Passed for the evaluated revision |
| Build | Advisory | Failed; inspect the producer log |
| Changed-code coverage | Advisory | Unable to verify; command missing |

Failed, blocked, unverified, and inactive checks remain separate. Missing
credentials, stale evidence, or skipped/manual producers never become a pass.
Only selected, applicable checks affect scores. **Advisory / Enforced** is a
separate choice; `ALLOW` means policy permits that snapshot, not release readiness.
GitHub required merge checks are configured separately.

Inspect the [live toolkit scorecard](https://ravisingh11.github.io/ai-software-toolkit/),
[full illustrative report](docs/examples/sample-scorecard.md), and
[reading evidence guide](docs/proof/reading-evidence.md) for revision binding,
freshness, result states, and provider limitations. Historical verification
records remain in the [provider ledger](docs/providers/verification.md).
The [v2.3.0 compatibility review](docs/releases/v2.3.0-compatibility.md) explains
hosted verification against the published CLI and its limits.

## See it in an application

[Fieldnotes](https://github.com/ravisingh11/ai-software-toolkit-reference-app) is a
TypeScript issue tracker with a [running application](https://ai-software-toolkit-reference-app.navivision-account.workers.dev/),
[live scorecard](https://ravisingh11.github.io/ai-software-toolkit-reference-app/), and
[setup and evidence guide](https://github.com/ravisingh11/ai-software-toolkit-reference-app/blob/main/docs/verification/README.md).
Its [five polyglot quality examples](https://github.com/ravisingh11/ai-software-toolkit-reference-app/tree/main/examples/polyglot)
run manually and do not establish full-application coverage. An
[isolated Python demo](examples/python-demo/README.md) is included here.

<a id="optional-quality-checks"></a>

Choose language tools and thresholds through the
[optional quality recipes](docs/standards/optional-quality-checks.md).

## Repository map

| Path | Purpose |
| --- | --- |
| `policies/` | Check catalog, profiles, providers, engineering policy |
| `proof/`, `tooling/` | Evaluation, installation, producers, validators |
| `workflows/`, `rulesets/` | Optional workflow and enforcement templates |
| `skills/`, `pr-review/`, `prompts/`, `templates/` | Agent procedures and review contracts |
| `security/`, `examples/` | Scanner rules, fixtures, example consumers |
| `docs/` | Onboarding and operating guides |
| `.proof/`, `.github/workflows/`, `.agents/` | This repository's installed runtime and CI |

[Documentation](docs/README.md) explains source ownership and intentional installed
copies. See [contributing](CONTRIBUTING.md), [validation](AGENTS.md#verification),
[vision](docs/vision.md), and [licensing](docs/licensing.md). MIT licensed;
third-party tools retain their own terms.
