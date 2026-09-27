# Validators

Run the dependency-free repository validator from the repository root:

```sh
python3 tooling/validators/validate_repository.py
```

It validates skill metadata and references, checks machine-local path hygiene,
validates policy and evidence examples through the core evaluator, checks the
distribution adapters, validates documentation integrity, and runs bundled unit
tests.

Run documentation validation directly:

```sh
python3 tooling/validators/validate_documentation.py
```

`.proof/documentation.yaml` maps implementation paths to source-of-truth
documents. With `--base-ref` and `--head-ref`, the validator fails when a
mapped implementation change has no documentation change. It always checks
local Markdown links and mapped documentation targets.

Inspect file and line scope:

```sh
python3 tooling/validators/inspect_change_scope.py
```

Thresholds come from `.proof/change-scope.yaml`. Findings are advisory:
the command records them and exits successfully unless configuration or Git
input is invalid.

See [Proof directories](../../README.md#proof-directories) for the
shared-source and repository-installation boundary.
