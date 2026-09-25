# Guardrails v2 operating runbook

Use this runbook to install, configure, run, interpret, and promote Guardrails
without turning missing configuration into a pass.

## Install

```sh
python3 /path/to/ai-software-toolkit/tooling/install.py --target /path/to/repo
python3 /path/to/ai-software-toolkit/tooling/install.py --target /path/to/repo --profile github
python3 /path/to/ai-software-toolkit/tooling/install.py --target /path/to/repo --no-actions
python3 /path/to/ai-software-toolkit/tooling/install.py --target /path/to/repo --local-hooks
```

The first command installs Core runtime and Actions. The second also selects
the GitHub overlay. `--no-actions` installs runtime only. `--local-hooks` adds
validated Semgrep CE and Gitleaks pre-commit hooks when `pre-commit` is present
and no pre-commit configuration already exists.

For existing v2 installations, preview `--merge-existing` or
`--refresh-existing` before writing. Refresh preserves repository-owned policy,
provider selection, documentation mapping, change-scope, ground truth, and
unmarked consumer workflows.

## Configure

```sh
python3 .guardrails/configure.py --help
python3 .guardrails/configure.py --list
python3 .guardrails/configure.py --enable-profile github --dry-run
python3 .guardrails/configure.py --set unit-tests=enforced --dry-run
python3 .guardrails/configure.py --add-supplemental deep-sast=snyk-code --dry-run
```

Configuration writes `.guardrails/policy.yaml` and
`.guardrails/providers.yaml` together. Remove `--dry-run` only after reviewing
both documents.

## Configure repository commands

```text
GUARDRAILS_SETUP_COMMAND
GUARDRAILS_BUILD_COMMAND
GUARDRAILS_UNIT_TEST_COMMAND
GUARDRAILS_CHANGED_COVERAGE_COMMAND
GUARDRAILS_FORMAT_LINT_COMMAND
GUARDRAILS_MIGRATION_VALIDATION_COMMAND
GUARDRAILS_WORKING_DIRECTORY
```

Use environment variables locally and repository variables in Actions. Local
scans represent missing commands as `not_run` / `NO RESULT`. In Actions, missing
build, test, and coverage commands do not create passing evidence. Missing
format/lint or migration commands fail their named jobs so those contexts cannot
satisfy branch protection by being skipped.

For the GitHub overlay, configure only applicable values:

```text
GUARDRAILS_CODEQL_LANGUAGES
GUARDRAILS_DEPENDENCY_REVIEW_ENABLED=true
GUARDRAILS_ARTIFACT_BUILD_COMMAND
GUARDRAILS_ARTIFACT_PATH
SECURITY_SETTINGS_TOKEN  # optional secret
```

The optional settings token needs repository Administration read and Secret
scanning alerts read access. Missing or insufficient access remains
`NO RESULT`.

## Run locally

```sh
python3 .guardrails/scan.py --help
python3 .guardrails/scan.py
```

The scanner requires exact clean-HEAD binding before local producers can pass.
It writes timestamped evidence and Markdown under `.artifacts/guardrails/`.
Use `--json` for machine-readable scorecard output and `--operation release`
for release policy. Default reports omit inactive and `evidence-only` controls;
use `--all-catalog-controls` only when a complete catalog view with `GRAY` /
`not_activated` rows is needed.

External providers can write nested v2 evidence fragments to
`.artifacts/guardrails/evidence/*.json`. The scanner merges only fragments with
the exact same subject. Conflicting provider results are contract errors.

## Run on a pull request

Core and selected GitHub workflows run independently. `Guardrail Scorecard`
then collects the declared provider checks for the exact PR head, verifies their
GitHub Actions provenance, evaluates the policy, and uploads the evidence and
scorecard artifact.

Treat the pull-request checks as merge evidence. Local results are diagnostic
because tools, history, and credentials may differ. A successful scorecard job
does not mean every capability passed; read its capability rows and decision.

## Interpret

| Result | Action |
| --- | --- |
| `GREEN / ALLOW` | Every selected authoritative provider passed for the exact subject. |
| `ORANGE / ALLOW` | Resolve or explicitly accept advisory gaps; do not call them passed. |
| `RED / BLOCK` | Fix enforced evidence or subject mismatch before proceeding. |
| `GRAY` row | Capability is not activated for this operation/subject; shown only in an `--all-catalog-controls` report. |

Supplemental providers never change the decision.

## Promote

1. Confirm the producer runs on representative changes.
2. Confirm exact-subject evidence and stable check naming.
3. Remove its required configuration and confirm the producer does not pass;
   format/lint and migration validation must fail visibly when their command is
   absent.
4. Assign a remediation owner.
5. Set the capability to `enforced`.
6. Add the exact observed check context to the GitHub ruleset.

Do not promote configuration jobs, setup probes, skipped jobs, or scorecard
aggregation itself as substitutes for capability evidence.

## Audit evidence

Retain the nested JSON evidence, timestamped Markdown scorecard, provider logs,
and relevant artifact attestations for the repository's required retention
period. Preserve the exact subject identifiers. Credentials and secret values
must never enter evidence, logs, documentation, or committed artifacts.

See [control setup](control-setup.md), [status](control-status.md), and
[producer contract](producer-contract.md).
