# Optional lifecycle verification fixture

This image packages the repository's installed Proof runtime and documentation.
At startup it executes the real evaluator with explicitly missing evidence;
`/health` reports the evaluated control count, advisory readiness and packaged
source revision. It is a verification fixture, not a production service.

The manual **Lifecycle Verification** workflow builds this image once, scans
its actual saved bytes with pinned Trivy, creates a nonempty CycloneDX SBOM,
and scans that same SBOM. It deploys the image on an internal Docker network
with a nonroot user, read-only filesystem, resource limits, no capabilities,
and no published ports. Passive ZAP, version/header/negative probes and a
short measured soak observe that deployment. Reports retain findings and
execution failures independently. A separate job attests the image and receipt
in one statement; only independent collection can verify provenance.

The default configuration is `proof/defaults/lifecycle.json`; installation
copies it to `.proof/lifecycle.json`. Repositories opt into each advisory
provider and manually dispatch with an open first-party PR number and its exact
current head SHA. The default build has no network access. A consumer requiring
public dependency downloads can explicitly select `build_network: "default"`
in trusted configuration; this is ordinary Docker build egress, not a registry
allowlist. Runtime networking remains internal in either case.

The 10-second workload is a short verification soak. It does not establish
production endurance, release approval, fleet security, or all-language scan
coverage. Missing tools, targets, reports, signatures and platform access remain
blocked or unverified. All checks remain optional, and the independent polyglot
workflow remains manual.
