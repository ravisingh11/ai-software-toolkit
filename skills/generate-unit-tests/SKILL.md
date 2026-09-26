---
name: generate-unit-tests
description: "Write meaningful unit tests for changed or untested behavior, including failure paths and edge cases, in the repository's existing test conventions. Use when coverage of a change is missing, when changed-code coverage fails, or when asked to add tests for a module."
---

# Generate Unit Tests

Add tests that would catch a real regression. Coverage percentage is an
outcome, not the goal: a test that only executes lines without asserting
behavior is not acceptable. Use `test-gap-finder` to decide *what* is
untested; this skill writes the tests.

## Inputs

- The target: a diff, a module, or the changed-code coverage report naming
  uncovered lines.
- The repository's test framework, layout, naming, and fixtures (detect from
  existing tests; never introduce a second framework).
- The behavior specification when one exists (docstrings, acceptance criteria,
  QA plans under `qa/plans/`).

## Permitted changes

- New or extended test files following the repository's conventions.
- Small test-support helpers or fixtures in the test tree.
- Production code only for testability seams that do not change behavior
  (for example, injecting a clock), and only with an explanation.

Not permitted: changing production behavior to make a test pass, deleting or
weakening existing assertions, or marking tests skipped to raise coverage.

## Method

1. List the behaviors of the target: happy path, each failure path, boundary
   values, and any concurrency or ordering assumption.
2. For each behavior, write one test that fails if the behavior is broken;
   check this by reasoning about (or briefly introducing) the breakage.
3. Prefer black-box assertions on outputs and side effects over asserting
   implementation details.
4. Keep tests deterministic: no network, real time, or shared mutable state.
5. Run the new tests and the module's existing tests.

## Stop conditions

Stop and report when the target's intended behavior is unknowable from code
and documentation (ask rather than encode a guess as a test), or when testing
requires infrastructure the repository does not provide.

## Verification

- New tests pass; the existing suite passes.
- Each new test's name states the behavior it protects.
- When run, the changed-code coverage command meets the repository target,
  and any remaining uncovered lines are listed with a reason.

## Outcome report

```text
Target: <module or diff>
Behaviors covered: <list, one per test>
Behaviors not covered and why: <list>
Verified: <commands run and results; coverage before/after when measured>
```
