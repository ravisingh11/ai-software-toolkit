# Configure and read evidence

## Configure and run

The [onboarding guide](../quickstart.md#3-configure-repository-commands)
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

| Check | Adoption group | Mode | Result or next step |
| --- | --- | --- | --- |
| Unit tests | Selected checks | Advisory | Passed for the exact revision |
| Changed-code coverage | Selected checks | Advisory | Unable to verify; configure the coverage command |
| Deep SAST | Selected checks | Advisory | Unable to verify; analysis provenance unavailable |
| Functional QA | Tools available to adopt | — | Set up app-specific QA when useful |
| Container vulnerability | Checks relevant later | — | Select when an owned container artifact applies |

This example is **ORANGE / ALLOW**, with zero enforced controls. `ALLOW` means
the configured policy permits the evaluated snapshot; it does not mean all
checks passed or the application is ready to release. See the
[full illustrative report](../examples/sample-scorecard.md) and
[status guide](../proof/control-status.md).

Open the [toolkit scorecard](https://ravisingh11.github.io/ai-software-toolkit/)
or the [sample application's scorecard](https://ravisingh11.github.io/ai-software-toolkit-reference-app/)
to inspect actual evidence. Each page identifies its repository, evaluated
revision, and source CI run. Provider names link to configuration at that
revision; **Latest reported run** opens available evidence for that snapshot.
Provider selection is separate from successful execution.

The **All 33 checks** overview near the top links every built-in check to its
details, grouped as selected, available to adopt, or relevant later. Checks are
optional to adopt, and advanced lifecycle verification stays manual.

The [three adoption groups](../../README.md#choose-what-fits-your-project) follow the project's
evaluation stage. Only selected checks contribute to this evaluation's totals.

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
advisory. The [provider adoption guide](../providers/availability.md#selection-and-stage)
explains how to inspect the exact policy and execution evidence. Counts and run
results belong to the revision shown on the live page, not to this README.

Installed [agent skills](../../skills/README.md) are available playbooks. An agent
uses a relevant skill for a task; installing it does not execute it, schedule it,
or prove that functional QA or a release review happened. Keep skill-use reports
bound to the source and behavior actually reviewed. Hosted QA needs its own
configured executor and evidence producer.

A passing scanner check is not a claim of zero vulnerabilities. Finding counts,
when displayed, retain their reporting source. Missing credentials, skipped
producers, and unavailable analyses stay explicit. The
[evidence guide](../proof/control-setup.md#reading-scorecard-evidence)
explains the full contract.

### Separate SDLC checkpoint examples

The page places **PR created or updated** and **After merge** examples above
the latest detailed PR scorecard. Each has a separate check list, invocation,
tested revision, source run, and next decision. Their outcomes are never
combined with one another or with the live scorecard totals.

These are fixed historical examples from different changes. The toolkit PR example records
metadata, change-scope, coverage and dependency-review outcomes from
[Proof Scorecard run 40879663676](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/40879663676/attempts/1),
evaluating `2388c864ef72fd9f803ff6195a4395b5d7a5fd02`.
Its recorded metadata and size failures remain advisory findings.

The main example records activation/documentation regressions, archive build
and consumer verification from
[Distribution Acceptance run 40631525656](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/40631525656/attempts/1),
on `8a36b246f6bd0c3808276de0f7794b26f574ce5e`. These are workflow-step
observations, not an evaluation of all selected Proof checks or deployed health.

The [reference app report](https://ravisingh11.github.io/ai-software-toolkit-reference-app/)
selects its own examples: PR #63 at `510e25a6c8f4816a35ef9f2d4d1d00f2db74cab8`
from [run 40879661416](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/40879661416/attempts/1),
and main `c3df3f459f14dd4a9945f4988722ebaafc804edd` from
[Application acceptance 40632274819](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/40632274819/attempts/1).
The app's recorded missing changed-coverage result remains unverified, while
its separate main example shows build, unit/coverage, browser and migration steps.
Other repositories display the explicitly named toolkit teaching examples;
they never inherit those results as their own evidence.

Inspect the exact run metadata and raw receipts before updating the examples;
their independent source projections are retained in the renderer's hosted
regression fixtures. Source logs/artifacts remain subject to GitHub retention.
An unavailable historical receipt must not be reinterpreted as a new pass.
All checks stay optional, Core advisory, and lifecycle/polyglot manual.

### Scorecard freshness

The page checks for a newer publication on load, when returning to the tab, and
every 60 seconds while visible. A newer-snapshot notice offers **Refresh latest**,
which reloads the published report and preserves the selected section. Refresh
does not start CI or enable checks; existing results stay visible until refresh.

**Matches the latest published snapshot** refers to the site's publication,
not current `main`, the latest PR head, or the deployed application. If the
freshness check cannot be validated, it reports unknown. A workflow-success
badge and an evidence scorecard answer different questions. See
[freshness and badge setup](../quickstart.md#publish-the-optional-scorecard-badge).

## Independent provenance and Trivy

Attest published release files or run Trivy dependency, IaC, and image scans
without setting up deployment, ZAP, or soak testing. Start with the
[independent setup guide](../providers/independent-security.md). Checks remain
optional; advanced lifecycle verification stays manual.

## Optional quality checks

Choose tools, source scopes, thresholds, CI triggers, and policy modes that fit
your repository. The [quality recipes](../standards/optional-quality-checks.md)
provide runnable building blocks:

| Check | What it exercises |
| --- | --- |
| Real linting | Language-aware rules, separate from formatting and type checking |
| Test integrity | Fresh test reports, actual test cases, and selected skipped-test budgets |
| Defensive tests | Authorization, tenant/resource access, invalid input, and failure paths |
| Changed-code coverage | Fresh coverage reports compared with an explicit Git base and source scope |
| Architecture boundaries | Dependency direction, cycles, and imports across selected boundaries |

The [TypeScript recipe](../../examples/typescript-quality/README.md) uses TypeScript
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
[GitHub profile](../quickstart.md#2-add-the-optional-github-profile) adds
CodeQL, dependency review, secret protection, and Dependabot verification.
Choose providers and configure their real prerequisites; workflow files alone
do not prove activation or successful execution.

[GitHub CodeQL](../providers/codeql.md) supports advanced setup and an explicit
`github-codeql-default-setup` selection for GitHub-managed setup. The latter
verifies configuration, managed workflow identity, exact revision, and analyses
for all configured languages. Missing permissions or unverifiable analyses
remain unverified. CodeQL languages are separate from the five polyglot examples.

[Optional lifecycle providers](../providers/lifecycle.md) produce IaC,
container, SBOM, artifact provenance/vulnerability, deployment-policy, DAST,
runtime, and short soak evidence for immutable artifacts and verification
environments. They require explicit selection, configuration, and trusted
collection. Verification fixtures do not attest production deployment or stability.

For optional Snyk jobs you leave disabled, set the corresponding
`SNYK_CODE_ENABLED=false` or `SNYK_OPEN_SOURCE_ENABLED=false` variable explicitly.
Collection skips waiting for their absent checks while retaining selected
missing evidence as **no result**. Running jobs still wait. See
[Snyk setup](../providers/snyk.md) and the
[provider inventory](../providers/availability.md) for requirements and limits.

Each repository decides whether to adopt or enforce a check. If you choose to
require one, first verify its producer, stable check name, failure behavior,
exact-subject evidence, and remediation owner. Policy modes and GitHub branch
rules are separate settings; AI review stays advisory-only.
