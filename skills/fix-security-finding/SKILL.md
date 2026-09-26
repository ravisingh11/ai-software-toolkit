---
name: fix-security-finding
description: "Validate a security finding from a scanner or review, implement the minimal remediation, add regression coverage, and document residual risk without exposing secrets. Use when Semgrep, CodeQL, Gitleaks, Snyk, a security review, or ai-toolkit check reports a security defect to fix."
---

# Fix Security Finding

Confirm the finding is real, fix the root cause, and prove it stays fixed.
`security-audit-lite` finds and rates issues; this skill remediates one. Use
the shared verification conventions from `_shared-project-ops` when the
repository has them installed.

## Inputs

- The finding: tool, rule or CWE, file and line, severity, and the evidence
  link (a scanner result, a `pr-review` finding JSON, or an `ai-toolkit check`
  row with its reason code).
- The repository's security policy (`SECURITY.md`, `policies/security.md`
  when present) and the affected component's threat model if documented.

## Permitted changes

- The vulnerable code path and its direct callers.
- New regression tests that exercise the previously vulnerable input.
- Dependency bumps only when the finding is a vulnerable dependency and the
  fix is a patch or minor upgrade; otherwise hand off to `dependency-upgrade`.
- Scanner configuration only to add a justified, narrowly scoped, documented
  suppression after the user agrees the finding is a false positive.

Not permitted: committing, printing, or logging secret values; rotating
credentials on the user's behalf; disabling a rule repository-wide; or
suppressing a true positive.

## Method

1. Reproduce or trace the finding to a concrete attacker-controlled input and
   an impact. If it is not reachable, record why and propose a suppression
   rather than a code change.
2. Choose the remediation that removes the vulnerability class (parameterized
   query, allow-list, safe API) over one that patches the instance.
3. Write a regression test with the malicious input first; confirm it fails
   before the fix and passes after.
4. Re-run the reporting scanner locally when available (`.guardrails/scan.py`
   or the tool itself) so the same rule no longer fires.
5. For leaked secrets: remove them from the tree, tell the user which
   credential must be rotated, and never paste the value anywhere.

## Stop conditions

Stop and report when the fix changes a public interface or data format,
when the finding lives in vendored or generated code, when remediation
requires a credential rotation only the user can perform, or when the
scanner cannot be rerun and the fix cannot be proven.

## Verification

- Regression test fails on the old code and passes on the new code.
- The originating scanner or check reports the finding resolved for the new
  revision (`ai-toolkit check` row `passed`, or the finding absent).
- Existing tests still pass.

## Outcome report

```text
Finding: <tool / rule / location / severity>
Confirmed: <yes, with reachable input | false positive, with reason>
Remediation: <what changed and why it removes the class>
Regression test: <path and what it proves>
Residual risk: <what remains, credentials to rotate, follow-ups>
Verified: <commands run and results>
```
