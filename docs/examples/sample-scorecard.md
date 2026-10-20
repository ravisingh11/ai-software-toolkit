# Illustrative Proof scorecard

**Illustrative example, not a live scan.** The outcomes and evidence filename
below are fictional. This abbreviated report demonstrates optional checks:
every selected capability is **advisory**, there are **zero enforced checks**,
and failed or missing evidence remains visible with an `ORANGE / ALLOW` result.
The example assumes the evidence matches the evaluated subject exactly.

For real results, open the [sample application](https://github.com/ravisingh11/ai-software-toolkit-reference-app)
and its [published scorecard](https://ravisingh11.github.io/ai-software-toolkit-reference-app/).
Check the snapshot's source revision, collection time, provider configuration,
and reported run before interpreting it as evidence for a change.

## Local report example

This table uses the local Markdown renderer's vocabulary and column format.
It shows a subset of an `--all-catalog-controls` report; inactive catalog rows
are omitted in the default view.

```text
# Proof Scan Report

- Status: **ORANGE**
- Decision: **ALLOW**
- Evidence: `.artifacts/proof/evidence-EXAMPLE.json`

| Readiness | Mode | Capability — Provider | Evidence |
| --- | --- | --- | --- |
| GREEN | advisory | Repository Validation — Repository Validators | passed |
| ORANGE | advisory | PR Change Scope — PR Size / Files & LOC | failed |
| ORANGE | advisory | Documentation Validation — Repository Validators | no_result |
| GREEN | advisory | Build — Repository Build Command | passed |
| GREEN | advisory | Unit Tests — Repository Unit Test Command | passed |
| ORANGE | advisory | Custom Static Analysis — Semgrep Community Edition | no_result |
| ORANGE | advisory | Secret Detection — Gitleaks CLI | no_result |
| ORANGE | advisory | Deep SAST — GitHub CodeQL default setup | no_result |
| GRAY | not_activated | Artifact Provenance — Not activated | not_activated |
| GRAY | not_activated | Container Vulnerability — Not activated | not_activated |
```

`GREEN` means an authoritative provider passed for the exact subject. `ORANGE`
means a selected advisory capability has no such pass, including failed,
blocked, missing, or unrun results. `GRAY` means the capability is not activated
for the operation and subject being evaluated. `ALLOW` describes the policy
decision; it does not mean every check passed or the application is secure.

`RED / BLOCK` applies when a repository explicitly opts into enforcement and an
enforced capability lacks an exact-subject pass. An evidence subject mismatch
also produces `RED / BLOCK`, even with advisory checks. Enforcement is a
repository decision, and AI review controls remain advisory-only.

For example, the fictional scope result can explain its orange row directly:

```text
Meaningful: 17 files, 1,284 changed lines (916 added). Total: 19 files,
1,472 changed lines. Excluded: 2 files, 188 changed lines.
```

The mechanical provider owns those counts. AI review can recommend independent
PR boundaries, but it does not recalculate the metrics or change the decision.

## Reading the published scorecard

The hosted page uses friendly labels: local `no_result` appears as
**Unverified**. Provider selection, activation, and evidence are separate:

| Illustrative observation | Meaning |
| --- | --- |
| Deep SAST: Unverified; Advisory; GitHub CodeQL default setup | A provider is selected, but this snapshot has no accepted result. Selection alone does not prove credentials, completed analyses, or a pass. |
| A check is Not activated with a named provider | A provider is selected, but this check has no active mode for this snapshot. |
| Provider: Not configured | The validated inactive row explicitly records no selected provider. |
| Not reported | The snapshot has no validated row or usable provider information; this does not establish that the check is disabled or passed. |
| Failed; Advisory | A real negative result remains visible without becoming a merge requirement. |

Provider names link to configuration at the evaluated revision. **Latest
reported run**, when available, links to validated evidence for that snapshot;
it does not promise a newer scan. For CodeQL default setup, acceptance requires
the configured languages, native managed run, jobs, and analyses to match the
exact PR revision and trusted configuration. A successful aggregate check or a
saved token alone is insufficient. See [CodeQL evidence](../providers/codeql.md).

The freshness notice compares the displayed snapshot with publication metadata.
If a newer snapshot is available, use **Refresh latest**. Refreshing loads a
published snapshot; it does not launch scans or fill missing evidence.

## Artifact and environment evidence

Optional [lifecycle providers](../providers/lifecycle.md) produce real Trivy,
SBOM, GitHub attestation, OWASP ZAP, deployment-policy, runtime, and soak results.
They require explicit activation and manual receipt collection. The gray rows
above illustrate a commit-only view, not an absence of these implementations.

A combined hosted report labels **Verification artifact** and **Verification
environment** separately. The signed receipt binds the PR revision, trusted
configuration, actual image digest, and measured environment. Commit evidence
cannot satisfy an artifact or runtime control. A valid signature proves the
binding; it does not turn failed vulnerability scans into passes or establish
production readiness. Missing or unverifiable receipts remain explicit gaps.

## Generate your own evidence

Follow [Start here](../../README.md#start-here) and the
[onboarding guide](../quickstart.md) to install and configure real repository
commands. From a committed, clean consumer repository, run:

```sh
python3 .proof/scan.py --all-catalog-controls
```

Read the generated Markdown and JSON under `.artifacts/proof/` for the actual
revision, providers, outcomes, and reasons. Missing tools and unset commands
can leave advisory rows orange. The setup doctor's `configured`,
`action_needed`, and `unverified` states describe setup, not a passing scan.

The [sample application](https://github.com/ravisingh11/ai-software-toolkit-reference-app)
shows an installed consumer and language-specific examples for Java,
TypeScript, Python, PHP, and Scala. Its polyglot workflow is **manual and
optional**. Choose tools and adapters for your language; a TypeScript example
does not validate Java or another language automatically. Each repository owns
its activation, thresholds, and any later enforcement decisions.

See the [control status guide](../proof/control-status.md) for the full vocabulary.
