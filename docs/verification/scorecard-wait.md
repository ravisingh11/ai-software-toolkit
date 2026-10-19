# Optional-provider scorecard verification

## Toolkit repository

[PR #107](https://github.com/ravisingh11/ai-software-toolkit/pull/107)
was merged after CI passed. Its reviewed head was
`a99dd9712df9a94086b5412086b6b7103fab9bc0`; the squash merge and updated trusted
runtime are `c46a7c263ea7667ea9c0fe061b628afd51ed6507`. Their source trees match.

| Evidence | Recorded result |
| --- | --- |
| [Pre-fix trusted scorecard](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39182072566) | Collection took 1,834 seconds (30m 34s). |
| [Updated trusted scorecard](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39184673806) | Collection took 19 seconds; ORANGE / allow, 14/16 advisory controls passed, zero enforced controls. |
| [Unit tests](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39182074311) | 888 cases: 887 passed, one skipped. |
| [Changed-code coverage](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39182074312) | All seven measured changed executable lines covered (100%); selected threshold remained 90%. |
| [Repository and documentation checks](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/39182074211) | Passed. |

Both timed scorecards evaluated the same reviewed PR head and original base
`fa02ab51dcb53c6297c85f5bce641771b8eee7a5`. The updated report used the merged
trusted runtime; it is not a separate full test run of the squash commit.
The dependency-vulnerability row remained advisory **ORANGE / no result**,
with the reason: “Waiting is disabled for this provider; its check did not
report this revision.” The other advisory gap was PR change scope. Missing
results were not converted into passes.

## Configuration and scope

Explicit `false` values for `SNYK_CODE_ENABLED` and
`SNYK_OPEN_SOURCE_ENABLED` are polling hints for absent provider checks.
Comparison is case-insensitive, matching the Snyk jobs. Unset/empty values
retain normal polling. Already queued or running checks still wait; provider
provenance and reported failures retain their usual validation. Missing
selected enforced evidence still blocks. Refresh the runtime and scorecard
workflow together using the supported installer, then merge before verifying
the updated trusted default-branch workflow. See [Snyk configuration](../providers/snyk.md).

All checks remain optional to adopt. Each repository owns provider selection,
thresholds, policy modes, workflow triggers, and branch rules. This fix changes
polling, not enforcement or credential configuration.

## Reference application

[Fieldnotes](https://github.com/ravisingh11/ai-software-toolkit-reference-app)
maintains its own [adoption record](https://github.com/ravisingh11/ai-software-toolkit-reference-app/blob/main/docs/toolkit-adoption.md)
and [verification index](https://github.com/ravisingh11/ai-software-toolkit-reference-app/blob/main/docs/verification/README.md).
Its consumer-owned Snyk workflow and policy selection are separate from the
canonical provider template. A successful consumer scan does not implicitly
activate a Proof provider.

Its Java, TypeScript, Python, PHP, and Scala examples use language-specific
tools. The polyglot workflow runs only by manual dispatch and is not required
for merging. Coverage measurements cover the selected examples, not the full
application; CI evidence is separate from deployment evidence.

The [2026-10-18 manual five-language run](https://github.com/ravisingh11/ai-software-toolkit-reference-app/actions/runs/39185524558)
passed all 30 stages and 115 conformance cases (23 per language) at source
`2f9ac1fcce571ed54d51b7fdf2aa50a8aadbe3b9`, with the installed runtime and
polyglot helpers pinned to `c46a7c263ea7667ea9c0fe061b628afd51ed6507`.
It used comparison base `2932827657d4758cdf030ab693239cfb2a23e258` and a
repository-selected 90% threshold. Changed-line coverage was Java 100%,
TypeScript 93%, Python 100%, PHP 100%, and Scala 92% in the example scopes.
This branch run verifies the pinned examples; it does not attest a deployment
or a later documentation commit.
