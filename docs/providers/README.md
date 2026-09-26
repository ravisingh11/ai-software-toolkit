# Providers

A provider produces evidence for one or more capabilities. Repository and
GitHub providers are installed by the Guardrails installer; external providers
are opt-in and need a credential the consumer owns. This section documents
each external provider's prerequisites, credential, check identity, outcomes,
and the diagnostics that tell you where setup stands.

| Provider | Capabilities | Credential | Template | Command ownership | Guide |
| --- | --- | --- | --- | --- | --- |
| SonarQube | `static-quality`, `changed-code-coverage` | `SONAR_TOKEN` | `workflows/sonar.yml` | Scanner action plus the quality-gate wait action | [sonarqube.md](sonarqube.md) |
| Snyk Code | `deep-sast` | `SNYK_TOKEN` | `workflows/snyk.yml` | Adapter: `snyk code test` | [snyk.md](snyk.md) |
| Snyk Open Source | `dependency-vulnerability` | `SNYK_TOKEN` | `workflows/snyk.yml` | Adapter: `snyk test` | [snyk.md](snyk.md) |
| FOSSA | `dependency-vulnerability`, `license-compliance` | `FOSSA_API_KEY` | `workflows/fossa.yml` | Adapter: `fossa analyze` then `fossa test` | [fossa.md](fossa.md) |
| Semgrep AppSec Platform | `custom-static-analysis`, `deep-sast` | `SEMGREP_APP_TOKEN` | none | Organization integration; evidence is the `Semgrep` app check | [control setup](../guardrails/control-setup.md#optional-vendor-providers) |

Every provider is opt-in: selecting it as authoritative for a capability with
`.guardrails/configure.py --select-provider CAPABILITY=PROVIDER` (or
`ai-toolkit providers select`) and activating the capability is what makes its
evidence count. Selection is not a pass; only exact-revision evidence is.

## Adapter-owned commands

Snyk and FOSSA run through `.guardrails/adapter.py` (source:
`tooling/provider_adapter.py`). The adapter, not the consumer, decides the
command sequence and how exit codes and output map to evidence. Consumers
supply arguments through `SNYK_CODE_ARGS`, `SNYK_OPEN_SOURCE_ARGS`, and
`FOSSA_ARGS` (repository variables in CI, environment variables locally), never
the verb. This is what guarantees that an upload alone cannot pass: `fossa
analyze` without a completed `fossa test` is `blocked` / `analysis-incomplete`.

Run an adapter locally to produce a fragment that `scan.py` merges:

```sh
export SNYK_TOKEN=...            # never committed
python3 .guardrails/adapter.py snyk-open-source --target .
python3 .guardrails/scan.py      # merges .artifacts/guardrails/evidence/*.json
```

The adapter exits 0 only for `passed`; the workflow templates fail the job for
every other outcome and put the reason in the job summary and in an uploaded
evidence fragment.

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

`ai-toolkit doctor` (and `.guardrails/doctor.py`) adds, for each selected
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
