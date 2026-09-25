# Guardrails Configuration Path Hard Cutover

## Status

Approved design. Implementation requires a hard cutover from legacy `.ai/`
Guardrails configuration to `.guardrails/` configuration.

## Context

The repository uses `.guardrails/` for the installed Guardrails runtime,
provider configuration, and producer manifest. Five remaining configuration
files still live under `.ai/` even though they describe engineering policy and
repository controls rather than AI implementation details. That split obscures
ownership and makes the installation model harder to explain.

The ground-truth inventory exists to provide repository context to AI agents,
so its new filename makes that purpose explicit while keeping it with the
Guardrails configuration that validates it.

## Decision

Use these canonical installed paths:

| Legacy path | Canonical path |
| --- | --- |
| `.ai/guardrails.yaml` | `.guardrails/policy.yaml` |
| `.ai/control-catalog.yaml` | `.guardrails/control-catalog.yaml` |
| `.ai/documentation.yaml` | `.guardrails/documentation.yaml` |
| `.ai/change-scope.yaml` | `.guardrails/change-scope.yaml` |
| `.ai/ground-truth.yaml` | `.guardrails/ground-truth-ai.yaml` |

The non-dot `guardrails/` directory remains the source location for shared
schemas, baseline templates, the evaluator implementation, and tests. The
dot-prefixed `.guardrails/` directory remains the installed repository runtime
and repository-specific configuration surface.

The canonical repository and embedded demo will no longer contain a `.ai/`
directory unless a future feature introduces genuinely AI-owned configuration.

## Compatibility Policy

This is a hard cutover:

- Runtime commands read only the new `.guardrails/` paths.
- Workflows and actions pass only the new paths.
- The installer writes only the new paths.
- There is no legacy runtime fallback and no automatic migration.
- Existing consumers must move customized files before reinstalling or
  refreshing Guardrails.

The installer must detect the five known legacy files before writing. If any
exist, it must exit non-zero with an actionable old-to-new path map. It must not
copy a baseline over customized legacy policy, delete legacy files, or infer
that two files with different contents can be merged safely. Detection applies
to normal, dry-run, merge-existing, and refresh-existing modes.

An unrelated `.ai/` directory or unrelated AI-specific file must not trigger
the Guardrails legacy-path error.

## Components

### Repository configuration

Move the canonical repository and Python demo files to the new paths. Preserve
their contents except where relative schema references must change.

### Runtime and tooling

Update defaults and explicit arguments in:

- the installed evaluator, configurator, scanner, scorecard, GitHub evidence
  collector, and ground-truth validator;
- canonical tooling equivalents;
- repository validators and staged-change attestation tooling;
- the composite action interface and commands.

No command should silently search legacy locations.

### Workflows and producer contracts

Update first-party workflows, reusable examples, and the producer contract to
use the new policy, catalog, documentation, scope, and AI ground-truth paths.
Producer check names and evidence identifiers do not change.

### Installer

Change installation destinations to `.guardrails/`. Add a preflight legacy
check before the installation plan performs writes. Keep existing protections
against overwriting unknown or customized files.

### Documentation, skills, and examples

Update setup, compliance, quick-start, architecture, validator, skill, and demo
documentation. Explain the distinction between `guardrails/` source files and
`.guardrails/` installed files once, then link to that canonical explanation.

## Execution Flow

```text
Install or refresh requested
        ↓
Check five known legacy .ai paths
        ↓
Legacy path exists? ── yes ──→ fail with explicit git mv instructions
        │
        no
        ↓
Write or refresh .guardrails files using existing overwrite protections
        ↓
Run repository-owned producers
        ↓
Evaluate .guardrails/policy.yaml against revision-bound evidence
```

## Failure Behavior

- Missing new configuration is a configuration error or `NO RESULT` according
  to the existing producer/evaluator contract; it is never a pass.
- Legacy configuration produces an installer error, not an implicit migration.
- Conflicting old and new files produce the same installer error until the
  operator resolves the conflict explicitly.
- Error output lists every detected legacy path and its exact destination.

## Verification

Add regression coverage proving:

1. A fresh installation creates the five canonical `.guardrails/` files and
   creates no Guardrails-owned `.ai/` files.
2. Installer modes fail before writing when a known legacy file exists.
3. Unrelated `.ai/` files do not block installation.
4. Runtime defaults and workflow commands use only canonical paths.
5. The canonical repository and demo validate and scan successfully from the
   new paths.
6. Active source, workflow, action, documentation, and skill references contain
   no legacy Guardrails paths. Legacy detection code and focused migration
   tests are the only allowed references.
7. JSON-compatible YAML, Markdown links, action syntax, workflow syntax, and
   the complete repository test suite pass.

## Out of Scope

- Changing control IDs, producer check names, evidence schemas, or enforcement
  semantics.
- Automatically migrating or deleting consumer files.
- Moving genuinely AI-owned configuration out of `.ai/` if such configuration
  is added later.
- Renaming the non-dot `guardrails/` source directory.
