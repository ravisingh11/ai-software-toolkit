# Documentation

AI Software Toolkit brings together skills, QA workflows, standards, and
Guardrails. Start with the task you need to perform.

| Task | Guide |
| --- | --- |
| Understand the direction and current maturity | [Vision](vision.md) |
| Set up the toolkit with one CLI | [Install with `ai-toolkit`](install.md) |
| Install and run Guardrails in a repository | [Quickstart](quickstart.md) |
| Install reusable agent skills | [Skill catalog](../skills/README.md) |
| Set up functional QA | [QA bootstrap](../skills/qa-bootstrap/SKILL.md) |
| Develop and check this toolkit | [Self-check](self-check.md), [contributing](../CONTRIBUTING.md) |
| Update an existing clone after the rename | [Repository rename](repository-rename.md) |
| Review supported releases | [Changelog](../CHANGELOG.md), [v1.0.0](releases/v1.0.0.md) |

## Guides by area

| Directory | Contents |
| --- | --- |
| [guardrails/](guardrails/README.md) | Runtime model, architecture, providers, configuration, operation, and scorecards |
| [standards/](standards/README.md) | Agent guidance, commits, error handling, release evidence, and specification-driven development |
| [agent-workflows/](agent-workflows/README.md) | Repository administration and dependency remediation workflows |
| [examples/](examples/sample-scorecard.md) | Illustrative scorecards and workflow examples |
| [releases/](releases/v1.0.0.md) | Published release notes |
| [archive/](archive/README.md) | Historical designs and implementation plans; not current setup instructions |

Shared requirements live in [policies/](../policies/ai-development.md).
[Licensing](licensing.md) and [social preview maintenance](social-preview.md)
remain toolkit-wide references.

## Source ownership and installed copies

This repository publishes the toolkit and consumes it. Similar-looking files
have different roles:

| Source | Installed consumer surface | Editing rule |
| --- | --- | --- |
| `guardrails/`, `tooling/` | `.guardrails/*.py`, schemas and validators | Edit the source, test it, then review the installed refresh diff |
| `policies/`, `guardrails/defaults/` | `.guardrails/*.yaml` | Shared defaults are advisory; preserve this repository's selected policy and configuration |
| `workflows/` | `.github/workflows/` | Templates are distributed; installed and repository-owned CI runs here |
| `skills/` | `.agents/skills/` | Publish shared skills from `skills/`; installed skills make this repository a consumer |
| `security/semgrep/` | `.guardrails/semgrep-rules.yml` and fixtures | Preserve tested scanner rules and installed copies |
| Toolkit distribution | `examples/python-demo/` | Keep the runnable consumer example, including its embedded runtime |

The installer defines the copy mapping in [tooling/install.py](../tooling/install.py).
Use its dry-run and review the diff before refreshing; a refresh is unnecessary
for documentation-only moves. Do not delete installed copies as duplicates or
move public runtime paths to make the source tree look smaller.

The `engineering-standards` identifier under `tooling/speckit/` is a compatibility
identifier for the published Spec Kit preset. It is independent of the GitHub
repository name.

## Local output and history

`.artifacts/`, `.omx/`, `.superpowers/`, and `.worktrees/` hold local output or
working state and are ignored by Git. Keep generated reports and execution
transcripts there. Curate durable design rationale into `docs/archive/`; current
instructions belong in the guides above. Removed transient reports and the
superseded v0.3.0 draft remain available in Git history.

Current guides formerly at `docs/architecture.md`, `docs/guardrails.md`,
`docs/guardrails-implementation.md`, `docs/producer-contract.md`, and
`docs/control-*.md` are now under `docs/guardrails/`. The former
`docs/compliance.md` is now [the operating guide](guardrails/operating-guide.md).
The five `docs/*-standard*.md` guides are now under `docs/standards/`, and
`docs/superpowers/` became `docs/archive/`. Runtime paths and release tags did
not move.
