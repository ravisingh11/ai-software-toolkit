---
name: dependency-upgrade
description: "Plan and execute one focused dependency upgrade: compatibility review, lockfile update, tests, security alerts, and rollback notes. Use when a dependency must move to a new version because of a vulnerability, deprecation, or required feature."
---

# Dependency Upgrade

Move one dependency (or one tightly coupled group) forward safely.
`dependency-risk-review` assesses risk before a change and
`dependency-remediation` covers alert triage and lockfile hygiene; this skill
performs the upgrade and proves compatibility. Detect the package manager from
the repository (`ai-toolkit discover` reports it); never mix managers.

## Inputs

- The dependency and target version or range, and the reason (advisory id,
  deprecation notice, feature need).
- The package manager, lockfile, and the repository's test and build commands.
- Any pinning policy (`renovate.json`, `dependabot.yml`, constraints files).

## Permitted changes

- The manifest entry for the dependency and its lockfile resolution.
- Transitive constraint or override entries only when the target cannot
  otherwise resolve, each with a comment naming the reason.
- Code changes strictly required by the new version's breaking changes.
- Documentation of the upgrade in the changelog when the repository keeps one.

Not permitted: upgrading unrelated packages, switching package managers,
removing the lockfile, or disabling audit checks.

## Method

1. Read the release notes between the current and target versions; list
   breaking changes that touch this repository's usage.
2. Upgrade with the package manager's own command so the lockfile is
   regenerated consistently; do not hand-edit the lockfile.
3. Build and run the full test suite; fix compile or test failures caused by
   documented breaking changes only.
4. Rerun the dependency scanner that raised the alert (Snyk, Dependabot,
   `pip-audit`, `npm audit`, or `ai-toolkit check`) and confirm the advisory
   is resolved.
5. Write a rollback note: the previous version, the exact revert command, and
   any data or config that the new version migrates.

## Stop conditions

Stop and report when the target version requires a runtime or platform
upgrade, when breaking changes need product decisions, when the lockfile
regenerates with unrelated drift the user has not approved, or when the
advisory is only fixed in a version outside the allowed range.

## Verification

- Lockfile updated by the package manager; `git diff` shows only the intended
  packages plus their transitive resolutions.
- Build and tests pass; the originating scanner no longer reports the
  advisory for the new revision.

## Outcome report

```text
Dependency: <name> <old> -> <new> (reason: <advisory or need>)
Breaking changes handled: <list or none>
Lockfile: <manager command used; unrelated drift: none | listed>
Verified: <build, tests, scanner results>
Rollback: <revert command and caveats>
```
