# Contributing

Contributions to AI Software Toolkit should help development, QA, security,
and release teams perform reusable work and verify the results. Keep the
distinction between policy, implemented capabilities, and aspiration clear.
See [the vision and maturity map](docs/vision.md).

## Where changes belong

- `policies/` defines organization requirements and the control catalog.
- `pr-review/` defines what AI reviews.
- `workflows/` defines how checks execute.
- `guardrails/` defines evidence schemas and deterministic evaluation.
- `rulesets/` defines GitHub enforcement templates.
- `skills/`, `prompts/`, and `templates/` provide reusable agent capabilities.
- `tooling/` contains deterministic installers and validators.
- `examples/` contains executable consumer examples.

Keep application-specific architecture, commands, customer data, credentials,
private repository inventories, and product-specific rules in the application
repository that owns them.

## Guardrail inclusion test

An enforced control needs all of the following:

- a concrete risk or failure mode
- a human-readable policy statement
- a control-catalog entry
- a deterministic producer or explicit external integration contract
- revision-bound evidence
- positive and negative tests
- a clear enforcement level: required, required when configured, or advisory

Keep decisions visible. Do not add hidden policy inheritance, silent fallbacks,
scoring that changes outcomes, or authority to commit, merge, deploy, publish,
delete, or change external settings.

## Skills and workflows

Add a shared skill only when the workflow is repeated, fragile, and broadly
useful. Every skill needs frontmatter, `agents/openai.yaml`, inputs, outputs,
verification steps, and documented failure behavior.

Workflow templates must identify their required inputs, permissions, secrets,
external services, check name, and failure behavior. Never add a provider-
specific or credential-dependent workflow that cannot execute in a consuming
repository.

## Documentation and license

Every policy or implementation change must update the relevant canonical
documentation. New first-party content is covered by the MIT License unless a file
contains a more specific notice. Preserve license and attribution notices for
third-party integrations or copied material.

## Validation

```sh
python3 -m pip install --disable-pip-version-check -r tooling/requirements-ci.txt
tooling/build.sh
GUARDRAILS_COVERAGE_BASE_REF=origin/main tooling/changed_code_coverage.sh
python3 tooling/validators/validate_repository.py
python3 tooling/validators/validate_documentation.py
python3 tooling/validate-skills.py
tooling/test.sh
python3 examples/python-demo/tools/validate_demo.py --documentation
tooling/lint.sh
python3 tooling/validators/validate_no_migrations.py
git diff --check
```

Before making a new status check required, run it on a representative change,
confirm its actual GitHub check-run name, and add that name to the ruleset only
after the failure and recovery behavior are understood.

## Release readiness

Before a toolkit release:

1. Run the validators, unit tests, and documentation link checks.
2. Review workflow permissions, pinned action references, and provider secrets.
3. Refresh and validate the embedded Python example.
4. Run a real pull request and inspect the scorecard artifact and PR comment.
5. Record any provider that remains advisory or not activated.

Keep release claims tied to observed evidence. A catalog entry or workflow file
is not proof that a provider is active.
