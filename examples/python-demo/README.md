# Python Guardrails v2 example

This standard-library Python application is an executable consumer of
[Guardrails](https://github.com/ravisingh11/ai-software-toolkit). It keeps
repository-specific ground truth in the application while using the shared v2
capability, profile, provider, evidence, and scorecard contracts.

![Engineering Standards](docs/assets/social-preview.png)

The committed example selects Core plus the optional GitHub profile. Every
selected capability remains advisory.

## Run the example

From `examples/python-demo`:

```sh
python3 -m unittest discover -s . -p 'test_*.py'
python3 tools/validate_demo.py --documentation
python3 tools/run_guardrails.py
```

`tools/run_guardrails.py` supplies real demo build and unit-test commands
through the standard environment variables, then runs:

```sh
python3 .guardrails/scan.py
```

The default scorecard omits controls that are inactive for the selected
operation and subject, including catalog entries marked `evidence-only`. Run
`python3 .guardrails/scan.py --all-catalog-controls` only when you want the
complete catalog view; that view includes inactive controls as `GRAY` /
`not_activated` rows.

The scan requires a clean Git `HEAD` before local providers can pass. On a dirty
worktree it writes truthful `NO RESULT` evidence instead of claiming the tests
or scanners passed that commit.

Reports are generated under:

```text
.artifacts/guardrails/evidence-YYYYMMDD-HHMMSSZ.json
.artifacts/guardrails/evidence.json
.artifacts/guardrails/scorecard-YYYYMMDD-HHMMSSZ.md
```

## Refresh the generated installation

From the standards repository root:

```sh
python3 tooling/install.py \
  --target examples/python-demo \
  --profile github \
  --refresh-existing \
  --dry-run
```

Review the plan, then remove `--dry-run`. Refresh preserves this demo's policy,
provider selection, documentation mappings, change-scope thresholds, ground
truth, and consumer-owned workflows. The committed generated runtime and marked
workflow copies are validated against the canonical distribution.

Pull requests also run the trusted `PR Change Scope` producer. It reports exact
total, meaningful, and excluded metrics; the demo keeps it advisory so an
oversized example is visible as `ORANGE / ALLOW` without blocking iteration.
The trusted `PR Metadata` producer cancels superseded runs per pull request and
requires its run-bound evidence upload before its exact-head check can pass.

## Capability and provider flow

Core supplies repository validators, repository commands, Semgrep CE, and
Gitleaks CLI. The GitHub overlay adds CodeQL, Dependency Review, GitHub Secret
Protection, and Dependabot verification. It also installs an
`Artifact Provenance` release-attestation workflow, but that workflow does not
yet emit nested artifact evidence or feed a Guardrails release scorecard and is
not a PR required-check candidate.

```text
profile -> capability -> authoritative provider -> exact-subject evidence
                  \---- supplemental provider ----> advisory evidence
```

The demo declares application documents in
`.guardrails/ground-truth-ai.yaml`. Those paths are demo-specific; consuming
repositories may use any existing repository-relative document paths.

## Local and pull-request flow

Local scans provide fast feedback from the current machine. The generated
workflows are nested here, so GitHub does not execute them in the parent
standards repository. When this example is copied to its own repository, the
provider workflows run independently against the PR head and `Guardrail
Scorecard` collects their exact-head evidence.

Configure these repository variables for the demo's command providers:

```text
GUARDRAILS_BUILD_COMMAND=python3 -m compileall -q app.py test_app.py tools .guardrails
GUARDRAILS_UNIT_TEST_COMMAND=python3 -m unittest discover -s . -p 'test_*.py'
GUARDRAILS_WORKING_DIRECTORY=.
```

The demo does not claim changed-code coverage; that capability remains
`NO RESULT` until a consuming repository configures a real coverage command.
The installed `Format and Lint` and `Migration Validation` workflows also
require real repository commands before the demo is run as a standalone GitHub
repository. Unlike the local scanner, those two Actions jobs fail when their
command is absent so they cannot satisfy a required context through a skip. Do
not configure either variable with a no-op merely to make the example green.

Set `GUARDRAILS_CODEQL_LANGUAGES=python` and
`GUARDRAILS_DEPENDENCY_REVIEW_ENABLED=true` only when the GitHub profile checks
are supported in the consuming repository. The optional
`SECURITY_SETTINGS_TOKEN` enables trusted setting probes; without it, GitHub
Secret Protection and Dependabot remain `NO RESULT`.

## Read the scorecard

| Readiness | Meaning |
| --- | --- |
| `GREEN` | Authoritative provider passed for the exact subject. |
| `ORANGE` | Advisory capability lacks an authoritative pass. |
| `RED` | Enforced capability lacks an authoritative pass or evidence targets the wrong subject. |
| `GRAY` | Capability is not activated for this operation/subject. |

Supplemental providers never satisfy or block a capability. Keep optional
vendor providers advisory until their workflow or adapter, credential/config,
exact evidence binding, and check name are verified.

Generated `.artifacts/` content is intentionally ignored. GitHub Actions
uploads the scorecard directory as `guardrail-scorecard-<run-id>`.

## Optional badges

The native **Scorecard Workflow** badge reports workflow execution. The
optional **Latest PR Scorecard** badge reports the newest accepted PR readiness
and passed/active count; workflow success can still contain an advisory
`ORANGE` score, and the latest PR result does not attest current `main`.

Badge publication is not embedded under this example because nested workflows
do not execute in the parent repository. A standalone demo repository can add
it with `--refresh-existing --scorecard-badge`, then follow the
[badge setup](https://github.com/ravisingh11/ai-software-toolkit/blob/main/docs/quickstart.md#publish-the-optional-scorecard-badge).
The public projection is aggregate-only; detailed evidence is excluded from
Pages and remains in the source Actions artifact under normal repository
access. Publication never changes `allow`, `block`, or branch protection.
