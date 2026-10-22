# AI Software Toolkit

**AI is the accelerant. Assurance is mandatory.**

AI turns directives into code faster than ever. That speed makes clear
boundaries, human review, and verifiable results essential. Build assurance
into the work before changes ship.

**Your directives. Disciplined execution. Evidence before release.**

AI Software Toolkit provides the foundation for that assurance across
human-led and agent-driven software delivery:

- **Standards** define expectations and safe boundaries.
- **Agent skills** guide controlled planning, implementation, review, and release.
- **Functional QA and deterministic checks** produce repeatable observations.
- **Proof** binds results to the evaluated revision and makes failures and
  missing evidence visible in readable scorecards.

Start with your highest-risk change. Define the outcome, choose the checks,
run them, and inspect the evidence before you ship. Your repository owns its
architecture, acceptance criteria, tools, commands, and release decisions.

**All toolkit checks are optional to adopt.** Choose which checks run, their
thresholds, and whether to enforce them. Installing the toolkit does not run
checks, make them required, or change branch protection. Language examples
are starting points to adapt or replace.

I built this because AI accelerated what I could ship. I needed assurance to
keep pace: explicit standards, controlled procedures, and evidence from the
first acceptance criterion through release and feedback.

[![Version](https://img.shields.io/github/v/release/ravisingh11/ai-software-toolkit?label=version)](https://github.com/ravisingh11/ai-software-toolkit/releases/latest)
[![License](https://img.shields.io/github/license/ravisingh11/ai-software-toolkit?label=license)](LICENSE)
[![Scorecard Workflow](https://github.com/ravisingh11/ai-software-toolkit/actions/workflows/proof-scorecard.yml/badge.svg?event=pull_request_target)](https://github.com/ravisingh11/ai-software-toolkit/actions/workflows/proof-scorecard.yml)
[![Latest PR Scorecard](https://ravisingh11.github.io/ai-software-toolkit/proof-badge.svg)](https://ravisingh11.github.io/ai-software-toolkit/)

## See it in a sample application

[**Fieldnotes — sample application repository**](https://github.com/ravisingh11/ai-software-toolkit-reference-app)
shows the toolkit in a working TypeScript issue tracker.

- [Open the application](https://ai-software-toolkit-reference-app.navivision-account.workers.dev/)
- [Read its live PR scorecard](https://ravisingh11.github.io/ai-software-toolkit-reference-app/)
- [Explore the app's setup and evidence guide](https://github.com/ravisingh11/ai-software-toolkit-reference-app/blob/main/docs/verification/README.md)
- [Try its Java, TypeScript, Python, PHP, and Scala quality examples](https://github.com/ravisingh11/ai-software-toolkit-reference-app/tree/main/examples/polyglot)

The deployed application is TypeScript; the other languages are independent
quality examples. Their polyglot workflow is **manual (`workflow_dispatch`) and
optional**, with an explicit comparison base and repository-selected threshold.
Example results do not establish full-application coverage or deployment readiness.

## What you can use

| Component | Purpose | Start here |
| --- | --- | --- |
| Skills | Repeatable development, review, security, and release tasks | [Install shared skills](skills/README.md#install-locally) |
| Functional QA | Acceptance criteria, browser/API exploration, and failure-path verification | [Set up QA](skills/qa-bootstrap/SKILL.md) |
| Quality recipes | Linting, test integrity, defensive tests, changed-code coverage, and architecture boundaries | [Optional quality checks](#optional-quality-checks) |
| Proof | Bind results to their source revision and expose missing evidence | [Onboarding guide](docs/quickstart.md) |
| Providers | Connect repository commands, GitHub checks, and optional scanners | [Provider setup](docs/providers/README.md) |
| Standards | Expectations for quality, security, and accountable AI use | [AI development policy](policies/ai-development.md) |

Use components independently. QA helps shape acceptance criteria and risk
coverage, explores behavior, and feeds failures back into future validation.
See the [toolkit vision](docs/vision.md) for the wider delivery lifecycle.

## Start here

Use Git, **Python 3.11+**, and a POSIX shell. Start from a reviewed toolkit
checkout and an existing application repository:

```sh
git clone https://github.com/ravisingh11/ai-software-toolkit.git
cd ai-software-toolkit
python3 tooling/ai_toolkit discover --target /path/to/your-repo
python3 tooling/ai_toolkit init --target /path/to/your-repo --components proof --preview
```

Discovery and preview do not write files. Review the proposed files and commands,
then apply the same selection:

```sh
python3 tooling/ai_toolkit init --target /path/to/your-repo --components proof --yes
python3 tooling/ai_toolkit doctor --target /path/to/your-repo
```

Replace `/path/to/your-repo` with your repository's path. `doctor` inspects setup;
it does not execute checks or prove they passed. Configure real repository
commands and review the installed policy before running a scan.

Follow the [onboarding guide](docs/quickstart.md) for command configuration,
ground-truth documents, GitHub setup, and your first PR. The
[CLI guide](docs/install.md) covers skills, QA, runtime-only installs, updates,
and managed-file ownership.

<a id="use-with-claude-code"></a>

### Install skills for Codex or Claude Code

For Claude Code, install the starter skills into your application's
`.claude/skills/` directory. From this toolkit checkout, preview first, then apply:

```sh
python3 tooling/ai_toolkit init --target /path/to/your-repo --components skills --clients claude-code --skills starter --preview
python3 tooling/ai_toolkit init --target /path/to/your-repo --components skills --clients claude-code --skills starter --yes
```

This skills-only selection does not install Proof workflows or run checks.
Use `--clients codex,claude-code` if you use both clients; they share the same
canonical skills in their respective project directories. For Codex alone, use
`--clients codex`; its project destination is `.agents/skills/`.

The separate [`tooling/install-skills.sh`](skills/README.md#install-locally)
installer copies selected skills and their shared helpers into your client
skills directory. It does not install package dependencies, run the copied
helpers, or install Proof workflows. Review replacement behavior and recovery
limits in the [installation guide](docs/install.md#installing-and-verifying-action-skills).

In Claude Code, ask: “Use the code-review skill to review this change. Explain
risks with file references. Do not run tests or commands unless I ask.” Keep
repository-specific instructions and execution limits in your own `CLAUDE.md`;
the installer does not write that file. Skills provide guidance, while Proof
collects execution evidence. Installing a skill is not a passing check.

See [Claude Code onboarding](docs/quickstart.md#claude-code-setup) for adding
Proof or QA separately. All checks remain optional.

### Try an isolated Python demo

From the toolkit checkout, copy the embedded demo into a separate directory.
No account, token, paid service, or Docker is required to get a report:

```sh
demo_workspace="$(mktemp -d)"
cp -R examples/python-demo/. "$demo_workspace/"
cd "$demo_workspace"
git init -q
git add .
git -c user.name='Toolkit Demo' -c user.email='demo@example.invalid' commit -qm 'chore: initialize toolkit demo'
python3 tools/run_proof.py
```

The helper supplies real Python build and unit-test commands. Reports appear
under `.artifacts/proof/`. Missing scanner tools, command configuration, and
GitHub-only evidence remain visible as **no result**. Scope and documentation
comparison checks need a parent commit, so an initial-commit demo can have
advisory gaps. The demo does not push anything.

## Configure and run

The [onboarding guide](docs/quickstart.md#3-configure-repository-commands)
explains `PROOF_BUILD_COMMAND`, `PROOF_UNIT_TEST_COMMAND`, and other command
variables. Use your application's real commands; do not substitute demo
commands or no-ops. Map your existing architecture, testing, security, and
deployment documents in `.proof/ground-truth-ai.yaml`.

Review and commit the installation and configuration before scanning. Run from
the consumer repository:

```sh
python3 .proof/configure.py --list
python3 .proof/doctor.py
python3 .proof/scan.py
```

Local evidence binds to a clean, committed `HEAD`. A dirty worktree produces
no-result evidence instead of claiming a pass for the commit. Read the generated
Markdown and JSON, fix actual failures, and verify independent producers on a PR.

<a id="recorded-live-verification-and-cleanup-2026-10-19"></a>

## Read the scorecard

An **illustrative example**, not a live scan:

| Check | Provider | Mode | Evidence |
| --- | --- | --- | --- |
| Unit tests | Repository Unit Test Command | Advisory | Passed for the exact revision |
| Changed-code coverage | Repository Changed Code Coverage Command | Advisory | No result; command not configured |
| Deep SAST | GitHub CodeQL default setup | Advisory | No result; analysis provenance unavailable |
| Container vulnerability | Trivy Container Image | Advisory | Failed; findings remain visible |
| Artifact provenance | Not configured | Not activated | Excluded from selected totals |

This example is **ORANGE / ALLOW**, with zero enforced controls. `ALLOW` means
the configured policy permits the evaluated snapshot; it does not mean all
checks passed or the application is ready to release. See the
[full illustrative report](docs/examples/sample-scorecard.md) and
[status guide](docs/proof/control-status.md).

Open the [toolkit scorecard](https://ravisingh11.github.io/ai-software-toolkit/)
or the [sample application's scorecard](https://ravisingh11.github.io/ai-software-toolkit-reference-app/)
to inspect actual evidence. Each page identifies its repository, evaluated
revision, and source CI run. Provider names link to configuration at that
revision; **Latest reported run** opens available evidence for that snapshot.
Provider selection is separate from successful execution.

The scorecard groups tools by the project's evaluation stage:

| Group | Meaning | Included in the score? |
| --- | --- | --- |
| **Selected checks** | Checks chosen by this project's policy for the evaluated stage | Yes, including failed or unverifiable results |
| **Tools available to adopt** | Unselected tools that can help at the current stage | No |
| **Checks relevant later** | Unselected checks for a later release or runtime stage | No |

Selection does not prove execution. Each selected check shows its actual result:
**Passed**, **Failed**, **Blocked**, or **Unable to verify**. Setup information
separately explains missing configuration, disabled providers, and manual runs
that have not happened. Zero result counts are hidden. Missing evidence never
counts as a pass; an empty enforced selection says **No checks enforced**.

**Advisory / Enforced** is a separate policy choice. Advisory findings remain
visible without blocking the toolkit decision. Enforced checks must pass;
failed, blocked, or unverifiable evidence prevents that decision from allowing
progress. GitHub's required merge checks are configured separately.

The toolkit repository currently selects its Core/GitHub development checks as
advisory. The [provider adoption guide](docs/providers/availability.md#selection-and-stage)
explains how to inspect the exact policy and execution evidence. Counts and run
results belong to the revision shown on the live page, not to this README.

Installed [agent skills](skills/README.md) are available playbooks. An agent
uses a relevant skill for a task; installing it does not execute it, schedule it,
or prove that functional QA or a release review happened. Keep skill-use reports
bound to the source and behavior actually reviewed. Hosted QA needs its own
configured executor and evidence producer.

A passing scanner check is not a claim of zero vulnerabilities. Finding counts,
when displayed, retain their reporting source. Missing credentials, skipped
producers, and unavailable analyses stay explicit. The
[evidence guide](docs/proof/control-setup.md#reading-scorecard-evidence)
explains the full contract.

### Scorecard freshness

The page checks for a newer publication on load, when returning to the tab, and
every 60 seconds while visible. A newer-snapshot notice offers **Refresh latest**,
which reloads the published report and preserves the selected section. Refresh
does not start CI or enable checks; existing results stay visible until refresh.

**Matches the latest published snapshot** refers to the site's publication,
not current `main`, the latest PR head, or the deployed application. If the
freshness check cannot be validated, it reports unknown. A workflow-success
badge and an evidence scorecard answer different questions. See
[freshness and badge setup](docs/quickstart.md#publish-the-optional-scorecard-badge).

## Independent provenance and Trivy

Attest published release files or run Trivy dependency, IaC, and image scans
without setting up deployment, ZAP, or soak testing. Start with the
[independent setup guide](docs/providers/independent-security.md). Checks remain
optional; advanced lifecycle verification stays manual.

## Optional quality checks

Choose tools, source scopes, thresholds, CI triggers, and policy modes that fit
your repository. The [quality recipes](docs/standards/optional-quality-checks.md)
provide runnable building blocks:

| Check | What it exercises |
| --- | --- |
| Real linting | Language-aware rules, separate from formatting and type checking |
| Test integrity | Fresh test reports, actual test cases, and selected skipped-test budgets |
| Defensive tests | Authorization, tenant/resource access, invalid input, and failure paths |
| Changed-code coverage | Fresh coverage reports compared with an explicit Git base and source scope |
| Architecture boundaries | Dependency direction, cycles, and imports across selected boundaries |

The [TypeScript recipe](examples/typescript-quality/README.md) uses TypeScript
tools. Other languages need their own implementations. The sample app's
[polyglot examples](https://github.com/ravisingh11/ai-software-toolkit-reference-app/blob/main/examples/polyglot/README.md)
show these choices:

| Language | Lint/static analysis | Coverage | Architecture |
| --- | --- | --- | --- |
| Java | Checkstyle | JaCoCo | `jdeps` |
| TypeScript | Type-aware ESLint | c8/V8 | dependency-cruiser |
| Python | Ruff | coverage.py | Conservative AST purity rules |
| PHP | PHPStan | Xdebug | Conservative token-based purity rules |
| Scala | WartRemover | JaCoCo | `jdeps` |

Their [optional workflow](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/workflows/polyglot-examples.yml)
runs only when manually dispatched. It does not run on pushes or PRs and is not
a required merge check. An unchanged comparison can yield **not applicable**
coverage; that is not a new coverage measurement or a substitute for missing
application coverage.

## Profiles and providers

Core selects advisory repository/documentation validation, ground truth, PR
scope and metadata, lint, migration validation, build, tests, changed-code
coverage, Semgrep CE, and Gitleaks CLI. The optional
[GitHub profile](docs/quickstart.md#2-add-the-optional-github-profile) adds
CodeQL, dependency review, secret protection, and Dependabot verification.
Choose providers and configure their real prerequisites; workflow files alone
do not prove activation or successful execution.

[GitHub CodeQL](docs/providers/codeql.md) supports advanced setup and an explicit
`github-codeql-default-setup` selection for GitHub-managed setup. The latter
verifies configuration, managed workflow identity, exact revision, and analyses
for all configured languages. Missing permissions or unverifiable analyses
remain unverified. CodeQL languages are separate from the five polyglot examples.

[Optional lifecycle providers](docs/providers/lifecycle.md) produce IaC,
container, SBOM, artifact provenance/vulnerability, deployment-policy, DAST,
runtime, and short soak evidence for immutable artifacts and verification
environments. They require explicit selection, configuration, and trusted
collection. Verification fixtures do not attest production deployment or stability.

For optional Snyk jobs you leave disabled, set the corresponding
`SNYK_CODE_ENABLED=false` or `SNYK_OPEN_SOURCE_ENABLED=false` variable explicitly.
Collection skips waiting for their absent checks while retaining selected
missing evidence as **no result**. Running jobs still wait. See
[Snyk setup](docs/providers/snyk.md) and the
[provider inventory](docs/providers/availability.md) for requirements and limits.

Each repository decides whether to adopt or enforce a check. If you choose to
require one, first verify its producer, stable check name, failure behavior,
exact-subject evidence, and remediation owner. Policy modes and GitHub branch
rules are separate settings; AI review stays advisory-only.

## Repository map

| Path | Purpose |
| --- | --- |
| `policies/` | Capabilities, profiles, providers, and engineering policy |
| `proof/`, `tooling/` | Evaluator, installer, producers, and validators |
| `workflows/`, `rulesets/` | Workflow and optional enforcement templates |
| `skills/` | Reusable agent instructions |
| `pr-review/`, `prompts/`, `templates/` | Review contracts and reusable guidance |
| `security/` | Scanner rules and fixtures |
| `examples/` | Runnable consumers and quality recipes |
| `docs/` | Onboarding, provider setup, and operating guides |
| `.proof/`, `.github/workflows/`, `.agents/` | This repository's installed toolkit and CI |

See the [documentation index](docs/README.md), [self-check guide](docs/self-check.md),
and [source ownership guide](docs/README.md#source-ownership-and-installed-copies)
for working on the toolkit itself.

## License and validation

MIT licensed; third-party tools keep their own terms. See [licensing](docs/licensing.md),
[contributing](CONTRIBUTING.md), and the [validation commands](AGENTS.md#verification).
