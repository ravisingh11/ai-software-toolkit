# Spec-Driven Development Standard

Use Spec Kit for work where the product intent, user journeys, implementation
shape, or acceptance evidence needs to be written down before code changes
begin. This standard adopts upstream Spec Kit as the workflow engine and adds
engineering-standards guidance through a preset.

## When To Use

Use the Spec Kit flow for:

- New product features or meaningful changes to user journeys.
- Cross-client or multi-surface work where web, API, mobile, admin, workers, or
  extensions must stay aligned.
- Changes with unclear requirements, important edge cases, or multiple valid
  implementation approaches.
- Refactors that affect public behavior, data contracts, operational risk, or
  release safety.

The issue-first workflow remains valid. Spec Kit artifacts complement the issue
by making the specification, plan, and task breakdown durable.

Skip Spec Kit for:

- Typo fixes, tiny UI polish, and small one-file corrections.
- Dependency bumps, lockfile maintenance, branch cleanup, and repo metadata
  hygiene.
- Emergency patches where the fastest safe path is a direct fix followed by
  release evidence.

## Required Artifacts

For work that uses Spec Kit, keep artifacts under:

```text
specs/<id>-<short-name>/
├── spec.md
├── plan.md
├── tasks.md
└── checklists/
```

Use the upstream Spec Kit commands in order:

1. `$speckit-constitution` when a repository does not yet have governing
   principles or they need revision.
2. `$speckit-specify` to capture user stories, functional requirements, edge
   cases, success criteria, and assumptions.
3. `$speckit-clarify` when the spec contains high-impact ambiguities.
4. `$speckit-plan` to map the approved spec to technical decisions and release
   gates.
5. `$speckit-tasks` to produce an implementation task list grouped by
   independently testable user stories.
6. `$speckit-analyze` before implementation when the spec, plan, and tasks
   might drift.
7. `$speckit-implement` only after the prior artifacts are coherent.

## Standards Preset

Install the engineering standards preset in a Spec Kit initialized repository:

```bash
specify preset add --dev speckit/presets/engineering-standards --priority 5
```

For a packaged release, publish the generated ZIP to an HTTPS release URL and
install that URL:

```bash
specify preset add --from https://github.com/engineering-standards/spec-kit-preset-engineering-standards/releases/download/v1.0.0/spec-kit-preset-engineering-standards-v1.0.0.zip --priority 5
```

The preset wraps upstream Spec Kit commands instead of replacing them. It adds:

- Issue linkage and release evidence expectations.
- Security, privacy, error-handling, and observability checks.
- Cross-client parity and contract drift checks.
- CI-neutral validation guidance tied to each repository's chosen release gate.
- Explicit guidance to avoid secrets, customer data, and private operational
  details in specs, plans, tasks, and checklists.

## Relationship To Existing Standards

- `docs/mature-product-repo-standard.md` defines when a product repo needs
  durable operational discipline.
- `docs/standards/release-evidence-standard.md` defines what must be recorded after a
  production-facing release.
- `docs/standards/error-handling-standard.md` defines error and observability behavior.
- `docs/contracts/CROSS_CLIENT_DELIVERY_CONTRACT.md` defines multi-surface
  parity tracking.

Spec Kit does not replace these standards. It gives agents a repeatable way to
produce feature artifacts that reference and satisfy them.

## Safety Rules

- Do not put secrets, tokens, customer data, private logs, or sensitive
  operational details in Spec Kit artifacts.
- Keep implementation details out of `spec.md`; put technical decisions in
  `plan.md`.
- Keep task descriptions specific enough for an agent to execute, including
  relevant file paths once known.
- Treat generated artifacts as versioned source of truth for the feature. If
  implementation changes the intent, update the spec or plan instead of leaving
  drift.
