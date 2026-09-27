---
name: change-proof-control
description: "Use when adding, activating, changing, promoting, demoting, replacing, or removing a Proof capability, provider, producer workflow, profile, policy override, enforcement mode, evidence contract, or GitHub check."
---

# Change Proof Control

Keep policy, runtime, workflows, evidence, scorecards, and docs aligned.

## Non-negotiable outcome

Configuration, a token, or a workflow file does not prove activation. Require
fresh provider evidence for the declared operation and subject. Catalog
decommissioning requires proof that its contract and distributed copies are
absent. Scoped deactivation must preserve shared contracts used elsewhere.
Provider replacement must preserve the capability's activation state. Missing,
skipped, stale, or unconfigured work must never become a pass.

## Workflow

1. Read `AGENTS.md`. In this source, read the architecture,
   producer-contract, status, and setup docs. In a consumer, inspect
   `.proof/`, its ground-truth inventory, and docs discovered with `rg`;
   do not assume fixed paths.
2. Define before editing: capability ID, stage, availability, evidence subject,
   enforcement policy, provider selection, producer/check, transition scope,
   activation requirements, status mapping, and unconfigured behavior.
3. Map affected policy, schemas, runtime, providers, installer mappings,
   workflows/copies, examples, rulesets, tests, and docs.
   Separate installer-owned artifacts from consumer-owned configuration,
   including `.proof/policy.yaml`, `.proof/providers.yaml`, mappings,
   thresholds, and ground-truth paths. Edit consumer choices directly; never
   fix only an installer-owned/generated copy.
4. Add a failing regression test. Cover success, failure, missing configuration,
   stale/wrong-subject evidence, and distribution when relevant.
5. Make the canonical change. Refresh installer-owned copies through the
   installer or documented distribution mechanism.
6. Run targeted tests, then complete `AGENTS.md` validation.
   Check workflow syntax, schemas, links, and
   `git diff --check`.
7. Change hosted variables, secrets, settings, or provider projects only with
   explicit authorization under consumer security/contribution rules; otherwise
   report activation pending. Never expose credentials.
8. When explicitly authorized, follow the contribution process, open a PR, and
   run the declared operation against its evidence subject; never infer one
   solely from the other. Verify contract-promised evidence, outputs, scorecard
   state, and failure/no-result behavior. For catalog removal, prove
   contract/copy absence, stale-evidence rejection, inactive/absent output, and
   gate retirement. For profile removal, remove profile copies, migrate consumer
   selections, and preserve affected controls' intended state, evidence, and
   gates. For scoped deactivation, prove that scope is inactive, preserve shared
   contracts/producers, and remove its gate only when unused by enforced scopes.
   For provider replacement, prove
   the former provider cannot satisfy the affected selection and the replacement
   preserves its activation state, including evidence when active. Require
   global absence only when the provider is decommissioned.
9. Activate advisory until reliable. Never enforce `advisory-only` controls or
   AI review alone. Before enforcement changes, map each context's controls;
   required contexts must isolate enforced from advisory outcomes. Use stable
   PR-head contexts and release/environment lifecycle gates. On replacement,
   add the stable new gate before retiring an exclusive old one; split/reconfigure
   shared gates. For demotion, deactivation, or removal,
   prove the affected outcome cannot fail a retained shared gate while other
   enforced outcomes remain protected. Without hosted authority, report
   enforcement pending, not advisory.

## Completion report

Use `references/completion-matrix.md`. Report unverified rows, changes,
validation, hosted runs, pending activation, and enforcement; never infer proof.
