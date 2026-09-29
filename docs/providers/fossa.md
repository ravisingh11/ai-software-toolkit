# FOSSA

| | |
| --- | --- |
| Provider id | `fossa` |
| Capabilities | `dependency-vulnerability`, `license-compliance` |
| Check name | `FOSSA` |
| Workflow | `FOSSA` (`.github/workflows/fossa.yml`) |
| Adapter commands | `fossa analyze --revision <sha>` then `fossa test --revision <sha> --format json --timeout <s>`; in the workflow both also get `--endpoint`, and `analyze` gets `--static-only-analysis` |
| Arguments variable | `FOSSA_ARGS` (extra `fossa analyze` arguments); `FOSSA_ENDPOINT` for a server other than `https://app.fossa.com` |
| Credential | `FOSSA_API_KEY` (secret of the `proof-providers` environment) |
| CLI pin | version and SHA-256 in the workflow `env:`; update both together |

## Why two commands

`fossa analyze` uploads the dependency graph; the policy decision is computed
asynchronously by FOSSA and returned only by `fossa test`
([FOSSA `test` reference](https://docs.fossa.com/docs/cli/references/subcommands/test)).
A workflow that runs only `analyze` has produced no evidence. The adapter
always runs both for the exact revision and reports `analysis-incomplete`
when `test` does not finish.

## Prerequisites

- A FOSSA account and an API key.
- A `proof-providers` environment whose deployment branches are limited to
  the default branch, with the key stored as its `FOSSA_API_KEY` secret, and
  no repository or organization secret of the same name. See
  [Credential isolation](README.md#credential-isolation).
- The Proof runtime, including `.proof/adapter.py` and
  `.proof/provider_check.py`, merged to the default branch.
- Optional `.fossa.yml` in the repository for project and target settings. It
  must not set `server`, `endpoint`, or `apiKey`; the workflow refuses a
  configuration that would choose where the key is sent.

## Install

```sh
cp <toolkit>/workflows/fossa.yml .github/workflows/fossa.yml
python3 .proof/configure.py --select-provider license-compliance=fossa --set license-compliance=advisory
```

## Outcomes

| Situation | Evidence | Reason code |
| --- | --- | --- |
| `analyze` and `test` exit 0 | `passed` | — |
| `test` reports issues (exit 1 with JSON issues) | `failed` with the issue count | — |
| `analyze` or `test` rejects the key (`Status: 401/403`, "API key") | `blocked` | `authentication-failed` |
| `analyze` finds no targets | `not_run` | `unsupported-project` |
| `test` reports that the build is still pending | `blocked` | `analysis-incomplete` |
| `analyze` uploaded but `test` did not run | `blocked` | `analysis-incomplete` |
| other non-zero exit, or `issues: []` with a non-zero exit | `blocked` | `execution-error` |
| adapter timeout | `blocked` | `timed-out` |
| `FOSSA_API_KEY` unset | `blocked` | `credential-missing` |
| `fossa` not on `PATH` | `not_run` | `configuration-missing` |
| `--revision` differs from `HEAD`, no resolvable `HEAD`, or a dirty worktree | `not_run` | `revision-mismatch` |
| arguments naming a path outside the checkout (`--file=/abs/manifest`, `../dir`, a symlink that leaves the tree) | `not_run` | `revision-mismatch` |

In the workflow, the adapter runs with `--data-only`, which adds:

| Situation | Evidence | Reason code |
| --- | --- | --- |
| `.fossa.yml` or `.fossa.yaml` names `server`, `endpoint`, or `apiKey` | `not_run`, nothing sent | `configuration-missing` |
| `FOSSA_ARGS` sets `--endpoint`, `--fossa-api-key`, or `--config` | `not_run` | `configuration-missing` |
| `.fossa.yml` is a symlink | `not_run` | `revision-mismatch` |
| fork pull request without `PROOF_PROVIDERS_SCAN_FORKS=true` | `not_run`, check concluded `action_required` | `credential-withheld` |

The workflow posts the `FOSSA` check for the pull-request head and fails its
own `FOSSA scan` job for every outcome except `passed`. Set the
`FOSSA_ENABLED` repository variable to `false` to skip the job when FOSSA is
not selected.

## How the key is protected

`FOSSA_API_KEY` never shares a job or a runner with pull-request code:

- The workflow runs on `pull_request_target`, so GitHub takes it and the
  `.proof` runtime from the default branch.
- The key is a secret of the `proof-providers` environment, which only the
  default branch can use.
- The job checks the pull-request head out as data. `fossa analyze` runs with
  `--static-only-analysis`, so it invokes no build tool or package manager.
  Both commands run with an explicit `--endpoint`, so a candidate
  configuration cannot redirect the key.

Static analysis is less complete than a build-integrated analysis for
ecosystems where FOSSA would otherwise run the build tool, such as Gradle,
Maven, or sbt without lockfiles. Read FOSSA's
[strategy documentation](https://docs.fossa.com/docs/cli/references/subcommands/analyze)
for what each ecosystem reports statically.

The scorecard dashboard does not collect FOSSA issue or license counts yet:
the dependency vulnerability and license compliance cards show only the check
result and say so. Read counts from the job summary or the FOSSA project.

## Verify

After the workflow and runtime are on the default branch, open a
same-repository pull request, confirm the `FOSSA` check binds to the head
commit and that the scorecard shows the evidence, then add a row to the
[verification ledger](verification.md).
