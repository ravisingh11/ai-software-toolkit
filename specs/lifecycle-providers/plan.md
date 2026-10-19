# Implementation plan

## Contract and trust

Keep nested evidence v2. Add a strict, bounded lifecycle receipt v1 with repository/PR/head/base, workflow SHA, run/attempt, configuration digest, one actual artifact digest, one canonical deployed-environment snapshot and exactly three subject documents. Producer receipts are untrusted until the collector independently validates GitHub run, artifact, trusted paths, every subject/control/provider binding, actual artifact bytes and late identity rechecks. Default-branch/manual execution and first-party verification targets only for initial adoption.

The artifact is a real built verification OCI archive containing the toolkit runtime/docs or reference Worker preview. This is explicitly not a production release image. Trivy scans its actual image, generates a nonempty CycloneDX inventory and scans that exact inventory. IaC scanning covers the actual verification Dockerfile/configuration and refuses empty scope. Separate GitHub attestation verifies exact artifact bytes, trusted workflow signer and source binding. Docker inspection and measured endpoint probes establish the environment receipt; passive ZAP and bounded soak use that same deployment.

Untrusted application build/runtime runs only in constrained Docker containers without host credentials, host Docker socket, writable source mounts, privileged capabilities or external runtime network access. Attestation uses a separate trusted job. Tool binaries/actions/images are immutable, checksummed and outside candidate configuration. Raw findings remain in CI artifacts; public output is bounded aggregate status, allowlisted provider names, subject/scope labels and validated same-repository run links.

## Delivery lanes

1. Producer lane: real tools, report validation, environment/deployment/runtime/soak probes, isolated fixture image and manual workflow; positive and defensive tests.
2. Collector lane: strict lifecycle receipt contract and GitHub import, bounded ZIP streaming/hash, exact trusted run and source binding; adversarial tests.
3. Core lane: catalog/provider/profile selections, evaluator companion applicability, scorecard CLI and public typed-scope display, installer/synchronization and documentation.
4. Integration: independent review, required complete validation, upstream PR/CI/merge; consumer supported install and two-phase trusted-runtime bootstrap; actual manual runs and fresh PR scorecards; browser proof of published outcomes.

## Activation

All new capabilities are optional, with explicit advisory opt-in; no existing core/GitHub profile defaults are strengthened. Polyglot triggers are unchanged. Missing/failed producer results remain visible. Bootstrap runtime before expecting trusted collection; do not relax provenance to make the installation PR pass. Existing unpatched Snyk and quota failures may block reference merge; preserve them while finishing independent work.

## Verification

Contract tests cover wrong SHA/digest/subject/control/provider, reruns, stale/duplicate/missing/oversized artifacts, unsafe targets/config/symlinks, denied API, partial scanner output, absent inputs and real failing probes. Run actual tools against owned fixtures and preserve reports. Then run all mandatory toolkit and reference validations, unchanged branch-rule receipts, exact-head CI, normal compare-and-swap merges and fresh trusted postmerge collection. A hosted workflow success alone never substitutes for provider outcomes or production evidence.
