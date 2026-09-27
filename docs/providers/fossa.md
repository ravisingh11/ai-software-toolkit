# FOSSA

| | |
| --- | --- |
| Provider id | `fossa` |
| Capabilities | `dependency-vulnerability`, `license-compliance` |
| Check name | `FOSSA` |
| Workflow | `FOSSA` (`.github/workflows/fossa.yml`) |
| Adapter commands | `fossa analyze --revision <sha>` then `fossa test --revision <sha> --format json --timeout <s>` |
| Arguments variable | `FOSSA_ARGS` (extra `fossa analyze` arguments) |
| Credential | `FOSSA_API_KEY` (GitHub secret) |
| CLI pin | version and SHA-256 in the workflow `env:`; update both together |

## Why two commands

`fossa analyze` uploads the dependency graph; the policy decision is computed
asynchronously by FOSSA and returned only by `fossa test`
([FOSSA `test` reference](https://docs.fossa.com/docs/cli/references/subcommands/test)).
A workflow that runs only `analyze` has produced no evidence. The adapter
always runs both for the exact revision and reports `analysis-incomplete`
when `test` does not finish.

## Prerequisites

- A FOSSA account and an API key stored as the `FOSSA_API_KEY` secret.
- The Proof runtime installed with `.proof/adapter.py`.
- Optional `.fossa.yml` in the repository for project and target settings.

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

`FOSSA_API_KEY` is injected only into the adapter step. The template runs
only on `pull_request` so its check name matches the provider contract. The
adapter is checked out from the base revision (`trusted/`) and scans the head
checkout (`candidate/`); a pull request that changes `.proof/adapter.py` or
the workflow file yields `not_run` evidence until it is merged.

## Verify

Open a pull request, confirm the `FOSSA` check binds to the head commit and
that the scorecard shows the evidence, then add a row to the
[verification ledger](verification.md).
