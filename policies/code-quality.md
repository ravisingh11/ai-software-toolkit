# Code Quality Policy

Repositories choose which automated checks to adopt and how to treat their
results. The [optional quality recipes](../docs/standards/optional-quality-checks.md)
provide linting and architecture examples without activating or requiring them.

## Requirements

- New code should improve the codebase rather than add avoidable technical
  debt.
- Prefer simple, maintainable implementations over clever or speculative
  abstractions.
- Follow the application repository's documented architecture and standards.
- Avoid unnecessary duplication; prefer existing utilities and patterns when
  they fit the problem.
- Handle failures explicitly and preserve useful diagnostics without exposing
  secrets or sensitive data.
- Avoid oversized functions, classes, and modules where reasonable.
- Do not introduce new compiler, linter, type-checker, or static-analysis
  warnings.
- Keep PRs focused and independently understandable.
- Treat repeated review findings as candidates for automated checks or shared
  standards.
- Prefer deletion and boundary repair over adding layers that do not reduce
  complexity or risk.

## Review signal

Code quality is evaluated in context. A small, clear change that matches local
architecture is preferable to a broad refactor that happens to reduce a
metric. Existing historical debt should be addressed through a separate,
tracked change unless it directly blocks the proposed work.
