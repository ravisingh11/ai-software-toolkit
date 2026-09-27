# Pull Request Policy

## Smaller PRs by default

Default advisory target:

```text
300–500 meaningful changed lines per PR
```

Repositories configure their thresholds in `.proof/change-scope.yaml`.
PR size is not a blocking rule initially. Generated, vendor, dependency-lock,
and documentation paths may be excluded from meaningful thresholds, but their
volume should remain visible in total change metrics. AI should flag an
oversized or multi-concern PR and explain why splitting it would improve
reviewability.

Example:

> This PR changes 1,284 lines across 17 files and contains three distinct
> concerns. Recommend splitting into three independent PRs.

The goal is faster review, better AI comprehension, less rework, lower
regression risk, faster merge, and faster production delivery.

## Configurable enforcement

The shared catalog describes available capabilities. It does not require every
repository to activate every capability at the same enforcement level.

Repositories may use this progression:

```text
Not activated → cataloged, but not selected by this repository
Advisory     → selected and visible without merge blocking
Enforced     → selected and added as an exact ruleset check
```

The repository selects its enforcement level in its policy configuration and
GitHub ruleset. In the policy JSON, the `required` list represents the
user-facing `Enforced` mode. Teams may add capabilities such as Snyk, FOSSA,
Semgrep, soak testing, or additional AI review depth when those capabilities
fit the repository and have an owner. Promotion to `Enforced` should follow a
period of reliable results, tuned thresholds, and clear remediation ownership.

## Default change path

Every code change should normally use a PR. Protected/default branches must
enforce:

- No direct push to a protected/default branch.
- No force push to a protected/default branch.
- Required status checks.
- Required review conversations resolved.
- Required AI reviews completed when selected by the repository enforcement
  profile.
- Unit tests passed.
- SonarQube Quality Gate passed when selected as a required repository check.
- Required security checks passed; advisory scanners remain visible for
  iteration.
- Dependency review passed.
- Snyk findings are reviewed when the repository has adopted the advisory Snyk
  integration; Snyk becomes enforced only after it meets the shared promotion
  rule and its exact check is added to the repository ruleset.
- CODEOWNERS or domain approval where applicable.

There is no standing bypass for normal development, including for a
single-developer repository. Emergency exceptions, if the organization later
decides to allow them, must be narrowly scoped, auditable, followed by
verification, and documented. An exception is not an alternative normal
workflow.

## Review expectations

PR descriptions should state the purpose, scope, verification performed,
risk/rollback considerations, and any known gaps. Reviewers should prioritize
material findings over comment volume.

## Legacy debt

This policy does not require unrelated historical cleanup before shipping a
focused change. New and changed code must meet the testing and quality gates;
older debt should be tracked separately.
