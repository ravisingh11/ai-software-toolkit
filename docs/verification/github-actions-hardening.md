# Repository Actions hardening record

This record describes settings verified for `ravisingh11/ai-software-toolkit`
on 2026-10-21. It is not a requirement for consuming repositories. The repository
remains public and welcomes external pull requests. Toolkit checks remain
optional according to their existing policy; polyglot verification remains manual.

## Applied settings

- Actions must use full commit SHAs.
- Only the 14 action paths below are allowed. GitHub-owned actions and verified
  creators have no blanket exception. The version wildcard permits reviewed SHA
  updates; the separate SHA requirement rejects tag references.
- Fork workflow approval is required for all external contributors. This setting
  was already enabled and was preserved. It does not make `pull_request_target`
  safe or replace its separate trust boundary.
- Future releases are immutable. Prepare a draft, attach and verify all assets,
  checksums and manifests, then publish. Existing published releases were not
  modified. Corrections to an immutable release require a new version.
- Default workflow token permissions remain read-only, and workflows cannot
  approve pull requests. Existing required checks and maintainer review rules
  were preserved.

Allowed action paths (each with `@*`, subject to SHA enforcement):

```text
SonarSource/sonarqube-quality-gate-action
SonarSource/sonarqube-scan-action
actions/attest
actions/checkout
actions/configure-pages
actions/dependency-review-action
actions/deploy-pages
actions/download-artifact
actions/upload-artifact
actions/upload-pages-artifact
github/codeql-action/analyze
github/codeql-action/autobuild
github/codeql-action/init
sigstore/cosign-installer
```

The static inventory followed pinned composite action dependencies, including
CodeQL autobuild and artifact upload dependencies. It inspected 15 distinct
pinned action references across installed workflows, templates and demo copies;
no unpinned references were found in that inventory. Downloaded binaries and
shell commands are outside GitHub's action allowlist enforcement.

## Event policies

Active policy 8224 blocks `pull_request_target` outside the paths below while
preserving other supported events. Active policy 8225 allows
`pull_request_target`, `workflow_dispatch`, and `workflow_call` for these paths:

```text
.github/workflows/ai-pr-review.yml
.github/workflows/change-scope.yml
.github/workflows/dependabot-verification.yml
.github/workflows/fossa.yml
.github/workflows/github-secret-protection.yml
.github/workflows/pr-metadata.yml
.github/workflows/proof-scorecard.yml
.github/workflows/snyk.yml
```

These exceptions preserve existing trusted automation, including inactive
optional providers; they do not activate those providers. New privileged workflow
paths require a fresh review and an explicit policy change. No actor restriction
was added that would exclude external contributors or Dependabot from normal CI.

## Credential and privilege audit

The reviewed source revision was
`bfa396d2483ffb9c1d2ab8389a47e4a005a01447`.

| Surface | Observed boundary |
| --- | --- |
| PR metadata and change scope | Trusted base/workflow runtime inspects candidate metadata; change scope has write permissions for its cancellation/reporting responsibilities. |
| Snyk, FOSSA and AI review | Trusted runtime is separate from candidate data; fork provider credentials are withheld. Provider keys are passed to provider steps. Candidate installation/build is not part of the data-only scanners. |
| Secret protection and Dependabot verification | Trusted API probes use the settings credential without executing candidate code. |
| Scorecard | Trusted collection/rendering uses candidate evidence as data; the configuration token belongs to the trusted collector. |
| Pages | Trusted publication consumes evidence; the deployment environment is restricted to main. |
| Lifecycle signing | Manual dispatch validates the default branch and PR revision; signing is separated into a fresh privileged job. |
| Artifact provenance | Release/manual execution can build reviewed release source with OIDC attestation permissions. Maintainers must treat dispatch ref selection and the configured build command as privileged. |
| Sonar | Uses ordinary PR semantics, where fork secrets are withheld. When configured, the token is job-scoped and the scanner reads candidate configuration; this remains a broader credential surface than the data-only providers. Review its configuration and credential scope before activation. |

No credential-exfiltration path was confirmed in this bounded review. This is
not proof that credentials have never leaked. The audit did not retrieve secret
values, perform a complete historical secret scan, test malicious fork payloads,
or audit all third-party action source. Main-only environments do not by
themselves make privileged PR workflows safe, since those workflows execute in
the base repository context. Review future changes to every exception carefully.

## Verification and maintenance

Settings were read back after mutation. Workflow defaults and the repository
ruleset list matched their pre-change snapshots; public visibility was verified.
No additional local tests were run. A documentation PR supplies a normal CI run
under the new settings; its actual checks must be reviewed before merging.

When adding an action, inspect nested dependencies before extending the
allowlist. When adding a privileged event workflow, review candidate execution,
secret scope, token permissions and publication paths before changing an event
policy. Keep draft release assets complete before publication.

See GitHub's documentation for [workflow execution policies](https://docs.github.com/en/actions/how-tos/administer/control-workflow-execution)
and [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).
