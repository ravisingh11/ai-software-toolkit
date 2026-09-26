# Snyk Code and Snyk Open Source

Two providers share one workflow template and one credential.

| | Snyk Code | Snyk Open Source |
| --- | --- | --- |
| Provider id | `snyk-code` | `snyk-open-source` |
| Capability | `deep-sast` | `dependency-vulnerability` |
| Check name | `Snyk Code` | `Snyk Open Source` |
| Workflow | `Snyk` (`.github/workflows/snyk.yml`) | same |
| Adapter command | `snyk code test --json` | `snyk test --json` |
| Arguments variable | `SNYK_CODE_ARGS` | `SNYK_OPEN_SOURCE_ARGS` |
| Credential | `SNYK_TOKEN` (GitHub secret) | same |

## Prerequisites

- A Snyk organization and an API token stored as the `SNYK_TOKEN` repository
  or organization secret. Snyk Code must be enabled for the organization.
- The Guardrails runtime installed with `.guardrails/adapter.py` (refresh an
  older installation with `tooling/install.py --refresh-existing`).
- For Snyk Open Source, dependencies must be resolvable; set
  `GUARDRAILS_SETUP_COMMAND` so the workflow installs them first.

## Install

```sh
cp <toolkit>/workflows/snyk.yml .github/workflows/snyk.yml
python3 .guardrails/configure.py --select-provider dependency-vulnerability=snyk-open-source --set dependency-vulnerability=advisory
python3 .guardrails/configure.py --select-provider deep-sast=snyk-code --set deep-sast=advisory   # replaces CodeQL as authoritative
```

Keep CodeQL authoritative for `deep-sast` and add Snyk Code as supplemental
(`--add-supplemental deep-sast=snyk-code`) if you want both; supplemental
evidence is advisory and cannot satisfy or block the capability.

## Outcomes

The Snyk CLI exit code is the contract
([Snyk `test` reference](https://docs.snyk.io/developer-tools/snyk-cli/commands/test)):

| Exit | Evidence | Reason code |
| --- | --- | --- |
| 0 | `passed` | — |
| 1 | `failed` with the finding count from the JSON output | — |
| 2 | `blocked` | `authentication-failed` when the output names the token, else `execution-error` |
| 3 | `not_run` | `unsupported-project` |
| timeout | `blocked` | `timed-out` |
| `SNYK_TOKEN` unset | `blocked` | `credential-missing` |
| `snyk` not on `PATH` | `not_run` | `configuration-missing` |
| `--revision` differs from `HEAD` | `not_run` | `revision-mismatch` |

The workflow fails the job for every outcome except `passed`; the job summary
shows the status and reason code.

## Verify

Open a pull request after installing the workflow and confirm that the `Snyk
Code` and `Snyk Open Source` checks appear for the exact head commit and that
the scorecard shows their evidence. Record the run in the
[verification ledger](verification.md).
