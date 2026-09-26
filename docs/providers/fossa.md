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
- The Guardrails runtime installed with `.guardrails/adapter.py`.
- Optional `.fossa.yml` in the repository for project and target settings.

## Install

```sh
cp <toolkit>/workflows/fossa.yml .github/workflows/fossa.yml
python3 .guardrails/configure.py --select-provider license-compliance=fossa --set license-compliance=advisory
```

## Outcomes

| Situation | Evidence | Reason code |
| --- | --- | --- |
| `analyze` and `test` exit 0 | `passed` | — |
| `test` reports issues (exit 1 with JSON issues) | `failed` with the issue count | — |
| `analyze` or `test` rejects the key (`Status: 401/403`, "API key") | `blocked` | `authentication-failed` |
| `analyze` finds no targets | `not_run` | `unsupported-project` |
| `test` times out waiting for the build | `blocked` | `analysis-incomplete` |
| `analyze` uploaded but `test` did not run | `blocked` | `analysis-incomplete` |
| other non-zero exit | `blocked` | `execution-error` |
| adapter timeout | `blocked` | `timed-out` |
| `FOSSA_API_KEY` unset | `blocked` | `credential-missing` |
| `fossa` not on `PATH` | `not_run` | `configuration-missing` |
| `--revision` differs from `HEAD` | `not_run` | `revision-mismatch` |

## Verify

Open a pull request, confirm the `FOSSA` check binds to the head commit and
that the scorecard shows the evidence, then add a row to the
[verification ledger](verification.md).
