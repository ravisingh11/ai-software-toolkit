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
- The Proof runtime installed with `.proof/adapter.py` (refresh an
  older installation with `tooling/install.py --refresh-existing`).
- For Snyk Open Source, dependencies must be resolvable; set
  `PROOF_SETUP_COMMAND` so the workflow installs them first.

## Install

```sh
cp <toolkit>/workflows/snyk.yml .github/workflows/snyk.yml
python3 .proof/configure.py --select-provider dependency-vulnerability=snyk-open-source --set dependency-vulnerability=advisory
python3 .proof/configure.py --select-provider deep-sast=snyk-code --set deep-sast=advisory   # replaces CodeQL as authoritative
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
| `--revision` differs from `HEAD`, no resolvable `HEAD`, or a dirty worktree | `not_run` | `revision-mismatch` |
| arguments naming a path outside the checkout (`--file=/abs/manifest`, `../dir`, a symlink that leaves the tree) | `not_run` | `revision-mismatch` |
| arguments that stop the scan (`--help`, `--version`, subcommands) | `not_run` | `configuration-missing` |

The workflow fails the job for every outcome except `passed`; the job summary
shows the status and reason code. `SNYK_TOKEN` is injected only into the
adapter step, never into the repository setup command. Set the
`SNYK_CODE_ENABLED` or `SNYK_OPEN_SOURCE_ENABLED` repository variable to
`false` to skip a job whose provider you have not selected. The template runs
only on `pull_request` so its check names match the provider contract. The
adapter is checked out from the base revision (`trusted/`) and scans the head
checkout (`candidate/`); a pull request that changes `.proof/adapter.py` or
the workflow file yields `not_run` evidence until it is merged.

This protects the evidence, not the secret, from a same-repository pull
request. Its author can already edit the `pull_request` workflow that receives
the secret, and job code on GitHub-hosted runners has passwordless sudo, so in
the Snyk Open Source job the repository setup command could also tamper with
the installed CLI. Fork pull requests receive no secrets, so the jobs are skipped for them and
the scorecard reports no result, never a pass. Grant write access
only to people trusted with the provider credential, and scope the token to
the minimum the scan needs.

The scorecard dashboard shows Snyk finding counts by severity on the deep SAST
and dependency vulnerability cards, for example **0 critical · 2 high · 5 medium
· 1 low**. The trusted adapter counts the JSON Snyk prints (Snyk Code SARIF
levels `error`, `warning`, and `note` map to high, medium, and low), and the
workflow packages only the counts with the base revision's runtime. Rule names,
file paths, and package names are never published. A scan that did not
complete records no counts, and the card says so.

## Verify

Open a pull request after installing the workflow and confirm that the `Snyk
Code` and `Snyk Open Source` checks appear for the exact head commit and that
the scorecard shows their evidence. Record the run in the
[verification ledger](verification.md).
