# Provider and evidence contract

The scorecard aggregates provider evidence. It is not a build, test runner,
scanner, reviewer, or platform setting.

## Nested v2 evidence

Evidence groups provider results under the capability they support:

```json
{
  "$schema": "./evidence.schema.json",
  "version": 2,
  "subject": {
    "type": "git-commit",
    "revision": "0123456789abcdef0123456789abcdef01234567"
  },
  "results": {
    "unit-tests": {
      "repository-unit-tests": {
        "producer": "Repository Unit Test Command",
        "status": "passed",
        "evidence": ["command: python3 -m unittest"]
      }
    },
    "deep-sast": {
      "github-codeql": {
        "producer": "GitHub CodeQL",
        "status": "not_run",
        "reason": "GitHub profile is not selected"
      }
    }
  }
}
```

Subject types are `git-commit`, `pull-request`, `artifact`, and `environment`. The catalog
declares which subject type each capability accepts.

## Result requirements

| Raw status | Required fields | Meaning |
| --- | --- | --- |
| `passed` | non-empty `evidence` list | Provider completed successfully for the exact subject. |
| `failed` | non-empty `evidence` list | Provider completed and found a failure. |
| `blocked` | non-empty `reason` | Provider could not complete. |
| `not_run` | non-empty `reason` | No usable provider result exists. |

Every result also requires a non-empty `producer`. Evidence records must not
contain credentials or secret values.

## Provider selection

`.guardrails/providers.yaml` defines each provider's capabilities, display name,
activation category, check contracts, declared secrets, and template metadata.
Its `selections` object assigns exactly one authoritative provider and zero or
more supplemental providers to every runnable capability.

A provider may use check-run contracts for some capabilities and review
contracts for others. It must not declare both contract types for the same
capability; configuration validation rejects that ambiguity before evidence is
collected.

Only the authoritative provider can satisfy or block a capability. Supplemental
providers appear in the scorecard with `advisory: true` and never change the
decision.

## Local evidence

`.guardrails/scan.py` resolves a clean full `HEAD` before local producers can
pass. Repository commands run from `GUARDRAILS_WORKING_DIRECTORY`; absent
commands report `not_run`. The scanner verifies the same clean revision before
and after each configured command and local tool, so one producer cannot change
the tree consumed by the next or publish passing evidence for a different tree.
Semgrep CE and Gitleaks use pinned containers or exactly matching host versions.
Before a Docker Gitleaks scan, the producer verifies that the container can
read complete Git history at the same `HEAD` as the host. An inaccessible,
shallow, or mismatched mount produces no usable evidence. A zero-commit scan
cannot pass merely because the scanner exits successfully.

External adapters may place `*.json` fragments in
`.artifacts/guardrails/evidence/`. The scanner accepts only nested v2 fragments
with the same subject. Different results for the same capability/provider pair
are a contract error.

## GitHub evidence

The GitHub collector derives expected checks from the selected capability and
provider contracts. For each check it verifies:

- exact `head_sha`;
- the `github-actions` app;
- a workflow run ID from the Actions details URL for native checks, or from the
  contract-bound external ID for custom checks (GitHub may rewrite a custom
  check's details URL to its check page);
- the declared workflow name;
- the declared workflow path when present, allowing GitHub's exact `@ref`
  suffix;
- a `pull_request` workflow event with an exact workflow-run head SHA, or a
  `pull_request_target` proof with an exact artifact-bound head association;
- matching workflow-run revision and check-suite identity for native Actions
  checks; and
- the declared external-ID prefix when the provider requires one.

For a custom PR-head check published by a trusted `pull_request_target` probe,
the external ID and details URL bind the custom check to the exact workflow run.
The collector does not equate that custom check suite with the probe workflow's
separate base-SHA suite.

GitHub can return an empty `pull_requests` array for a valid `pull_request`
workflow run. Native checks therefore bind through the event type, exact
workflow-run head SHA, matching check-suite identity, and unchanged trusted
paths. A non-empty association that names a different head is rejected.

| GitHub conclusion | Raw evidence status |
| --- | --- |
| `success` | `passed` |
| `failure` | `failed` |
| `cancelled`, `timed_out`, `action_required`, `stale` | `blocked` |
| `neutral`, `skipped`, missing, or incomplete | `not_run` |

Unverifiable provenance is `not_run`. A check name alone is insufficient.

GitHub review providers use a separate review contract. Guardrails accepts a
completed review only when its `commit_id` equals the evaluated head SHA, its
`user.login` exactly matches configured `review_author`, and GitHub identifies
the account as a bot. The latest matching review is evidence that the review
completed, not a guarantee that the reviewer found every defect. An approved or
comment-only review reports `passed`; `CHANGES_REQUESTED` reports `failed`.
Scorecard workflows refresh on review submission and dismissal, and cancel an
older in-flight scorecard for the same pull request so stale review state cannot
publish last.

## Promotion contract

Before selecting a provider as authoritative or setting its capability to
`enforced`, verify its workflow/adapter, credentials and configuration,
exact-subject binding, check name, failure behavior, and remediation owner. A
credential or workflow file alone does not activate or pass the capability.
Controls marked `advisory-only` in the catalog, including every AI review
control, cannot be promoted to `enforced`.

See [control setup](control-setup.md) and [status](control-status.md).
