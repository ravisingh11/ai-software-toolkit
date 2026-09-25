# Guardrails v2 quick start

This guide installs the Guardrails component of [AI Software Toolkit](vision.md).
For other entry points, [install skills](../skills/README.md#install-locally)
or [set up functional QA](../skills/qa-bootstrap/SKILL.md) from a source revision
containing those capabilities.

Install Core, configure repository commands, run locally, and then verify the
same capability providers on a pull request.

For a copyable, isolated first run, start with the
[release-pinned Python demo](../README.md#start-here). It clones v1.0.0,
refreshes the embedded installation, configures real build/test commands,
commits the demo, and scans it. Git, Python 3.11+, and a POSIX shell are the
prerequisites. Docker and GitHub credentials are optional; missing providers
produce no result, not a pass. “v2” is the runtime and evidence contract;
v1.0.0 is the repository release version.

The numbered steps below adapt that flow to **your own repository**. Use its
real commands and ground-truth documents, not the demo's paths.

## 1. Preview and install Core

Clone the released source, then run the installer from that checkout:

```sh
git clone --branch v1.0.0 https://github.com/ravisingh11/ai-software-toolkit.git
cd ai-software-toolkit
python3 tooling/install.py --target /path/to/repo --dry-run
python3 tooling/install.py --target /path/to/repo
```

Replace `/path/to/repo` with an existing consumer directory. Installation writes
files there; it does not configure GitHub settings or prove any check passed.
For an existing v2 installation, preview and use `--refresh-existing` instead
of a plain install. Refresh updates distributed runtime and installer-owned
workflows while preserving repository policy, documentation/ground-truth
mappings, scope/metadata settings, and consumer-owned workflows. Review the
diff before committing; provider definitions are refreshed while retaining
repository-specific trusted paths.

A normal install includes the Core runtime and Core GitHub Actions. To install
only the runtime, use:

```sh
python3 tooling/install.py --target /path/to/repo --no-actions
```

To add validated local pre-commit hooks, first install `pre-commit`, then run:

```sh
python3 tooling/install.py --target /path/to/repo --local-hooks
```

The installer refuses to overwrite an existing pre-commit configuration.

## 2. Add the optional GitHub profile

For a fresh install:

```sh
python3 tooling/install.py --target /path/to/repo --profile github
```

For an existing v2 installation:

```sh
python3 tooling/install.py --target /path/to/repo --profile github --merge-existing --dry-run
python3 tooling/install.py --target /path/to/repo --profile github --merge-existing
```

Core remains selected. The GitHub profile is an additive advisory overlay.

## 3. Configure repository commands

This verified example matches the embedded Python demo:

```sh
export GUARDRAILS_BUILD_COMMAND='python3 -m compileall -q app.py test_app.py tools .guardrails'
export GUARDRAILS_UNIT_TEST_COMMAND="python3 -m unittest discover -s . -p 'test_*.py'"
export GUARDRAILS_WORKING_DIRECTORY='.'
```

Use the same names as GitHub Actions repository variables. Configure
`GUARDRAILS_SETUP_COMMAND`, `GUARDRAILS_CHANGED_COVERAGE_COMMAND`,
`GUARDRAILS_FORMAT_LINT_COMMAND`, and `GUARDRAILS_MIGRATION_VALIDATION_COMMAND`
only when the repository has real commands for those capabilities. Unset build,
test, or coverage commands produce `NO RESULT` rather than pass. The installed
format/lint and migration Actions jobs fail visibly when their command is absent;
local scans represent the same absence as `NO RESULT`.
`GUARDRAILS_WORKING_DIRECTORY` must resolve inside the repository.

Before opening the first pull request, configure real format/lint and migration
commands for any installed workflows you intend to run. Do not use a no-op or
an unrelated validation command: a green check must prove its named capability.

## 4. Declare repository ground truth

Edit `.guardrails/ground-truth-ai.yaml` so each entry names an existing path:

```json
{
  "version": 1,
  "documents": [
    {"path": "README.md"},
    {"path": "docs/architecture/system.md"},
    {"path": "handbook/testing.md"}
  ]
}
```

The paths are repository-relative and configurable. Root-level conventional
filenames are not required.

## 5. Inspect policy and run

Run from the consumer repository, not the standards checkout. Review and commit
the installation/configuration with your normal Git workflow **before** the
scan. A new repository also needs `git init` and its initial commit; the
[demo walkthrough](../README.md#start-here) includes both.

```sh
python3 .guardrails/configure.py --list
python3 .guardrails/scan.py --help
python3 .guardrails/configure.py --help
python3 .guardrails/scan.py
```

The scan requires a clean worktree for passing local evidence and binds evidence
to the resolved full `HEAD`. A dirty worktree yields no-result evidence; a
repository without a commit cannot resolve `HEAD`. It writes:

```text
.artifacts/guardrails/evidence-YYYYMMDD-HHMMSSZ.json
.artifacts/guardrails/evidence.json
.artifacts/guardrails/scorecard-YYYYMMDD-HHMMSSZ.md
```

The default scorecard omits inactive and `evidence-only` controls. Use
`python3 .guardrails/scan.py --all-catalog-controls` to inspect the complete
catalog with those controls shown as `GRAY` / `not_activated`.

Release policy can activate controls for more than one evidence subject. Select
one immutable subject contract per invocation instead of combining commit and
artifact evidence:

```sh
python3 .guardrails/scan.py --operation release --subject-type git-commit
python3 .guardrails/scan.py --operation release --subject-type artifact \
  --revision 'sha256:<artifact-digest>'
```

If more than one subject applies and `--subject-type` is omitted, the scanner
stops with a configuration error rather than silently omitting controls.

Core uses the pinned Semgrep CE and Gitleaks CLI containers when Docker is
available. Otherwise it accepts only host Semgrep `1.175.0` and Gitleaks
`8.30.1`. Missing Docker, unavailable tools, a shallow history, or a version
mismatch produces `NO RESULT`.

### First-run troubleshooting

- **No HEAD / no commit:** commit the reviewed installation before scanning.
- **First commit only:** documentation-change and scope checks need the default
  base `HEAD~1`; they report no result until a real parent commit exists.
- **Dirty worktree:** review `git status --short`, then commit intended changes.
  Do not discard unrelated work just to get a clean scan.
- **Build/tests/coverage have no result:** export the real command variables in
  this shell. Setting GitHub repository variables does not populate your local
  environment, and a configured command is not proof it passed.
- **Scanner tools unavailable:** install the pinned tools or a working Docker
  runtime if you want their evidence. Do not replace a security scan with a no-op.
- **Semgrep cannot find its rules inside Docker:** verify the daemon can mount
  the consumer directory, including `.guardrails/semgrep-rules.yml`; inspect
  that path inside the container before attributing the failure to a mount.
- **GitHub checks absent locally:** verify the supported producers on a real PR.
  An advisory `ORANGE / ALLOW` result is not an all-checks-passed result.

<a id="diagnose-installation-planned-v030"></a>
<a id="diagnose-installation-unreleased-v030"></a>

## Diagnose installation

The v1.0.0 installer distributes `.guardrails/doctor.py` with the runtime,
including runtime-only installs. Refreshing an existing v2 installation adds
it. Run these commands from the installed consumer repository:

```sh
python3 .guardrails/doctor.py
python3 .guardrails/doctor.py --target /path/to/repo
python3 .guardrails/doctor.py --target /path/to/repo --json
python3 .guardrails/doctor.py --github OWNER/REPO
python3 .guardrails/doctor.py --operation release
```

`--target` defaults to the current working directory; `--operation change|release`
defaults to `change`. `--json` selects
machine-readable diagnostics. Optional `--github OWNER/REPO` uses the locally
authenticated `gh` CLI for read-only API metadata probes; without it, diagnosis
is local. Probes cover repository-level Actions variables and secret names,
plus secret-scanning/push-protection settings when the secret-protection
provider is selected. Inherited organization/environment variables and secrets
are not queried. Secret values, token validity, token permissions, and actual
workflow availability are not verified.

Endpoint scope and access requirements are documented by GitHub:
[repository secrets](https://docs.github.com/en/rest/actions/secrets#list-repository-secrets),
[repository variables](https://docs.github.com/en/rest/actions/variables#list-repository-variables),
and [repository metadata](https://docs.github.com/en/rest/repos/repos#get-a-repository).

| Setup state | Meaning |
| --- | --- |
| `configured` | The inspected configuration or prerequisite is present; execution is not verified. |
| `action_needed` | An actionable setup gap was found, including invalid installed configuration. |
| `unverified` | The available checks cannot establish readiness; absence from repository-level metadata does not rule out inherited settings. |

Exit codes: **1** means actionable setup gaps, including readable but invalid
installed configuration; **0** means none were found (the report can still
contain `unverified` items); **2** means invalid CLI arguments, a nonexistent
target, or failure to load a required runtime helper. Exit 0 is not an
all-controls-passed result.

If a required helper is missing or cannot be imported (including syntax damage),
doctor reports its filename and exits 2 without a traceback; refresh the trusted
installation. `GUARDRAILS_WORKING_DIRECTORY` is trimmed like the scanner's value,
and an empty or whitespace-only value selects the repository root.
Helper exits are handled as load failures, but user interrupts still propagate.

Doctor must not run scans, execute configured repository commands, install
tools, or mutate files, policy, GitHub settings, or secrets. A local
**configured** result means configuration was found, not that a check ran or
passed. GitHub metadata also does not prove an exact-head provider pass.
Continue to use the scanner and trusted PR workflows for execution evidence.
See the [release notes](releases/v1.0.0.md#upgrade-from-v020) for upgrade constraints.

Git inspection disables hooks, fsmonitor, and filters and does not recurse into
submodules. An otherwise clean checkout with `.gitmodules` remains `unverified`;
filtered files may appear dirty with filters disabled. Before scanning, review
`git status` in a trust-reviewed checkout, including its filters and submodules;
do not discard changes merely to clear a diagnostic.

## 6. Configure the GitHub overlay

If the GitHub profile is selected, configure only applicable repository
variables:

```text
GUARDRAILS_CODEQL_LANGUAGES
GUARDRAILS_DEPENDENCY_REVIEW_ENABLED=true
GUARDRAILS_ARTIFACT_BUILD_COMMAND
GUARDRAILS_ARTIFACT_PATH
```

`GUARDRAILS_CODEQL_LANGUAGES` is the CodeQL language list. Artifact variables
apply to release/workflow-dispatch provenance, not PR commit evidence.

The optional `SECURITY_SETTINGS_TOKEN` is used only by trusted, no-checkout
`pull_request_target` setting probes for GitHub Secret Protection and
Dependabot. It needs repository Administration read and Secret scanning alerts
read access. Missing or insufficient access publishes `NO RESULT`.
Dependabot's version `2022-11-28` API response must be valid JSON with boolean
`enabled: true` and `paused: false`. Empty, malformed, or incomplete successful
responses publish `NO RESULT`; a `404` means automated security fixes are
disabled.

## 7. Open a pull request

```text
local scan -> push branch -> provider workflows -> exact-head collector
           -> Guardrail Scorecard -> review -> merge
```

Provider workflows run independently. The scorecard collector reads only the
selected authoritative and supplemental check contracts and verifies their
workflow provenance for the exact PR head. Native workflow providers may also
declare `trusted_paths` for validator code, rule packs, and fixtures that define
the result. The workflow definition and every declared path must have the same
Git blob at the PR head and trusted base; otherwise the result is `NO RESULT`.
If a configured repository command delegates to a tracked helper, add that
helper to the check's `trusted_paths`. Refreshes retain repository-specific
trusted-path additions while restoring the canonical provider contract.

Core also installs `PR Change Scope`. Base-owned validator code compares the
exact PR base and head without executing candidate code. The default policy
measures meaningful source changes against 300 added and 500 changed lines,
while still showing excluded documentation, lockfile, generated, and vendor
volume in total metrics. An oversized advisory PR produces a neutral provider
check and `ORANGE / ALLOW`; promotion to `enforced` changes the provider check
to failure.

## 8. Promote one proven capability

Keep all capabilities advisory while tuning. After a provider has a stable
check name, reliable exact-subject evidence, and a remediation owner:

```sh
python3 .guardrails/configure.py --set unit-tests=enforced --dry-run
python3 .guardrails/configure.py --set unit-tests=enforced
```

Then add the observed check context to the repository ruleset. Policy mode and
GitHub branch protection are separate changes; both are required for a merge
gate.

## Publish the optional scorecard badge

The v1.0.0 installer supports the optional publisher. Run the installation
commands below from the released standards checkout, not the consumer.

GitHub's native **Scorecard Workflow** badge reports whether the workflow ran
successfully. The optional **Latest PR Scorecard** badge reports the newest
accepted PR readiness and passed/active count. A successful workflow may still
publish `ORANGE / ALLOW`; the latest PR result does not attest current `main`.
The native URL's `event=pull_request_target` filter selects PR executions and
avoids the default-branch fallback showing `no status`.

For a clean installation:

```sh
python3 tooling/install.py --target /path/to/repo --scorecard-badge --dry-run
python3 tooling/install.py --target /path/to/repo --scorecard-badge
```

For an existing installation:

```sh
python3 tooling/install.py --target /path/to/existing-repo --refresh-existing --scorecard-badge --dry-run
python3 tooling/install.py --target /path/to/existing-repo --refresh-existing --scorecard-badge
```

To remove only the installer-owned publisher files:

```sh
python3 tooling/install.py --target /path/to/existing-repo --refresh-existing --remove-scorecard-badge --dry-run
python3 tooling/install.py --target /path/to/existing-repo --refresh-existing --remove-scorecard-badge
```

In repository settings, select **Pages → Build and deployment → GitHub
Actions**. Then create:

```text
GUARDRAILS_SCORECARD_BADGE_ENABLED=true
GUARDRAILS_SCORECARD_BADGE_PAGES_MODE=dedicated
```

No PAT or repository secret is required. The workflow uses the scoped
`GITHUB_TOKEN`. `dedicated` means the publisher owns the complete Pages site;
do not enable it when another Pages workflow already owns that deployment.
Instead, render the four generated files into the existing site's artifact.

Add the badges after the first successful publication:

```markdown
[![Scorecard Workflow](https://github.com/OWNER/REPOSITORY/actions/workflows/guardrails-scorecard.yml/badge.svg?event=pull_request_target)](https://github.com/OWNER/REPOSITORY/actions/workflows/guardrails-scorecard.yml)
[![Latest PR Scorecard](https://OWNER.github.io/REPOSITORY/guardrails-badge.svg)](https://OWNER.github.io/REPOSITORY/)
```

For an `OWNER.github.io` repository, use the Pages root without the repository
segment. The public projection contains aggregate status/counts, source-run
metadata, and a revision digest. Detailed controls, findings, evidence, reasons,
provider data, check URLs, raw revisions, and source Markdown are excluded from
Pages and remain in the source Actions artifact under normal repository access.
Publishing is optional reporting and never influences the
scorecard decision or branch rules.

The report page presents the policy status and decision, separate active,
enforced, and advisory counts, readable UTC timestamps, and a link to the
source CI run. Verification details expand to show the subject digest; summary
JSON and Markdown remain available. The layout adapts to narrow screens and
loads without JavaScript or external fonts. “Not passed” includes failed,
missing, and unresolved evidence; zero configured controls are labeled
explicitly. This is the latest published PR evaluation, not an assessment of
the current default branch.

Continue with [control setup](guardrails/control-setup.md) and [rulesets](../rulesets/README.md).
