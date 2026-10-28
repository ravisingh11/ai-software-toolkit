# Documentation

AI Software Toolkit brings together skills, QA workflows, standards, and
Proof. Start with the task you need to perform.

Six entry points, one per component:

| Entry point | Start here | Then |
| --- | --- | --- |
| **Install** | [Install with `ai-toolkit`](install.md) — one CLI for discovery, preview, installation, `doctor`, `check`, and `update` | [Quickstart](quickstart.md) for the underlying installer and scanner |
| **Proof** | [Proof guides](proof/README.md) — runtime model, control setup, operating guide, scorecards | [Producer contract](proof/producer-contract.md), [control status](proof/control-status.md) |
| **Skills** | [Skill catalog](../skills/README.md) — review skills, the five action skills, installation for Codex and Claude Code | Each action skill's `VERIFICATION.md` for what has been proven |
| **QA** | [QA bootstrap](../skills/qa-bootstrap/SKILL.md) — generate the `qa` orchestrator | [Plans, findings, and regression reruns](../skills/qa-bootstrap/references/plans-and-findings.md) |
| **Providers** | [Providers](providers/README.md) — SonarQube, Snyk, FOSSA, reason codes, adapter-owned commands | [Live verification ledger](providers/verification.md) |
| **Reference app** | [Reference app](reference-app.md) — the embedded Python fixture and separate TypeScript application | [Demo README](../examples/python-demo/README.md) |

For decisions from coding through merge, use [SDLC checkpoints](sdlc-checkpoints.md):
recommended check placement, evidence scope, authority, invalidation and later
release/deployment handoffs. The guide maps all 33 checks without activating them.

For a first installation, follow [workspace and skill onboarding](skill-onboarding.md).
For evidence that an action skill worked, use the
[real-client verification protocol](skill-verification.md); file validation and
skill invocation alone do not prove the outcome.

Also: [Vision and maturity](vision.md) (what is shipped, opt-in, or planned),
[self-check](self-check.md) and [contributing](../CONTRIBUTING.md) for
developing the toolkit, the [repository rename](repository-rename.md) note,
the [Guardrails to Proof migration](proof/migrating-from-guardrails.md),
and the [changelog](../CHANGELOG.md) with [release notes](releases/README.md).

The [activation index](activation.md) covers all 33 checks. The
[reading evidence guide](proof/reading-evidence.md) preserves detailed setup,
provider limitations, and scorecard interpretation.

## Guides by area

| Directory | Contents |
| --- | --- |
| [proof/](proof/README.md) | Runtime model, architecture, providers, configuration, operation, and scorecards |
| [providers/](providers/README.md) | External provider guides, adapter-owned commands, reason codes, and the live verification ledger |
| [standards/](standards/README.md) | Agent guidance, commits, error handling, release evidence, and specification-driven development |
| [agent-workflows/](agent-workflows/README.md) | Repository administration and dependency remediation workflows |
| [examples/](examples/sample-scorecard.md) | Illustrative scorecards and workflow examples |
| [releases/](releases/README.md) | Published release notes |
| [archive/](archive/README.md) | Historical designs and implementation plans; not current setup instructions |

Shared requirements live in [policies/](../policies/ai-development.md).
[Licensing](licensing.md) and [social preview maintenance](social-preview.md)
remain toolkit-wide references.

## Source ownership and installed copies

This repository publishes the toolkit and consumes it. Similar-looking files
have different roles:

| Source | Installed consumer surface | Editing rule |
| --- | --- | --- |
| `proof/`, `tooling/` | `.proof/*.py`, schemas and validators | Edit the source, test it, then review the installed refresh diff |
| `policies/`, `proof/defaults/` | `.proof/*.yaml` | Shared defaults are advisory; preserve this repository's selected policy and configuration |
| `workflows/` | `.github/workflows/` | Templates are distributed; installed and repository-owned CI runs here |
| `skills/` | `.agents/skills/` | Publish shared skills from `skills/`; installed skills make this repository a consumer |
| `security/semgrep/` | `.proof/semgrep-rules.yml` and fixtures | Preserve tested scanner rules and installed copies |
| Toolkit distribution | `examples/python-demo/` | Keep the runnable consumer example, including its embedded runtime |

The installer defines the copy mapping in [tooling/install.py](../tooling/install.py).
Use its dry-run and review the diff before refreshing; a refresh is unnecessary
for documentation-only moves. Do not delete installed copies as duplicates or
move public runtime paths to make the source tree look smaller.

The `engineering-standards` identifier under `tooling/speckit/` is a compatibility
identifier for the published Spec Kit preset. It is independent of the GitHub
repository name.

## Distribution verification

The toolkit-owned `.github/workflows/distribution-acceptance.yml` verifies CLI
archive integrity and fresh/published-consumer compatibility on PRs and explicit
maintainer dispatch. It is not installed into consumers. After required CI passes,
run it on the final merged revision and retain the verified CLI bytes and
`distribution-verification.json` for the draft release. Its fixture runner is
`tooling/verify_distribution.py`; it does not execute application checks or
activate providers. Full source archives retain the optional Spec Kit source;
the default CLI archive and standard release attachments exclude its package.

## Local output and history

`dist/`, `.artifacts/`, `.omx/`, `.superpowers/`, and `.worktrees/` hold local
output or working state and are ignored by Git. Keep generated reports and execution
transcripts there. Curate durable design rationale into `docs/archive/`; current
instructions belong in the guides above. Removed transient reports and the
superseded v0.3.0 draft remain available in Git history.

Current guides formerly at `docs/architecture.md`, `docs/proof.md`,
`docs/proof-implementation.md`, `docs/producer-contract.md`, and
`docs/control-*.md` are now under `docs/proof/`. The former
`docs/compliance.md` is now [the operating guide](proof/operating-guide.md).
The five `docs/*-standard*.md` guides are now under `docs/standards/`, and
`docs/superpowers/` became `docs/archive/`. Runtime paths and release tags did
not move.

See [documentation mappings and execution](proof/documentation-validation.md) for
practical consumer setup. `tooling/activation.py` owns shared activation hints
and renders the index; both doctor commands use those same hints.

## Documentation coverage check

`tooling/validators/validate_repository.py` checks workflow templates, skill
entries, provider names, and tooling references against current documentation.
For tooling it recognizes Python and shell files plus executable or
shebang-bearing commands, including extensionless commands. It excludes test
fixtures, tests, bytecode caches, and package initializer files. Archived plans
do not satisfy the check. Other source-file types still need review; a filename
mention establishes documentation coverage, not the accuracy of its contents.
