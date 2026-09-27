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

The workflow templates check out `.proof/adapter.py` from the pull request's
base revision into `trusted/` and run it against the head revision in
`candidate/`, so a pull request cannot change the code that receives the
credential. The base revision must already contain the adapter; the first
pull request that installs it fails the job with that message until the
installation is merged. The provider contracts also list the adapter as a
trusted path, so the scorecard refuses `Snyk Code`, `Snyk Open Source`, and
`FOSSA` evidence (`not_run`) from any pull request whose adapter or workflow
file differs from the base, including one that refreshes the runtime through
`ai-toolkit update`. What remains is the trust GitHub gives every
`pull_request` workflow that uses a secret: on a same-repository pull request
the workflow file itself comes from the head, so protect `.github/workflows/`
with review requirements; fork pull requests receive no secret at all. The
provider CLI runs against candidate code and may execute the repository's own
build tooling, which is inherent to those scanners.

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
