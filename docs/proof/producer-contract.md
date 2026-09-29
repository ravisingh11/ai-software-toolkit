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

### Optional PR-size measurements

The `change-scope.repository-change-scope` result may include `change_scope`
with `version: 1`, aggregate `metrics`, and the four configured `thresholds`.
This optional display metadata is accepted only for `passed` or `failed`
results. Counts must be nonnegative integers, thresholds positive integers,
totals consistent, and the status must match whether a threshold was exceeded.
The schema defines the exact allowed numeric fields and bounds. No filenames
or findings belong in this metadata.

Evidence without this field remains valid. Refresh the evaluator, schema,
collector, scope producer, and renderer together before emitting it; older
runtimes reject unknown result fields. The GitHub collector retains the trusted
producer status but omits unavailable or malformed optional measurements.
The dashboard then displays measurements as unavailable. This extension does
not change policy evaluation or promote scope from advisory to enforced.

### Optional PR metadata detail

The `pr-metadata.repository-pr-metadata` result may include `pr_metadata`
with `version: 1`, a boolean `title_matches`, and the integer counts
`required_sections` and `missing_sections` (0–20, missing never above
required). It is accepted only for `passed` or `failed` results and on no
other control or provider, and `passed` must equal "title matches and zero
missing sections". The trusted base-branch `validate_pr_metadata.py` produces
it, so it is not labeled self-reported. It never carries the title, body, or
section names.

The PR Metadata workflow copies the detail into its run-bound artifact. The
GitHub collector attaches it after artifact provenance passes and omits a
missing or malformed value without changing the proven status. The dashboard
re-validates it and shows, for example, **Title matches the required format ·
3 of 3 required sections present**; without it, the card states which detail
was not reported. Refresh the evaluator, schema, validator, collector,
renderer, and `pr-metadata.yml` together; older runtimes reject unknown result
fields.

### Optional self-reported test, coverage, and validator measurements

A `unit-tests` result may include `measurements` with `version: 1`,
`source: "pull-request-workflow"`, and `tests` (`total`, `passed`, `failed`,
`skipped`). A `changed-code-coverage` result may include `measurements` with
the same `version` and `source` and `coverage` (`measured_lines`,
`covered_lines`, `threshold_percent`). Measurements are accepted only for
`passed` or `failed` results and on no other control. Counts are nonnegative
integers; `total` must equal the sum of its parts and be positive; covered
lines cannot exceed measured lines; the threshold is 0–100. A `passed` result
cannot report failed tests or coverage below its threshold.

The repository validators report counts the same way, each on its own
control:

| Control | Kind | Fields | Consistency rules |
| --- | --- | --- | --- |
| `repository-validation` | `contracts` | `total`, `passed`, `failed`, `not_run` | `total` is positive and equals the sum; `passed` means no failed or not-run groups; `failed` needs a failed group |
| `documentation-validation` | `documentation` | `markdown_files`, `links_checked`, `broken_links`, `mapping_failures` | Broken links cannot exceed links checked; `passed` exactly when there are no broken links or mapping failures |
| `repository-ground-truth` | `documents` | `declared`, `found`, `missing` | `declared` equals `found + missing`; `passed` exactly when nothing is missing |
| `migration-validation` | `migrations` | `checked`, `failed` | Failed cannot exceed checked; `passed` cannot report failures |

The installed repository validator runs its contract groups in order and stops
at the first failure, so later groups count as `not_run`. The ground-truth
validator counts documents declared in `.proof/ground-truth-ai.yaml` and checks
only that each exists; it does not assess their contents. Migration
Validation runs a repository-owned command, so its counts appear only when
that command writes `migrations` to `PROOF_MEASUREMENTS_FILE`; zero checked
means no migrations were found to check. This repository's
`validate_no_migrations.py` counts each migration surface it finds as checked
and failed, because the repository declares none. Build and Format and Lint
report only their command's exit status. A validator that
cannot read its own configuration writes no measurements. Document paths and
link targets are never published.

These numbers come from the pull request's own workflow run, which executes
the pull request's code, so they are **self-reported**. They are display
metadata only: they never change a result's status, and the dashboard labels
them as not independently verified. `tooling/proof_measurements.py`
(installed as `.proof/measurements.py`) converts `python -m unittest` logs,
JUnit XML, or a `diff-cover` JSON report into this format and packages it.
Tests that are skipped or marked as expected failures count as skipped,
never as passed.

The provider contract opts in with `measurements_artifact_prefix` and
`measurements_member`, which require a `workflow_path` pull-request check and
no `external_id_prefix`. The workflow sets `PROOF_MEASUREMENTS_FILE`; when the
configured command writes that file, the workflow binds it to the run ID, run
attempt, repository, head SHA, and control, and uploads the artifact
`<prefix><run_id>-<run_attempt>`. The upload step is non-fatal, so an
artifact-service failure never changes the check result. The GitHub collector
attaches the measurements only after the check's own provenance passes, reads
the attempt from the check's own job, and requires every binding to match, so a
re-run never displays an earlier attempt's numbers. Missing,
expired, duplicated, unbound, or inconsistent measurements are omitted
without changing the check result, and the dashboard shows them as not
collected.

Adapters written by this toolkit start a `blocked` or `not_run` reason with a
standard code followed by a colon: `configuration-missing`,
`credential-missing`, `authentication-failed`, `execution-error`,
`analysis-incomplete`, `revision-mismatch`, `unsupported-project`, or
`timed-out`. The code is a prefix of `reason`, so the evidence schema is
unchanged; reports use it to choose a next action. See the
[reason code reference](../providers/README.md#reason-codes).

## Provider selection

`.proof/providers.yaml` defines each provider's capabilities, display name,
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

`.proof/scan.py` resolves a clean full `HEAD` before local producers can
pass. Repository commands run from `PROOF_WORKING_DIRECTORY`; absent
commands report `not_run`. The scanner verifies the same clean revision before
and after each configured command and local tool, so one producer cannot change
the tree consumed by the next or publish passing evidence for a different tree.
Semgrep CE and Gitleaks use pinned containers or exactly matching host versions.
Before a Docker Gitleaks scan, the producer verifies that the container can
read complete Git history at the same `HEAD` as the host. An inaccessible,
shallow, or mismatched mount produces no usable evidence. A zero-commit scan
cannot pass merely because the scanner exits successfully.

External adapters may place `*.json` fragments in
`.artifacts/proof/evidence/`. The scanner accepts only nested v2 fragments
with the same subject. Different results for the same capability/provider pair
are a contract error. The installed `.proof/adapter.py` writes such
fragments for Snyk Code, Snyk Open Source, and FOSSA after running the
adapter-owned command sequence for the exact `HEAD`.

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

GitHub review providers use a separate review contract. Proof accepts a
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
