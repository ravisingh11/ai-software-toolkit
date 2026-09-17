# Sample Guardrails v2 scorecard

**Illustrative fixture, not a live scan.** The timestamp, evidence path, and
outcomes below are examples, not evidence from the current checkout or a
published release. This representative output shows all four readiness colors.
The build capability is enforced and has no authoritative result, so the overall decision
is `BLOCK`. Advisory gaps remain `ORANGE`; inactive capabilities remain `GRAY`.

```text
# Guardrail Scan Report

- Status: **RED**
- Decision: **BLOCK**
- Evidence: `.artifacts/guardrails/evidence-20260828-120000Z.json`

| Readiness | Mode | Capability — Provider | Evidence |
| --- | --- | --- | --- |
| GREEN | advisory | Repository Validation — Repository Validators | passed |
| ORANGE | advisory | PR Change Scope — PR Change Scope | failed |
| ORANGE | advisory | Documentation Validation — Repository Validators | no_result |
| RED | enforced | Build — Repository Build Command | no_result |
| GREEN | advisory | Unit Tests — Repository Unit Test Command | passed |
| ORANGE | advisory | Custom Static Analysis — Semgrep Community Edition | no_result |
| ORANGE | advisory | Secret Detection — Gitleaks CLI | no_result |
| ORANGE | advisory | Deep SAST — GitHub CodeQL | no_result |
| GRAY | not_activated | Artifact Provenance — Not activated | not_activated |
| GRAY | not_activated | Container Vulnerability — Not activated | not_activated |
```

For example, a scope check can explain the orange row directly:

```text
Meaningful: 17 files, 1,284 changed lines (916 added). Total: 19 files,
1,472 changed lines. Excluded: 2 files, 188 changed lines.
```

The mechanical provider owns those counts. AI review may identify three
concern clusters and recommend independent PR boundaries, but it does not
recalculate the metrics or change the policy decision.

The real `--all-catalog-controls` report includes every catalog capability. The
abbreviated table preserves the exact renderer vocabulary and row format. Its
`Artifact Provenance` row is catalog visibility only; the current release
attestation workflow does not produce nested artifact evidence for a release
scorecard.

Generate a current report with:

```sh
python3 .guardrails/scan.py --all-catalog-controls
```

Run this in a committed, clean consumer repository after configuring its real
commands. The [release-pinned walkthrough](../../README.md#start-here) creates
an isolated demo; its advisory defaults differ from the enforced build in this
fixture. Read the newly generated Markdown and JSON under
`.artifacts/guardrails/` for your actual revision, provider results, and reasons.
Missing tools and command variables can legitimately leave rows orange.

The setup doctor reports setup states
(`configured`, `action_needed`, `unverified`), not these scorecard colors.
Neither `configured` nor its zero exit code means a provider passed. See
[setup diagnostics](../quickstart.md#diagnose-installation).

See the runnable [Python demo](../../examples/python-demo/) and the
[status guide](../control-status.md).
