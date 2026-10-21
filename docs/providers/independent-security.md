# Independent provenance and Trivy setup

Start with the one check you need. These workflows do not require the lifecycle
fixture, an application deployment, ZAP, or a soak run. They need no vendor
account or additional provider secret. Check adoption and enforcement remain
optional; advanced lifecycle verification and polyglot examples remain manual.

Refresh the toolkit installation using the [installation guide](../install.md)
and review the diff. The installer ships `artifact-provenance.yml`, `trivy.yml`,
`.proof/prepare_release_attestation.py`, and `.proof/run_trivy.py`. The canonical
helpers are `tooling/prepare_release_attestation.py` and `tooling/run_trivy.py`.
Merge the workflows and helpers into the trusted default branch before use.
Workflow permissions, pinned tools, and required GitHub checks remain explicit.

## Verify exact published release assets

Run **Artifact Provenance** with only a release tag:

```sh
gh workflow run artifact-provenance.yml --ref main -f release-tag=v2.1.1
```

Use your repository's actual default branch and release tag. Leave
`artifact-path` empty for this mode. Optionally select files with
`-f 'asset-pattern=*.zip'`; the default is every uploaded release asset.
To run automatically for future published releases, explicitly opt in:

```sh
gh variable set PROOF_ARTIFACT_PROVENANCE_ENABLED --body true
```

The helper downloads actual uploaded bytes, verifies their GitHub SHA-256
digests and sizes, and checks the release and tag again before signing. It
refuses draft releases, missing digests, empty selections, unsafe filenames,
more than 100 files, and more than 4 GiB in total. It never rebuilds or executes
the downloaded assets and never edits an immutable release.

This produces a **release-verification attestation**, not a claim that the
original build happened in this workflow. The custom predicate records the
release, source commit, and exact file hashes. Download its predicate and signed
bundle from the `release-verification-*` Actions artifact. Verify a downloaded
asset with GitHub CLI:

```sh
gh attestation verify ./ai-toolkit.pyz --repo OWNER/REPO \
  --signer-workflow OWNER/REPO/.github/workflows/artifact-provenance.yml \
  --predicate-type https://github.com/ravisingh11/ai-software-toolkit/attestations/release-artifact-verification/v1
```

Inspect the verified predicate's tag, commit, and asset identity too. A valid
signature on a publication record does not establish the original build inputs.
GitHub's attestation feature availability and token/organization policies still
apply. The workflow uses scoped GitHub OIDC and attestation permissions.

## Build provenance instead

For native build provenance, keep the existing independent build mode. Supply
your real build command and its artifact path or glob:

```sh
gh variable set PROOF_ARTIFACT_BUILD_COMMAND --body 'python3 tooling/build_archive.py'
gh variable set PROOF_ARTIFACT_PATH --body 'dist/ai-toolkit.pyz'
gh workflow run artifact-provenance.yml --ref main -f artifact-path=dist/ai-toolkit.pyz
```

Those example commands suit the toolkit itself; use your application's build
command and reviewed workflow ref. Build mode runs the configured command and
uses GitHub's native SLSA provenance predicate. The attested output is retained
in the `provenance-artifacts-*` Actions artifact. It is privileged maintainer-owned
execution. A rebuild can have different bytes from a published asset; do not
claim a published file is covered unless its digest matches the attestation.
The build mode remains compatible with existing configured consumers.

## Run one Trivy scan

Choose **Trivy** in Actions, or dispatch just the desired scan:

```sh
gh workflow run trivy.yml --ref main -f scan=dependencies -f path=.
gh workflow run trivy.yml --ref main -f scan=iac -f path=infra
# Replace this with your own public image's full digest:
gh workflow run trivy.yml --ref main -f scan=image -f image=REGISTRY/IMAGE@sha256:FULL_64_CHARACTER_DIGEST
```

Dependency and IaC scans read repository files without installing packages or
building the application. Image scans read the supplied public registry image
by digest, produce its vulnerability report and CycloneDX SBOM, and do not
start a container. No Dockerfile or application probes are required for these
standalone scans. Private registry authentication is outside this starter.

The workflow installs checksum-pinned Trivy 0.76.0. Vulnerability scans require
a database updated within 48 hours. HIGH or CRITICAL findings fail the job,
including unfixed vulnerabilities. Tool errors, stale data, empty inventories,
missing inputs, malformed reports and mismatched IaC counts cannot pass. IaC
requires completed rule evaluations. Regular source subtrees are required;
symlink-containing targets are refused. Scanner reports and version metadata
are retained as Actions artifacts, including on failure when available.
The helper runs Python in isolated mode to prevent source files from shadowing
standard-library imports. Repository-local Trivy configuration and ignore files
are not loaded; inline
IaC exceptions still belong to the reviewed input and remain in Trivy reports.
A passing scan is not a claim of zero vulnerabilities or full tool coverage.

## Optional PR checks and scorecard selection

No Trivy scan runs on PRs until you explicitly enable the desired check:

```sh
gh variable set PROOF_TRIVY_DEPENDENCIES_ENABLED --body true
gh variable set PROOF_TRIVY_IAC_ENABLED --body true
# Optional source subtree for PR scans (manual runs have their own path input):
gh variable set PROOF_TRIVY_PATH --body .
```

These are separate opt-ins. The native checks are **Trivy / Dependencies** and
**Trivy / IaC**. They are not added to branch protection. To use one as a Proof
provider, explicitly select it and choose an advisory mode:

```sh
python3 .proof/configure.py --select-provider dependency-vulnerability=trivy-repository-vulnerabilities
python3 .proof/configure.py --operation change --set dependency-vulnerability=advisory
python3 .proof/configure.py --select-provider iac-misconfiguration=trivy-repository-iac
python3 .proof/configure.py --operation change --set iac-misconfiguration=advisory
```

Selection replaces that capability's previous authoritative provider; review
and commit it deliberately. The provider labels are **Trivy Repository
Dependencies** and **Trivy Repository IaC**. Collection validates the exact PR
head, GitHub Actions identity, trusted workflow and helper paths. Changes to
those trusted files need to be merged before a later PR can claim their new
results. Manual scans remain available as reports; a manual run is not silently
accepted as evidence for a different PR or commit.

## Keep the evidence scopes separate

Standalone image scans and release-verification attestations are directly
usable reports and signatures, bound to an image digest or release files.
They do not turn artifact/environment controls in a PR scorecard green.
The existing `github-artifact-attestations` and lifecycle Trivy selections
still require the signed, exact-subject lifecycle receipt. This avoids treating
a repository scan as proof of a built image or a release signature as proof of
an environment. Existing policies, schemas and evidence contracts are unchanged.

Use [advanced lifecycle verification](lifecycle.md) only when you also want
image build, deployment policy, ZAP, runtime probes and soak evidence in the PR
scorecard. Its workflow remains `workflow_dispatch` only and is independent of
these two starters. A workflow template or fixture does not establish live
consumer verification; inspect a real run and its source-bound output before
claiming successful adoption.
