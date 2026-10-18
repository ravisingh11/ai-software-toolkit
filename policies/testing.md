# Testing Policy

## Status

Repositories choose their test commands, coverage targets, and Proof modes.
The [optional quality recipes](../docs/standards/optional-quality-checks.md)
and [defensive scenarios](defensive-testing.md) do not activate checks or
change enforcement. The coverage target below is a recommended starting point.

This is an initial, evolving standard. The requirements below are the default
direction; language-specific test commands, report formats, and exceptions
remain repository-specific.

## Requirements

- New functionality requires automated tests.
- Modified behavior requires updated tests.
- Every bug fix requires a regression test.
- Important failure paths and edge cases should be tested.
- Tests run automatically on every PR.
- Tests must contain meaningful assertions and verify behavior, not merely
  execute lines to increase a metric.
- Use integration, contract, or UI tests when unit tests cannot establish the
  required behavior.
- Repositories with long-running or resource-sensitive workloads should define
  a soak check for pre-release and scheduled validation. Record the exact
  revision, duration, workload, resource observations, thresholds, and result.
- Focus enforcement on new and changed code.
- Existing historical test debt does not have to be remediated before every
  unrelated change. Track it as a separate task with ownership and scope.

## Coverage target

> Target **≥90% coverage of new/changed testable code**.

Coverage is a signal, not the objective itself. A high percentage does not
excuse weak assertions, missing failure-path tests, or a design that is hard to
test. Repositories should configure their coverage tool and SonarQube analysis
to report new-code coverage where supported.

## Exceptions

If a file or behavior is not meaningfully testable, document the reason in the
PR and preserve a focused verification alternative. Do not weaken unrelated
checks to make a test pass.
