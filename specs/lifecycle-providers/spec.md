# Optional lifecycle providers and exact-subject scorecards

## User outcome

A repository can opt into real container vulnerability, IaC, SBOM, artifact vulnerability, deployment-policy, dynamic application security and runtime-assurance producers. Existing attestation and soak producers feed subject-aware scorecards. The toolkit and reference application demonstrate real execution and accepted evidence, rather than reporting provider definitions as functioning services.

## Acceptance criteria

1. Every previously evidence-only capability has an executable built-in provider and a supported installation/activation path. Artifact provenance and soak have complete production and collection paths.
2. A completed tool run is required. Missing executable, credentials, database, project, target, reports or platform access stays blocked or missing; findings remain failed. No canned success and no empty unscannable target passes.
3. Commit, artifact and environment subjects remain distinct. Artifacts use a cryptographic digest of actual built bytes. Environment subjects bind the deployed revision, target, configuration and run identity. Companion evidence cannot satisfy another subject.
4. Hosted collection validates repository, exact PR/head/base, trusted workflow/runtime/configuration, run/attempt, unique non-expired artifact and every typed binding. Modified, stale, duplicate, partial or inaccessible evidence never inherits a pass.
5. Verification targets are first-party and explicitly scoped: toolkit documentation/runtime package and reference application's isolated Worker preview. Verification-environment evidence is labeled and is not presented as production deployment or whole-platform assurance.
6. Producers have positive, findings, malformed/partial-report, wrong-subject, stale, ambiguous, denied-access and failure-path regression tests. Actual hosted scanner/runtime executions validate the tool adapters; mocked fixtures alone are insufficient.
7. Both live PR scorecards show the new provider names, configuration/run links and actual typed outcomes, retaining unrelated missing evidence. Scorecard publication still requires a valid PR source binding.
8. Shared and consumer checks remain optional/advisory. No new required check, ruleset strengthening, hidden suppression or policy promotion. The polyglot workflow remains manual and optional.
9. Normal PRs are reviewed and merged only after CI completes without failures. Unrelated unpatched Snyk failures remain visible and can block a consumer merge; implementation work must still continue independently.

## Non-goals

- Provisioning paid vendor accounts, fabricating credentials or enabling every external integration.
- Claiming the toolkit is an application or that local previews are production releases.
- Unrequested production deployment, public active scanning, or probing third-party targets.
- Substituting workflow success for tool completion, typed evidence or provider provenance.

## Delivery evidence

Retain exact source/merge revisions, immutable tool versions, negative tests, hosted run artifacts, public snapshot source runs, browser verification, and unchanged optional/manual policy evidence. Report blockers separately from completed implementation.
