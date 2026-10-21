# Optional artifact and verification-environment providers

The lifecycle providers run real tools against a built verification container
and its isolated runtime. They are manual and optional. They do not provision
production infrastructure or claim that a preview is a production release.

| Control | Provider | Subject and completion requirement |
| --- | --- | --- |
| Container vulnerability | `trivy-container-image` | Actual saved image bytes; completed Trivy vulnerability scan with a current database |
| IaC misconfiguration | `trivy-iac-config` | Exact commit's nonempty declared IaC inputs; completed Trivy configuration scan |
| Artifact SBOM | `trivy-artifact-sbom` | Same image; nonempty CycloneDX inventory with its own digest |
| Artifact vulnerability | `trivy-artifact-sbom-scan` | That exact SBOM; completed vulnerability scan without re-resolving source dependencies |
| Artifact provenance | `github-artifact-attestations` | Same image digest jointly signed with the receipt in one GitHub attestation |
| Deployment policy | `repository-deployment-policy` | Actual Docker deployment inspection against the configured verification isolation policy |
| Dynamic application security | `zap-baseline-local` | Actual first-party local service; completed pinned OWASP ZAP passive baseline |
| Runtime assurance | `repository-runtime-assurance` | That deployed container; exact version, security headers, negative probes and latency |
| Runtime soak | `repository-soak` | Same environment; measured bounded workload, duration and resource observations |

Trivy findings at HIGH or CRITICAL fail the relevant scan; unfixed findings are
not ignored. ZAP's noninformational alerts fail its baseline result. The baseline's warning exit (2) also covers informational alerts; a validated informational-only report passes this existing risk policy while retaining the raw report. An empty warning report, a FAIL exit without a noninformational finding, or a malformed report remains blocked. The pinned offline baseline uses the bundled release passive rules (pscanrules v76), verified through ZAP's local installed add-on listing before scanning. Raw and normalized inventory digests are bound into its signed evidence. Startup, missing or malformed inventory blocks the result; no beta-rule or authenticated active-scan coverage is claimed. Both inventory and baseline suppress online add-on updates with `-silent`. A completed
advisory workflow may therefore contain failed controls. Missing tools, current
vulnerability data, targets, inventories, reports or signatures never pass.
A passive baseline is not an authenticated or comprehensive active penetration
test. A short verification soak is not evidence of production endurance.

## Install and opt in

Refresh the supported installer first. It installs the manual
`lifecycle-verification.yml`, `.proof/lifecycle_producers.py`,
`.proof/lifecycle_contract.py`, `.proof/collect_lifecycle_evidence.py` and a
preserved `.proof/lifecycle.json` starter configuration. Source implementations
are `tooling/lifecycle_producers.py`, `tooling/lifecycle_contract.py` and
`tooling/collect_lifecycle_evidence.py`.

The starter targets the toolkit's [runtime/documentation fixture](../../examples/lifecycle/README.md).
A consumer must supply its own pinned Dockerfile, build-context allowlist,
actual application startup and health/authentication probes. It must not call
that generic documentation fixture its application. An absent fixture stays
missing. Merge the trusted runtime and fixture configuration before expecting
accepted evidence from a PR that changes them.

Use the existing configuration entrypoint for explicit advisory activation:

```sh
python3 .proof/configure.py --operation change --set iac-misconfiguration=advisory
python3 .proof/configure.py --operation release \
  --set container-vulnerability=advisory --set artifact-sbom=advisory \
  --set artifact-vulnerability=advisory --set artifact-provenance=advisory \
  --set deployment-policy=advisory --set dynamic-application-security=advisory \
  --set runtime-assurance=advisory --set runtime-soak=advisory
```

Review and merge those choices. Then opt the repository's PR collector into
lifecycle import with both non-secret GitHub variables
`PROOF_LIFECYCLE_ENABLED=true` and `PROOF_SCORECARD_STAGE=lifecycle`.
Ordinary PR development scorecards do not import release/environment companions;
those checks appear as relevant later until you request a lifecycle evaluation.
No new required checks or branch rules are added. The existing Core and GitHub
profile defaults stay unchanged. Consumers retain their own activation and
enforcement decisions. The polyglot workflow remains manual and optional.

Dispatch **Lifecycle Verification** from the default branch with an open,
same-repository PR number and its exact current head SHA:

```sh
gh workflow run lifecycle-verification.yml --ref main \
  -f pull-request-number=123 -f revision=FULL_40_CHARACTER_PR_HEAD
```

Use the actual default branch if it is not `main`. Do not substitute a branch
name for the exact revision or rerun an old attempt. The collector refuses
ambiguous runs and attempts other than the first. After the manual run finishes,
a fresh PR scorecard event imports its receipt. Preserve an initial missing
snapshot as historical evidence; it is not retrospectively changed into a pass.

## Execution boundary

BuildKit/buildx is required; legacy Docker build fallback is refused. The
candidate must be a clean checkout at the declared revision. Its code runs only
inside Docker, never as a host setup script. The Dockerfile and toolchain are
trusted-base configuration and external base images must use digests.
`build_network` is explicitly `none` or Docker's `default` network; the latter
permits outbound dependency retrieval during the sandboxed build and is not a
registry-only egress restriction. It does not grant host networking, credentials,
SSH forwarding or host mounts.

Runtime is non-root with a read-only root filesystem, dropped capabilities,
no-new-privileges, CPU/memory/PID/tmpfs limits and an internal Docker network.
No candidate container receives a host Docker socket, provider token, secret or
writable source mount. Probes and ZAP run against the same internal target.
Logs, execution time, image size and receipt archives are bounded. The signing
job never executes candidate code; it validates the receipt and image before
attestation. Tool, action and base-image pins are reviewed source configuration.

## Exact-subject collection

Evidence remains nested Proof v2. A strict lifecycle receipt v1 binds repository,
PR, head/base, trusted workflow SHA, run/attempt, canonical configuration digest,
actual artifact digest and the digest of a measured environment snapshot. Its
three documents remain separate: `git-commit`, `artifact`, and `environment`.
The scorecard evaluates artifact/environment companions with release lifecycle
applicability beside the PR's commit evidence; a commit result cannot satisfy
an artifact or runtime control.

GitHub attests both the actual `image.tar` and `lifecycle-receipt.json` in the
same signed statement. The collector verifies the downloaded receipt bytes
using GitHub CLI, exact repository/workflow/source/signer/ref, certified run
identity and verified timestamps. It requires that very statement to contain
the image digest too. This binds actual image bytes without downloading a large
image into every scorecard run. Separate signatures cannot be combined to
manufacture that association.

The collector independently checks current PR/head/base, the unique completed
manual run, immutable trusted source/configuration, unique nonexpired receipt
and image artifacts, their API digests, and late changes. Wrong, stale, edited,
partial, inaccessible or unprovable evidence remains explicit `not_run`.
Cryptographic provenance acceptance does not convert failed tool results into
passes. Only artifact provenance is derived from successful signature checking.
Raw reports remain in CI artifacts; the public scorecard uses bounded results,
validated same-repository run links, and explicit **Verification artifact** /
**Verification environment** labels. It makes no production assurance claim.

## Verification status

Unit fixtures establish defensive parsing and subject separation, not real tool
or hosted-service operation. Record source-bound hosted runs and published
snapshots only after they actually complete. Local exploratory runs from an
uncommitted worktree, blocked ZAP downloads, and synthesized attestation JSON
must not be described as accepted hosted evidence.
