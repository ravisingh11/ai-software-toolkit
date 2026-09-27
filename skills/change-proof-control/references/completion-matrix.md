# Proof change completion matrix

Copy this table into the implementation notes or final report. A row is complete
only when its evidence is current and directly supports the claim.

| Surface | Status | Exact evidence or link | Owner / next action |
| --- | --- | --- | --- |
| Capability contract | Pending | Catalog entry, stage, availability, evidence subject, and enforcement policy agree. | |
| Provider contract | Pending | Authoritative/supplemental selection, producer name, check/review contract, secrets, and failure mapping validate. | |
| Canonical implementation | Pending | Runtime, schema, adapter, and canonical workflow changes are covered by focused tests. | |
| Distribution | Pending | Installer mapping and installed self/demo copies match canonical sources. | |
| Local behavior | Pending | For scanner-supported subjects, a clean exact-revision scan shows pass, fail, blocked, and no-result behavior. For `pull-request`, use hosted workflow/evaluator proof bound to the exact PR head. | |
| GitHub activation | Pending | Required variables, secrets, settings, and provider-side configuration are present without exposing values. | |
| Hosted lifecycle proof | Pending | Active: the declared operation reports the expected result for its evidence subject. Scoped deactivation: only the intended scope becomes inactive. Catalog removed: contract/copy absence and inactive-or-absent output are proven. Profile removed: consumer selections migrate and affected controls preserve their intended state. Provider replaced: prior activation is preserved and an active selection runs through the replacement. | |
| Evidence provenance | Pending | The collector accepts the provider identity, exact subject/revision, and proof required by its check-run, review, local, artifact, or environment contract. Control removed: no stale evidence satisfies the control. Provider replaced: the former provider cannot satisfy the affected selection; require global rejection only when it is decommissioned. | |
| Scorecard outputs | Pending | Every output promised by the workflow contract shows the provider result and correct readiness/decision; require a PR comment only when implemented. | |
| Enforcement | Pending | Policy and lifecycle gates agree. Context dependencies are mapped, and required contexts isolate enforced outcomes from advisory siblings. Replacement adds a stable gate before retiring an exclusive old gate or splitting/reconfiguring a shared one. Demotion, deactivation, and removal stop the affected outcome from failing retained gates without weakening other enforced outcomes. | |
| Documentation | Pending | Setup, status, troubleshooting, provider extension, and migration guidance use the public vocabulary. | |

## Required negative proofs

- Remove or invalidate required configuration: the producer must not pass.
- Supply stale or wrong-subject evidence: the collector must reject it.
- Fail the underlying tool: evidence and the scorecard must retain the failure.
- Remove a distributed runtime dependency: repository validation must fail.
- Select an operation-inapplicable or advisory-only enforcement mode: policy
  validation must reject it.
- Activate or promote: prove each required context excludes advisory sibling
  outcomes; split or reconfigure an aggregate context when needed.
- Remove a control: installed copies and obsolete gates must drop it; stale
  evidence must be rejected and output must be inactive or absent.
- Remove a profile: profile copies must disappear, consumer selections must
  migrate, and affected controls must retain their intended evidence, state,
  and gates.
- Replace a provider selection: the former provider must no longer satisfy the
  affected capability, and the replacement must preserve its activation state.
  When active, fresh evidence must come from the replacement. When enforced,
  add its stable gate before retiring an exclusive old gate; split or
  reconfigure a shared old gate for remaining controls.
  Drop global provider copies and reject all its evidence only when the provider
  itself is decommissioned.
- Deactivate an operation or profile: prove only that scope is inactive and
  retain shared contracts and producers still used elsewhere. Its outcome must
  not fail a retained shared gate; other enforced outcomes must remain protected.
- Demote an enforced control: remove an exclusive context or split/reconfigure a
  shared one so the demoted outcome cannot fail it. Without hosted authority,
  report enforcement pending rather than advisory.

## Stop conditions

Do not merge while any applicable row lacks evidence, an active required
producer is skipped, a generated copy differs from its canonical source, stale
evidence survives a removal, or unresolved P0/P1 findings remain. Leave optional
provider activation work clearly marked instead of manufacturing a green result.
