---
name: address-pr-findings
description: "Triage consolidated pull-request review findings, resolve the actionable P0-P2 items with verified changes, and explain any accepted or deferred risk. Use after a code, security, QA, or repository-standards review has produced findings that need to be worked off."
---

# Address PR Findings

Turn review findings into verified fixes or explicit decisions. `code-review`
produces findings; the finding schema, severities, statuses, and dedupe rules
live in the toolkit's pr-review references (finding-format.md and
dedupe-rules.md). This skill consumes them.

## Inputs

- The findings, in the pr-review finding-format shape (id,
  severity `P0`-`P3`, status, evidence, fixPlan, verification).
- The pull request diff and the repository's validation commands.

## Permitted changes

- Code, tests, and documentation needed to resolve a finding.
- Updating each finding's `status` (`resolved`, `accepted`, `deferred`,
  `needs-context`) and its `verification` block in the findings file or PR
  comment.

Not permitted: marking a finding `resolved` without a verified change,
silently dropping findings, or downgrading severity to avoid work. A finding
may be `accepted` or `deferred` only with a written reason the user can review.

## Method

1. Deduplicate per the pr-review dedupe rules; one root cause,
   one finding.
2. Order by severity, then by blocking flag. Work `P0` and `P1` first; `P2`
   next; `P3` only when cheap and safe.
3. For each finding: reproduce or confirm from evidence, apply the fixPlan
   (or a better one, explained), and run the finding's verification command.
4. Route by kind: a security finding follows `fix-security-finding`; a test
   gap follows `generate-unit-tests`; a dependency finding follows
   `dependency-upgrade`; a failing check follows `fix-ci`.
5. Record the result in the finding's `verification` block: method, command,
   result, residual risk.

## Stop conditions

Stop and report when a `P0`/`P1` finding cannot be verified, when two
findings' fixes conflict, when a finding needs product or security judgment
the user has not delegated, or when the PR base has moved and findings no
longer apply to the current diff.

## Verification

- Every `resolved` finding has a verification command that was run and
  passed on the new revision.
- The repository's full validation passes.
- Remaining `open`, `accepted`, and `deferred` findings each carry a reason.

## Outcome report

```text
Findings: <n total>; resolved <n>, accepted <n>, deferred <n>, open <n>
Per finding: <id> <severity> -> <status>: <what changed / why not>; verified by <command>
Verified: <full validation commands and results>
Risk accepted or deferred: <list with reasons>
```
