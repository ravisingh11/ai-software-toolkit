# Providers

A provider produces evidence for one or more capabilities. Repository and
GitHub providers are installed by the Proof installer; external providers
are opt-in and need a credential the consumer owns. This section documents
each external provider's prerequisites, credential, check identity, outcomes,
and the diagnostics that tell you where setup stands.

| Provider | Capabilities | Credential | Template | Command ownership | Guide |
| --- | --- | --- | --- | --- | --- |
| SonarQube | `static-quality`, `changed-code-coverage` | `SONAR_TOKEN` | `workflows/sonar.yml` | Scanner action plus the quality-gate wait action | [sonarqube.md](sonarqube.md) |
| Snyk Code | `deep-sast` | `SNYK_TOKEN` | `workflows/snyk.yml` | Adapter: `snyk code test` | [snyk.md](snyk.md) |
| Snyk Open Source | `dependency-vulnerability` | `SNYK_TOKEN` | `workflows/snyk.yml` | Adapter: `snyk test` | [snyk.md](snyk.md) |
| FOSSA | `dependency-vulnerability`, `license-compliance` | `FOSSA_API_KEY` | `workflows/fossa.yml` | Adapter: `fossa analyze` then `fossa test` | [fossa.md](fossa.md) |
| Semgrep AppSec Platform (`semgrep-app`) | `custom-static-analysis`, `deep-sast` | `SEMGREP_APP_TOKEN` | none | Organization integration; evidence is the `Semgrep` app check | [control setup](../proof/control-setup.md#optional-vendor-providers) |

Every provider is opt-in: selecting it as authoritative for a capability with
`.proof/configure.py --select-provider CAPABILITY=PROVIDER` (or
`ai-toolkit providers select`) and activating the capability is what makes its
evidence count. Selection is not a pass; only exact-revision evidence is.

## Adapter-owned commands

Snyk and FOSSA run through `.proof/adapter.py` (source:
`tooling/provider_adapter.py`). The adapter, not the consumer, decides the
command sequence and how exit codes and output map to evidence. Consumers
supply arguments through `SNYK_CODE_ARGS`, `SNYK_OPEN_SOURCE_ARGS`, and
`FOSSA_ARGS` (repository variables in CI, environment variables locally), never
the verb. This is what guarantees that an upload alone cannot pass: `fossa
analyze` without a completed `fossa test` is `blocked` / `analysis-incomplete`.

Run an adapter locally to produce a fragment that `scan.py` merges:

```sh
export SNYK_TOKEN=...            # never committed
python3 .proof/adapter.py snyk-open-source --target .
python3 .proof/scan.py      # merges .artifacts/proof/evidence/*.json
```

The adapter exits 0 only for `passed`; the workflow templates fail the job for
every other outcome and put the reason in the job summary and in an uploaded
evidence fragment. Evidence binds to a clean checkout: a dirty worktree, an
unresolvable `HEAD`, or a revision that is not `HEAD` yields `revision-mismatch`,
and so does any `*_ARGS` value that names a path outside the checkout, such
as `--file=/elsewhere/package.json`, `--policy-path=../shared`, or a committed
symlink that leaves the tree, because the provider would then examine or
filter something other than the revision.

## Credential isolation

The Snyk, FOSSA, and AI PR Review workflows hold a provider credential. None
of them shares a job or a runner with pull-request code:

1. **The workflow comes from the default branch.** The templates run on
   `pull_request_target`, and GitHub always takes a `pull_request_target`
   workflow file and checkout commit from the default branch
   ([GitHub changelog, 2025-11-07](https://github.blog/changelog/2025-11-07-actions-pull_request_target-and-environment-branch-protections-changes/)).
   Each job checks out `.proof/` from that same commit (`trusted/`). A pull
   request that edits the workflow or the runtime changes nothing until it is
   merged.
2. **The secret is readable only from the default branch.** Store
   `SNYK_TOKEN`, `FOSSA_API_KEY`, and `ANTHROPIC_API_KEY` as secrets of an
   environment named `proof-providers`, with deployment branches limited to
   the default branch, and delete any repository or organization secret of the
   same name. A repository secret is readable by any workflow pushed to any
   branch, so a workflow split alone would not protect it. GitHub checks
   environment rules for `pull_request` runs against `refs/pull/<n>/merge`,
   and for `pull_request_target` runs against the default branch. The jobs
   use `deployment: false`, so they create no deployment records.
3. **The pull-request head is data.** Each job checks the head out into
   `candidate/` without credentials and never executes it. There is no setup
   command, dependency installation, build tool, or local action. The adapter
   runs with `--data-only`: FOSSA runs static analysis against a fixed
   endpoint, and Snyk Open Source tests only lockfiles whose parsers run
   nothing (see [Snyk](snyk.md)).

This boundary prevents invoking candidate commands; it is not an operating
system sandbox around the provider binaries. FOSSA's static analysis may run
its bundled helper tools. Pinned CLI versions, fixed endpoints, environment
isolation, and real provider verification remain necessary. Generic CodeQL
warnings about candidate checkout in a privileged workflow still require
review; fixture tests alone do not clear them.

Each job posts the check named in the provider contract for the pull-request
head, with the external id `proof:<provider>:<run id>:<head sha>`, and uploads
the same result as the run-bound artifact `proof-<provider>-<run id>`
(`.proof/provider_check.py`, source `tooling/provider_check.py`). The Proof
collector trusts that check only when
its run is a `pull_request_target` run of the declared workflow, and it reads
the status from the artifact: the artifact must name the same run,
repository, provider, base SHA, base ref, and head SHA. The job's own check
has a different name (for example `Snyk Code scan`), so it can never stand in
for the provider check. A missing runtime, a missing or unreadable adapter
result, or a job that never finishes yields no pass.

**Fork pull requests** are withheld. The pinned checkout action refuses fork
heads in privileged workflows, and this integration's fork-scanning boundary
has not been independently verified. There is currently no fork opt-in; the
workflows preserve the checkout action's default protection. A fork pull
request gets the provider check with conclusion `action_required` and
`not_run` evidence (`credential-withheld`), without checking out its head or
sending its code to a provider. This applies to Snyk, FOSSA, and AI PR review.
Dependabot pull requests receive no Actions or environment secrets and report
`credential-missing`.

`tooling/doctor.py --github <owner>/<repo>` reports whether `proof-providers`
exists, whether only the default branch can use it, and whether any provider
secret still has a repository or organization copy. It reads names only,
never secret values.

### Migrating from the `pull_request` templates

1. Create the `proof-providers` environment with deployment branches limited
   to the default branch. Add the provider secrets to it, and then delete the
   repository and organization copies.
2. Refresh the runtime (`tooling/install.py --refresh-existing`) and copy the
   new `snyk.yml`, `fossa.yml`, and `ai-pr-review.yml` templates over the old
   ones. The paths, workflow names, and provider check names are unchanged, so
   rulesets and the scorecard need no change.
3. Expect the pull request that makes this change to show the provider checks
   as not run. Its workflows no longer run on `pull_request`, and until merge
   the default branch still has the old files. The next pull request after
   merge runs the new workflows.
4. `PROOF_SETUP_COMMAND` no longer affects Snyk. Projects whose dependencies
   need a build tool or package manager to resolve get Snyk Open Source
   `requires-dependency-resolution`.
5. `ai-pr-review.yml` no longer offers `workflow_call`. Set
   `AI_REVIEW_COMMAND`, `AI_REVIEW_SETUP_COMMAND`, and
   `AI_REVIEW_WORKING_DIRECTORY` as repository variables.

## Reason codes

Non-passing results (`blocked`, `not_run`) carry a reason that starts with one
of these codes. Reports and `ai-toolkit check` key their next action off the
code; the evidence schema is unchanged (the code is the prefix of `reason`).

| Code | Status | Meaning | Typical next action |
| --- | --- | --- | --- |
| `configuration-missing` | `not_run` | A required CLI, file, or setting is absent; nothing was scanned | Install the tool or configuration named in the reason |
| `credential-missing` | `blocked` | The credential is not available to this run | Add the GitHub secret or export the variable locally |
| `authentication-failed` | `blocked` | The provider rejected the credential | Rotate or fix the credential |
| `execution-error` | `blocked` | The command failed before producing a result | Read the run log |
| `analysis-incomplete` | `blocked` | Upload or start succeeded but the provider did not finish evaluating the revision | Rerun once analysis completes or raise the timeout |
| `revision-mismatch` | `not_run` | Evidence is for a different revision than the one under evaluation | Rerun on the exact HEAD |
| `unsupported-project` | `not_run` | The provider found nothing it can analyze | Check the working directory and manifests, or deselect the provider |
| `timed-out` | `blocked` | The command exceeded the adapter timeout | Rerun or raise `--timeout` |

## What GitHub check runs can and cannot express

On a pull request, the evaluator reads the job's check run: `success` is
`passed`, `failure` is `failed`, `timed_out` is `blocked`, and `neutral` or
`skipped` is `not_run`. A job cannot conclude `neutral` from a step, so the
adapter workflows fail the job for every non-passing outcome. The distinct
reason code is visible in the job summary and the uploaded fragment, and in
local scans that merge fragments, but the check-run surface collapses
non-passing outcomes to `failed`. Run-bound artifact evidence (used by
`PR Change Scope` and `PR Metadata`) would lift that limitation but requires a
`pull_request_target` workflow that never checks out untrusted code with the
provider credential, which these scanners cannot satisfy; that is why it is
not used here.

## Diagnostics

`ai-toolkit doctor` (and `.proof/doctor.py`) adds, for each selected
external provider:

- `provider.<id>.adapter` — whether the installed runtime carries the adapter
  and whether the CLI is on `PATH` locally (nothing is executed).
- `local.credential.<NAME>` — whether the credential is set locally; its
  validity is never checked.
- `provider.<id>.template` — whether the shipped workflow template has been
  copied into `.github/workflows/`.

## Verification status

Fixtures prove the mapping; only a live run against the real service proves
the adapter. The [verification ledger](verification.md) records which adapters
have been verified live, when, at which toolkit revision, and by whom. An
adapter is labelled verified only in the pull request that adds its ledger row.

Doctor checks both authoritative and supplemental providers, including GitHub
secret-name metadata when `--github` is requested. A missing or stale adapter
contract is reported as action needed; refresh the installed runtime before
running that provider. Secret presence never proves credential validity.

## Migrate callers of the reusable security bundle

The reusable `workflows/security-scanning.yml` no longer accepts the
`fossa-command` or `snyk-open-source-command` inputs, or the `FOSSA_API_KEY`
and `SNYK_TOKEN` secrets. Remove those entries from the caller's `with:` and
`secrets:` mappings before upgrading its pinned toolkit revision. Keep the
bundle for its remaining scanners; credentialed FOSSA and Snyk scans now use
the standalone adapter workflows.

1. Refresh the installed `.proof/` runtime and copy the hardened
   `workflows/fossa.yml` and/or `workflows/snyk.yml` into the consuming
   repository's `.github/workflows/` directory. Merge the runtime and templates
   into the default branch before expecting provider results. These templates
   use `pull_request_target`; the workflow must already exist on the default
   branch. Keep provider controls advisory while verifying the new producer.
2. Create the `proof-providers` GitHub environment restricted to the default branch
   and store `FOSSA_API_KEY` and/or `SNYK_TOKEN` as environment secrets. Remove
   duplicate repository secrets and exclude this repository from any
   organization secrets with those names, so credentials cannot bypass the
   environment's branch restriction. Verify the pinned scanner's execution
   boundary; static analysis is not an operating system sandbox. Credentials
   remain withheld for fork pull requests.
3. Configure the adapter argument variables (`FOSSA_ARGS`, `SNYK_CODE_ARGS`,
   `SNYK_OPEN_SOURCE_ARGS`) and provider selection using the
   [FOSSA](fossa.md) and [Snyk](snyk.md) guides. The removed command inputs are
   not copied into these variables: adapters own the commands. Retain the
   templates' native CLI version and checksum pins, updating each pair
   together; do not replace the Snyk binary with an npm wrapper.
4. Run a new pull request after installation and verify the standalone
   `FOSSA`, `Snyk Code`, or `Snyk Open Source` checks and their exact-revision
   evidence before changing required checks. Missing credentials, withheld
   fork credentials, and incomplete scans do not establish a passing result.
