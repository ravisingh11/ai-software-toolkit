# Ruleset import notes

`default-branch-protection.json` is an import-oriented baseline for pull-request
protection. It requires a PR, resolved review threads, no force push, and no
branch deletion. It intentionally contains no required status checks because a
shared template cannot know which providers are activated in a consumer.

## Activate the baseline

Review the JSON against the current GitHub ruleset schema, import or create it
for the target repository, and verify `~DEFAULT_BRANCH` resolves as intended.
The template has no bypass actors and requires zero approving reviews so a solo
maintainer can use it without a standing bypass.

Repositories can raise `required_approving_review_count`, require code-owner
review after adding a real `CODEOWNERS` file, or enable last-push approval based
on their ownership model.

## Add status checks only after proof

For each capability:

1. Select the profile or explicit mode override.
2. Configure its authoritative provider.
3. Run it on representative pull requests.
4. Confirm exact-subject evidence and truthful skip/failure behavior.
5. Record the exact stable check context GitHub displays.
6. Set the capability to `enforced`.
7. Add that exact context to `required_status_checks`.

Do not require a setup job, configuration probe, supplemental provider, or
scorecard aggregation as a substitute for authoritative capability evidence.
An unset variable or missing token must never satisfy a capability. Depending
on the producer, it becomes `NO RESULT` or an explicit failing check. Format and
lint and migration validation intentionally fail when their repository command
is absent.

## Current v2 check names

| Profile | Capability check names |
| --- | --- |
| Core | `Validate / repository`, `Validate / docs`, `Validate / ground truth`, `PR Change Scope`, `PR Metadata`, `Format and Lint`, `Migration Validation`, `Build`, `Unit Tests`, `Changed Code Coverage`, `Semgrep CE`, `Gitleaks` |
| GitHub overlay | `CodeQL`, `Dependency Review`, `GitHub Secret Scan`, `Dependabot Verification` |

`Artifact Provenance` is a release/dispatch attestation job, not a pull-request
check, and it does not yet produce nested artifact evidence for a Guardrails
release scorecard. Do not add it to branch-protection required checks.

GitHub can render a workflow/job combination differently depending on how a
workflow is installed. Always copy the context from a real check run rather
than relying only on this table.

Before requiring `Format and Lint` or `Migration Validation`, set its repository
command variable, observe a successful and a failing representative run, and
then copy the exact context into the ruleset. If the variable is later removed,
the named check fails instead of satisfying branch protection through a skip.

Do not require `PR Change Scope` while it is advisory: an oversized PR then
publishes a neutral custom check and remains `ORANGE / ALLOW`. After promotion
to `enforced`, require the exact observed `PR Change Scope` context so an
oversized PR blocks merge.

## Provider and policy separation

Policy mode and branch protection are separate controls. `enforced` policy
without a required GitHub context does not protect merge. A required context
without a reliable authoritative provider can deadlock merge.

Supplemental providers remain advisory and should not be required for the same
capability merely because they are visible in the scorecard.

Rulesets cannot configure credentials, enable GitHub security settings, create
external vendor projects, or prove a provider ran. Complete those activation
steps first.

See [control setup](../docs/guardrails/control-setup.md), [status](../docs/guardrails/control-status.md),
and [workflow guidance](../workflows/README.md).
