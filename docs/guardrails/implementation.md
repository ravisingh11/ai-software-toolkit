# Guardrails v2 implementation map

Guardrails uses JSON-compatible YAML and Python's standard library for its core
contracts and evaluator.

| Source | Installed consumer path | Purpose |
| --- | --- | --- |
| `guardrails/baseline.yaml` | `.guardrails/policy.yaml` | Core-selected starter policy |
| `policies/profiles.yaml` | `.guardrails/profiles.yaml` | Core and GitHub profile defaults |
| `policies/control-catalog.yaml` | `.guardrails/control-catalog.yaml` | Capability catalog |
| `policies/provider-config.yaml` | `.guardrails/providers.yaml` | Provider definitions and selections |
| `guardrails/*.schema.json` | `.guardrails/*.schema.json` | Policy, profile, provider, catalog, and evidence validation |
| `guardrails/evaluate.py` | `.guardrails/evaluate.py` | Effective-policy and evidence evaluation |
| `tooling/configure_guardrails.py` | `.guardrails/configure.py` | Atomic policy/provider mutation |
| `tooling/scan_repository.py` | `.guardrails/scan.py` | Local producer execution, evidence merge, and report writing |
| `tooling/guardrail_scorecard.py` | `.guardrails/scorecard.py` | Public scorecard rendering |
| `tooling/github_evidence.py` | `.guardrails/github_evidence.py` | Exact-head GitHub check collection and provenance validation |
| `tooling/produce_guardrail_evidence.py` | `.guardrails/produce.py` | Repository command, Semgrep CE, and Gitleaks evidence |
| `tooling/validators/validate_pr_metadata.py` | `.guardrails/validators/validate_pr_metadata.py` | Mutable pull-request fingerprint and metadata evidence |
| `guardrails/validate_repository.py` | `.guardrails/validators/validate_repository.py` | Installed runtime inventory and contract validation |
| `tooling/render_scorecard_badge.py` | `.guardrails/render_scorecard_badge.py` | Optional bounded public scorecard projection |
| `tooling/reconcile_scorecard_badge.py` | `.guardrails/reconcile_scorecard_badge.py` | Optional trusted source-run and PR-binding reconciliation |

## Installed configuration

`guardrails/baseline.yaml` is the consumer starter policy. After installation,
`.guardrails/policy.yaml` is repository-owned configuration and may select
additional profiles or overrides without changing the consumer baseline.

The installer also adds repository-owned documentation mappings, change-scope
thresholds, ground-truth inventory, validators, Semgrep rules, rule fixtures,
and selected workflow templates. Refresh preserves repository-owned policy,
provider selection, documentation, scope, and ground-truth files.

## Runtime sequence

1. Resolve and validate policy, profiles, catalog, and providers.
2. Resolve the operation and exact subject.
3. Run local providers or collect selected GitHub checks.
4. Merge only nested v2 evidence with an identical subject.
5. Add honest `not_run` placeholders for missing authoritative providers.
6. Validate evidence shape and provider capability mappings.
7. Evaluate authoritative evidence; retain supplemental evidence as advisory.
8. Write JSON evidence and a timestamped Markdown scorecard.

Invalid configuration or evidence exits `2`. An allowed decision exits `0`; a
blocked decision exits `1`.

The portable repository validator requires every executable installed runtime
component, including the PR metadata validator. It accepts all catalog subject
types and enforces catalog promotion restrictions, so `advisory-only` controls
cannot pass repository validation with an `enforced` policy override.

Future lifecycle capabilities remain catalog/evidence definitions and have no
runtime producers. See [architecture](architecture.md) and
[producer contract](producer-contract.md).

## Optional badge publisher

`--scorecard-badge` installs the two badge runtime files and
`guardrails-scorecard-badge.yml`; the default install omits them. Existing
installations require `--refresh-existing --scorecard-badge`. Refresh detects
the installer-owned optional set and keeps it current. Symmetric removal uses
`--refresh-existing --remove-scorecard-badge` and refuses symlinks or
consumer-owned collisions.

The native **Scorecard Workflow** badge is GitHub's workflow conclusion. The
optional **Latest PR Scorecard** is the newest accepted PR readiness and
passed/active count. Publication is downstream reporting only and never affects
evaluation or merge policy. The public files contain aggregates, source-run
metadata, and a revision digest; detailed evidence is excluded from Pages and
remains in the source Actions artifact under normal repository access. See
[quick start](../quickstart.md#publish-the-optional-scorecard-badge).
