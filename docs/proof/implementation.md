# Proof implementation map

Proof uses JSON-compatible YAML and Python's standard library for its core
contracts and evaluator.

| Source | Installed consumer path | Purpose |
| --- | --- | --- |
| `proof/baseline.yaml` | `.proof/policy.yaml` | Core-selected starter policy |
| `policies/profiles.yaml` | `.proof/profiles.yaml` | Core and GitHub profile defaults |
| `policies/control-catalog.yaml` | `.proof/control-catalog.yaml` | Capability catalog |
| `policies/provider-config.yaml` | `.proof/providers.yaml` | Provider definitions and selections |
| `proof/*.schema.json` | `.proof/*.schema.json` | Policy, profile, provider, catalog, and evidence validation |
| `proof/evaluate.py` | `.proof/evaluate.py` | Effective-policy and evidence evaluation |
| `tooling/configure_proof.py` | `.proof/configure.py` | Atomic policy/provider mutation |
| `tooling/scan_repository.py` | `.proof/scan.py` | Local producer execution, evidence merge, and report writing |
| `tooling/proof_scorecard.py` | `.proof/scorecard.py` | Public scorecard rendering |
| `tooling/github_evidence.py` | `.proof/github_evidence.py` | Exact-head GitHub check collection and provenance validation |
| `tooling/proof_measurements.py` | `.proof/measurements.py` | Self-reported test and coverage measurements for the Unit Tests and Changed Code Coverage workflows |
| `tooling/produce_proof_evidence.py` | `.proof/produce.py` | Repository command, Semgrep CE, and Gitleaks evidence |
| `tooling/validators/validate_pr_metadata.py` | `.proof/validators/validate_pr_metadata.py` | Mutable pull-request fingerprint and metadata evidence |
| `proof/validate_repository.py` | `.proof/validators/validate_repository.py` | Installed runtime inventory and contract validation |
| `tooling/render_scorecard_badge.py` | `.proof/render_scorecard_badge.py` | Optional bounded public scorecard projection |
| `tooling/reconcile_scorecard_badge.py` | `.proof/reconcile_scorecard_badge.py` | Optional trusted source-run and PR-binding reconciliation |

## Installed configuration

`proof/baseline.yaml` is the consumer starter policy. After installation,
`.proof/policy.yaml` is repository-owned configuration and may select
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
`proof-scorecard-badge.yml`; the default install omits them. Existing
installations require `--refresh-existing --scorecard-badge`. Refresh detects
the installer-owned optional set and keeps it current. Symmetric removal uses
`--refresh-existing --remove-scorecard-badge` and refuses symlinks or
consumer-owned collisions.

The native **Scorecard Workflow** badge is GitHub's workflow conclusion. The
optional **Latest PR Scorecard** is the newest accepted PR readiness and
passed/active count. Publication is downstream reporting only and never affects
evaluation or merge policy. The public files contain aggregates, PR-size
measurements and thresholds, source-run metadata, a revision digest, and
individual entries for all trusted built-in catalog controls. IDs, names, and
purposes are supplied by the trusted catalog; validated scorecard rows supply
effective modes and evidence statuses. Absent rows display **Not reported**,
not a pass or an inferred `not_activated` mode. The source run is the evidence
link. Private or arbitrary control IDs, provider data, findings, detailed
evidence, reasons, check URLs, raw revisions, and source Markdown remain
excluded from Pages and available in the source Actions artifact under normal
repository access. See
[quick start](../quickstart.md#publish-the-optional-scorecard-badge).

### Optional check execution facts

GitHub check evidence can include `check_execution` version 1: `started_at`,
`completed_at`, `duration_seconds`, and an allowlisted `conclusion`. The collector
adds these facts only for valid completed timestamp pairs. It adds no API calls
or free-form log content. The evaluator verifies the conclusion against evidence
status and verifies that duration equals the elapsed whole seconds. Missing
metadata preserves legacy behavior; invalid supplied metadata is rejected.
The public renderer independently validates these facts before displaying them.
They describe check execution, not test totals, scan coverage, or finding counts.

This is an additive evidence-v2 field. Old artifacts remain supported. Upgrade
collector, evaluator, and schema together with the installer refresh workflow;
older strict evaluators reject results containing the new optional field.
Per-control assessment descriptions come from a trusted built-in allowlist,
not provider-supplied prose. Providers that do not emit execution facts continue
to show unavailable timing.
