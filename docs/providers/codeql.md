# GitHub CodeQL setup and evidence

CodeQL advanced setup and GitHub default setup are distinct producers. Choose one
explicitly; the toolkit does not enable default setup, scan extra languages,
change required checks, or switch existing provider selections automatically.
All checks remain optional to adopt and repository owners choose enforcement.

## Advanced setup

The existing `github-codeql` provider expects the repository-owned
`.github/workflows/codeql.yml`, unchanged from the trusted base, with its declared
GitHub Actions check. Its provenance checks remain unchanged. Set
`PROOF_CODEQL_LANGUAGES` only when using this advanced workflow.

## Default setup (optional)

After upgrading the installed toolkit runtime, select:

```sh
python3 .proof/configure.py --select-provider deep-sast=github-codeql-default-setup
```

Enable GitHub default setup in the repository's code-scanning settings separately.
Keep the duplicate advanced workflow inactive by leaving
`PROOF_CODEQL_LANGUAGES` unset. The scorecard collector requires read access to
Actions, checks, PRs, contents, and security events; the installed scorecard
workflow includes `security-events: read`. No additional secret or write access
is needed. Missing permissions produce missing evidence, never a pass.

This GitHub.com provider requires independent API proof, rather than accepting a
check merely named **CodeQL**:

- The GitHub Advanced Security aggregate check must have the expected immutable
  app identity, exact repository/revision, and a terminal outcome.
- The configured GitHub-managed workflow must be active at
  `dynamic/github-code-scanning/codeql`, with the exact workflow/run identity,
  PR number, PR head/base, and `refs/pull/<number>/head` association.
- Every configured canonical language must have a successful, completed
  `Analyze (...)` job from the GitHub Actions app, bound to that run and suite.
  Aliases such as JavaScript and TypeScript count as one JS/TS analysis.
- CodeQL analyses must match the exact head/ref, managed analysis key/category,
  language, and matching job execution window, without analysis errors or warnings.
- Setup configuration must predate the run. The `.github/codeql` model/configuration
  tree must match the trusted base, including absence-to-presence changes.
  Organization-supplied custom CodeQL properties are not supported by this
  provider and remain unverified when present or unreadable.

API denial, malformed or incomplete pagination, unknown languages, missing or
skipped analyses, configuration drift, and ambiguous duplicate evidence remain
**Unverified**. First-attempt managed runs are supported; reruns without a
provable attempt-level analysis binding remain unverified. A successful aggregate
check alone is insufficient, because it can complete before all language uploads.
Verified negative aggregate outcomes remain negative. Refreshing a scorecard does
not enable scans or change this contract.

The public provider label links to the evaluated configuration, and its reported
managed run links to available same-repository evidence. Unavailable finding
counts are not invented. Recognizing default setup does not fill unrelated
coverage, secret-protection, dependency-remediation, or other evidence gaps.
The reference app's polyglot workflow remains manual and optional.

GitHub documents [default setup](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configure-code-scanning),
[custom repository properties](https://docs.github.com/en/code-security/concepts/code-scanning/repository-properties),
and [model packs/configuration changes](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/manage-your-configuration/edit-default-setup).
