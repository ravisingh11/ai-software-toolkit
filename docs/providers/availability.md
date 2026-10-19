# Provider implementation inventory

This inventory covers every built-in provider in
[`policies/provider-config.yaml`](../../policies/provider-config.yaml).
It describes shipped implementation, not a claim that a repository has the
provider running. Every check remains optional; selecting a provider does not
activate a control or change GitHub branch protection.

Verify these separately:

1. **Implemented:** the producer and collector path exist and match the contract.
2. **Installed:** the required workflow, runtime, or platform integration exists
   in the consuming repository at the evaluated revision.
3. **Configured:** required commands, settings, credentials, and service access
   are available to that run. A secret name alone does not prove validity.
4. **Observed:** a real run produced provenance-checked evidence for the exact
   subject. Preserve its actual passed, failed, blocked, or missing result.

Neither a registry entry nor a successful workflow proves all four. The public
scorecard's provider column describes selection only. Its source run and
individual result supply the snapshot's evidence; an older snapshot does not
prove current activation. `Not configured`, `Not activated`, and `Unverified`
remain distinct.

## Complete built-in inventory

Paths below are toolkit source files, not proof of installation in a consumer.
PR check collection is implemented in
[`tooling/github_evidence.py`](../../tooling/github_evidence.py).
Repository command bindings can come from `.proof/commands.json` as well as
the named `PROOF_*` variables; the configured command must do the actual work
in either case.

| Provider ID | Shipped producer or integration boundary | What still has to be supplied or verified |
| --- | --- | --- |
| `repository-validator` | [`repository-validation.yml`](../../workflows/repository-validation.yml), repository/documentation/ground-truth validators | Repository document mappings and validator inputs; actual exact-head checks. One provider serves three controls. |
| `repository-change-scope` | [`change-scope.yml`](../../workflows/change-scope.yml), trusted scope validator and run-bound evidence | Installed trusted workflow, configured limits, complete matching evidence. Oversize changes remain visible. |
| `repository-pr-metadata` | [`pr-metadata.yml`](../../workflows/pr-metadata.yml), trusted metadata validator and run-bound evidence | Repository title/body rules and current PR metadata. |
| `repository-format-and-lint` | [`format-and-lint.yml`](../../workflows/format-and-lint.yml) command runner | A real `PROOF_FORMAT_LINT_COMMAND`. The toolkit does not select a universal linter. |
| `repository-migration-validation` | [`migration-validation.yml`](../../workflows/migration-validation.yml) command runner | A real `PROOF_MIGRATION_VALIDATION_COMMAND`, including an explicit no-migrations validator where applicable. |
| `repository-build` | [`build.yml`](../../workflows/build.yml) command runner | A real `PROOF_BUILD_COMMAND` and required setup. |
| `repository-unit-tests` | [`unit-tests.yml`](../../workflows/unit-tests.yml) command runner | A real `PROOF_UNIT_TEST_COMMAND` and meaningful repository tests. |
| `repository-changed-code-coverage` | [`changed-code-coverage.yml`](../../workflows/changed-code-coverage.yml) command runner | `PROOF_CHANGED_COVERAGE_COMMAND`, language-specific instrumentation, and the correct comparison base. Acceptance tests alone do not supply line coverage. |
| `semgrep-ce` | [`semgrep-ce.yml`](../../workflows/semgrep-ce.yml), shipped rules and safe/unsafe fixtures | Supported runtime, rule execution and exact-head evidence. Custom rules are not a universal deep-SAST implementation. |
| `gitleaks` | [`gitleaks.yml`](../../workflows/gitleaks.yml), pinned Gitleaks CLI | Actual history scan and exact-head evidence. This does not enable GitHub push protection. |
| `github-codeql` | [`codeql.yml`](../../workflows/codeql.yml), advanced CodeQL workflow | `PROOF_CODEQL_LANGUAGES`, supported languages/build setup, GitHub access, and a completed analysis. Do not run conflicting advanced uploads alongside default setup. |
| `github-codeql-default-setup` | GitHub-managed dynamic workflow; dedicated strict collector | Configured GitHub default setup, read access to analysis evidence, explicit provider selection, and complete exact-head analyses for every configured language. No toolkit workflow template is shipped. See [the contract](codeql.md). |
| `github-dependency-review` | [`dependency-review.yml`](../../workflows/dependency-review.yml), GitHub dependency-review action | GitHub dependency data/access and a completed PR comparison. This is not a full dependency inventory scan. |
| `github-secret-protection` | [`github-secret-protection.yml`](../../workflows/github-secret-protection.yml), settings probe and run-bound evidence | `SECURITY_SETTINGS_TOKEN` with sufficient access and actual platform secret scanning/push-protection settings. A workflow file alone does not enable them. |
| `github-dependabot` | [`dependabot-verification.yml`](../../workflows/dependabot-verification.yml), platform settings probe | `SECURITY_SETTINGS_TOKEN` and actual alerts/automated security-fixes settings. It does not inspect `.github/dependabot.yml` or prove every vulnerability has been remediated. |
| `github-artifact-attestations` | [`artifact-provenance.yml`](../../workflows/artifact-provenance.yml), GitHub attestation action | Real release artifact/build and permissions. The optional [lifecycle workflow](lifecycle.md) signs the actual image and receipt, and its typed collector validates that joint signature. Standalone release-job success alone is not a PR scorecard pass. |
| `sonarqube` | [`sonar.yml`](../../workflows/sonar.yml), scanner and asynchronous quality-gate wait | Host/project/token and a real completed gate. Changed-code coverage additionally requires coverage input and an appropriate server gate; the collector does not inspect gate conditions. See [limitations](sonarqube.md#install). |
| `qa-bootstrap-workflow` | Evidence contract for consumer-generated `QA / report`; [`qa-bootstrap` skill](../../skills/qa-bootstrap/SKILL.md) | Generate and verify the app-specific executor/reporter. **No fixed QA workflow or universal application test implementation is shipped.** PR-authored execution stays advisory. |
| `snyk-code` | [`snyk.yml`](../../workflows/snyk.yml), [`provider_adapter.py`](../../tooling/provider_adapter.py): `snyk code test` | Explicit activation, isolated credential, supported project, service access/quota and exact-head run-bound evidence. |
| `snyk-open-source` | [`snyk.yml`](../../workflows/snyk.yml), adapter: `snyk test` | Explicit activation, isolated credential and supported lockfiles. Credentialed data-only scans do not run dependency resolution; unsupported inputs remain missing. Real findings remain failed. |
| `semgrep-app` | External Semgrep App integration; collector recognizes its declared app check | Consumer-owned platform setup and exact-head `Semgrep` check. **No toolkit scanner workflow is shipped.** The collector checks app slug, check name and revision, not an immutable app ID or the platform's rule set/deep-analysis configuration. |
| `fossa` | [`fossa.yml`](../../workflows/fossa.yml), adapter: `fossa analyze` followed by `fossa test` | Explicit activation, isolated credential, enabled service-side security/license policies and completed evaluation. The collector does not inspect those policies; upload alone cannot pass. |
| `ai-engineering-adapter` | [`ai-pr-review.yml`](../../workflows/ai-pr-review.yml), trusted command and role-result wrapper | `AI_REVIEW_COMMAND`, its dependencies and isolated credential. The real [Claude reference reviewer](../../tooling/ai_review_claude.py) is shipped source but is not automatically installed. |
| `codex-github-review` | External Codex review integration; collector recognizes exact-head bot reviews | Connect/enable Codex reviews and verify the configured bot identity. **No toolkit reviewer workflow is shipped.** A `COMMENTED` review proves review occurrence, not absence of findings. |
| `ai-qa-adapter` | Shared AI review workflow, QA role-result wrapper and Claude reference reviewer | The same manual reviewer installation, command, credential and role-specific exact-head evidence; not an activated reviewer by default. |
| `ai-security-adapter` | Shared AI review workflow, security role-result wrapper and Claude reference reviewer | The same manual reviewer installation, command, credential and role-specific exact-head evidence; not an activated reviewer by default. |
| `ai-repository-standards-adapter` | Shared AI review workflow, repository-standards role-result wrapper and Claude reference reviewer | The same manual reviewer installation, command, credential and role-specific exact-head evidence; not an activated reviewer by default. |
| `repository-soak` | [`soak.yml`](../../workflows/soak.yml), scheduled/manual command runner | Consumer-owned workload, duration/threshold measurements and `SOAK_COMMAND`. The optional [lifecycle workflow](lifecycle.md) now measures a bounded verification workload and imports exact environment-subject evidence. The standalone command template is not a universal endurance-test implementation. |

## Additional lifecycle providers

The seven former evidence-only capabilities now have built-in producers and
typed collection. They remain explicitly opt-in, not new Core/GitHub profile
requirements. See [activation, execution limits and provenance](lifecycle.md).

| Provider ID | Real producer | Remaining prerequisite |
| --- | --- | --- |
| `trivy-container-image` | Pinned Trivy scan of actual saved image | Build the owned verification artifact; current database and completed report |
| `trivy-iac-config` | Pinned Trivy configuration scan | Nonempty supported IaC inputs for the exact commit |
| `trivy-artifact-sbom` | Pinned Trivy CycloneDX generation | Nonempty inventory for the actual image, not just a source manifest |
| `trivy-artifact-sbom-scan` | Pinned Trivy scan of that exact inventory | Matching SBOM digest, current database and complete findings |
| `repository-deployment-policy` | Actual Docker isolation/deployment inspection | A real scoped verification deployment; does not claim production approvals |
| `zap-baseline-local` | Pinned OWASP ZAP passive baseline | Owned internal application endpoint and completed target-bound report |
| `repository-runtime-assurance` | Version, header, negative-request and resource probes | Exact deployed image/revision and measured environment snapshot |

The completed artifact-provenance and soak collection paths use the same
optional lifecycle receipt. Actual hosted execution and accepted publication
must still be verified for each consumer; neither the new definitions nor
unit fixtures establish that verification.

## Verify an installation

Use `.proof/doctor.py --github OWNER/REPO` for supported setup diagnostics and
inspect the actual workflows, commands, GitHub settings, provider activation
variables and source reports. Doctor is a setup diagnostic, not an end-to-end
scan of every catalog provider. Its credential-name checks do not authenticate
to each vendor or prove organizational integration settings.

Record live external-provider results in the [verification ledger](verification.md)
only when its stated exact-revision requirements have been met. Existing
unverified rows remain unverified; static fixtures and local broad-token
replays must not be relabeled as hosted workflow verification. Keep the optional
polyglot workflow manual in repositories that adopt that example, and preserve
language-specific setup requirements.
