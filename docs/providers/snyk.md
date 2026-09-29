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
| Credential | `SNYK_TOKEN` (secret of the `proof-providers` environment) | same |

## Prerequisites

- A Snyk organization and an API token. Snyk Code must be enabled for the
  organization.
- A `proof-providers` environment whose deployment branches are limited to
  the default branch, with the token stored as its `SNYK_TOKEN` secret, and no
  repository or organization secret of the same name. See
  [Credential isolation](README.md#credential-isolation).
- The Proof runtime, including `.proof/adapter.py` and
  `.proof/provider_check.py`, merged to the default branch (refresh an older
  installation with `tooling/install.py --refresh-existing`).
- For Snyk Open Source, committed lockfiles: `package-lock.json`,
  `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml`, or `Gemfile.lock`.

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

In the workflow, the adapter runs with `--data-only`, which adds:

| Situation | Evidence | Reason code |
| --- | --- | --- |
| a manifest that Snyk resolves by running a build tool, package manager, or interpreter (`pom.xml`, `gradlew`, `build.gradle`, `requirements.txt`, `pyproject.toml`, `go.mod`, `*.csproj`, a `package.json` with no lockfile beside it or above it, and others) | `not_run`, nothing scanned | `requires-dependency-resolution` |
| `SNYK_OPEN_SOURCE_ARGS` that choose targets (`--file`, `--package-manager`, `--command`, a positional path) | `not_run` | `configuration-missing` |
| a symlinked manifest or lockfile | `not_run` | `revision-mismatch` |
| no supported lockfile | `not_run` | `unsupported-project` |
| fork pull request without `PROOF_PROVIDERS_SCAN_FORKS=true` | `not_run`, check concluded `action_required` | `credential-withheld` |

Snyk Open Source runs `snyk test --file=<lockfile>` once per lockfile, and
the worst result wins: any blocked or not-run lockfile makes the whole check
non-passing. `--all-projects`, `--yarn-workspaces`, and `--detection-depth`
are ignored because the adapter finds the lockfiles itself, and
`--exclude=<names>` also excludes those directories and files from that
search. `node_modules` and `.git` are always skipped.

The workflow posts the `Snyk Code` and `Snyk Open Source` checks for the
pull-request head and fails its own jobs (`Snyk Code scan`, `Snyk Open Source
scan`) for every outcome except `passed`. The job summary shows the status
and reason code. Set the `SNYK_CODE_ENABLED` or `SNYK_OPEN_SOURCE_ENABLED`
repository variable to `false` to skip a job for a provider you have not
selected.

## How the token is protected

`SNYK_TOKEN` never shares a job or a runner with pull-request code:

- The workflow runs on `pull_request_target`, so GitHub takes it and the
  `.proof` runtime from the default branch. A pull request that edits
  `.github/workflows/snyk.yml` or `.proof/adapter.py` changes nothing until it
  is merged.
- The token is a secret of the `proof-providers` environment. Its deployment
  branch policy stops a `pull_request` workflow, which runs against
  `refs/pull/<n>/merge`, or a `push` workflow on another branch, from reading
  it.
- The job checks the pull-request head out as data. There is no setup
  command, dependency installation, or build tool. The adapter runs in a
  minimal environment (`env -i`) that holds the token and nothing else of the
  job.

What the candidate can still influence is data the scan reads: the source
code, the lockfiles, and a `.snyk` policy file, whose ignores apply as they
always have. Snyk Open Source for projects that need dependency resolution is
reported as not run rather than scanned. For those projects, select a
provider that needs no credential, or keep Snyk Open Source running outside
the pull-request workflow, where its result is not Proof evidence.

The scorecard dashboard shows Snyk finding counts by severity on the deep SAST
and dependency vulnerability cards, for example **0 critical · 2 high · 5 medium
· 1 low**. The trusted adapter counts the JSON Snyk prints (Snyk Code SARIF
levels `error`, `warning`, and `note` map to high, medium, and low), and the
counts travel in the same run-bound evidence artifact as the result. Rule names,
file paths, and package names are never published. A scan that did not
complete records no counts, and the card says so.

## Verify

After the workflow and runtime are on the default branch, open a
same-repository pull request and confirm that the `Snyk Code` and `Snyk Open
Source` checks appear for the exact head commit and that the scorecard shows
their evidence. Then confirm that a pull request which edits
`.github/workflows/snyk.yml` still runs the default branch's version, and that
a fork pull request shows `action_required`. Record the run in the
[verification ledger](verification.md).
