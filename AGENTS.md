# Repository instructions

This repository defines shared engineering policy and the Proof runtime.
Keep changes small, evidence-backed, and reusable across application
repositories.

## Source-of-truth boundaries

- `policies/` defines engineering requirements and the control catalog.
- `pr-review/` defines AI review behavior.
- `workflows/` and `.github/workflows/` define reusable and repository CI.
- `proof/` and `tooling/` implement deterministic evaluation and setup.
- `rulesets/` defines GitHub enforcement templates.
- `skills/` contains reusable agent instructions.
- `examples/` demonstrates consumption without becoming organization policy.

Do not add application-specific architecture, credentials, customer data, or
private repository details here. A consuming repository owns its own
`AGENTS.md`, architecture, testing, security, deployment, and contribution
ground truth.

This repository has no application database or migration framework. Adding a
database migration surface requires replacing the no-migrations validator with
the chosen framework's real migration validation command in the same change.

## Change contract

- Use a pull request for every normal change to the default branch.
- No approving review is required for a solo maintainer unless the repository
  ruleset is intentionally strengthened.
- Keep controls advisory until their producer, evidence, status-check name,
  failure behavior, and owner have been verified on representative changes.
- Never report a missing, skipped, stale, or unconfigured producer as passed.
- Keep provider credentials in GitHub secrets or the provider platform; never
  commit them.
- Preserve the `.proof/` public runtime contract and document migrations.

## Verification

Run the smallest relevant checks while working. Before opening or updating a
pull request, run the complete repository validation:

```sh
tooling/build.sh
tooling/test.sh
PROOF_COVERAGE_BASE_REF=origin/main tooling/changed_code_coverage.sh
python3 examples/python-demo/tools/validate_demo.py --documentation
python3 tooling/validate-skills.py
python3 tooling/validators/validate_repository.py
python3 tooling/validators/validate_documentation.py
python3 tooling/validators/validate_no_migrations.py
tooling/lint.sh
git diff --check
```

Update the canonical policy or documentation whenever behavior changes. State
which controls are advisory, enforced, not activated, or awaiting a real
producer; do not imply that a workflow file alone proves activation.
