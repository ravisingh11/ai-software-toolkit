---
name: spec-driven-development
description: "Capture tool-independent specifications, plans, tasks, and acceptance evidence for substantial features, unclear requirements, cross-client changes, or risky refactors."
---

# Specification-driven development

Use the repository's existing issue tracker, Markdown conventions, or chosen
specification tool. Spec Kit is optional and is never a prerequisite for this skill.

## Workflow

1. Capture outcomes, user journeys, constraints, assumptions, and edge cases.
2. Clarify ambiguities that affect scope or safety.
3. Record technical decisions, contract changes, risks, and release gates.
4. Break the plan into independently testable user stories and tasks.
5. Review consistency before implementing; update artifacts when intent changes.
6. Link acceptance evidence and release decisions to the reviewed revision.

For small changes, use an issue or PR description instead of generating unnecessary
artifacts. Keep specifications free of secrets, customer data, and private logs.
Preserve cross-client parity and repository-owned acceptance criteria.

## Optional integration

When the repository already chooses Spec Kit, follow its installed workflow.
See the toolkit's `docs/standards/spec-driven-development-standard.md` and
`tooling/speckit/engineering-standards/README.md` for explicit preset installation.
The preset is independent of Proof and the starter skill selection.

## Verification

Review that intent, implementation plan, tasks, and acceptance evidence agree.
Execute only the repository's authorized checks. Installing a skill or generating
a specification does not execute a producer or prove a check passed.
