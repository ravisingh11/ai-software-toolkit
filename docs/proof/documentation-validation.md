# Map code changes to documentation

Documentation validation checks relative links, declared document targets, and
code-to-document mappings. A filename match establishes coverage, not that the
document is accurate. Review the content as part of the PR.

Edit `.proof/documentation.yaml` using the existing version 1 format. Use paths
that exist in your repository; do not keep generic `src/**` rules if your code
lives elsewhere. For example:

```json
{
  "version": 1,
  "mappings": [
    {"name": "public-api", "triggers": ["app/api/**", "lib/contracts/**"], "documents": ["docs/api.md"]},
    {"name": "database", "triggers": ["migrations/**"], "documents": ["docs/data-migrations.md", "docs/rollback.md"]},
    {"name": "setup", "triggers": ["package.json", "tooling/**"], "documents": ["README.md", "docs/setup.md"]}
  ]
}
```

Create and track every declared document, or adjust the mappings. Every document
pattern must match an existing repository file. When any trigger changes, at
least one of the mapping's document patterns must change in the comparison.
Split mappings when both API and migration instructions need separate updates;
multiple `documents` in one mapping are alternatives, not an all-documents rule.

## Local inspection and CI

From your consumer repository, inspect tracked paths with `git ls-files`. Commit
or stage new documentation so it is included in the tracked inventory. Configure
real mappings and review the diff before running validation:

```sh
python3 .proof/validators/validate_documentation.py --policy .proof/documentation.yaml
python3 .proof/validators/validate_documentation.py --policy .proof/documentation.yaml --base-ref origin/main --head-ref HEAD
```

Doctor inspects mapping configuration and target availability without running link
or change-comparison producers. The first command checks integrity only. The second also checks changed-file
mappings; fetch the actual comparison base first. `--changed-file path` can supply
an explicit reviewed changed-file list. Missing policy, invalid mappings, or an
unavailable requested comparison base fail; none becomes a pass.

The optional `repository-validation.yml` workflow runs `Validate / docs` with
explicit PR base/head revisions. Install the template only if you want that CI
producer, preserve full history, and inspect its exact revision and result before
making it required. Local and CI execution remain separate choices; doctor does
not run either command. See [activation](../activation.md#documentation-validation).

## Inventory boundary

In Git, validation scans Git-tracked repository files, including staged additions.
Ignored or untracked dependency/generated Markdown cannot break the scan or satisfy
a document mapping. Inventory queries disable filesystem monitors, hooks, and
optional Git locks so setup inspection cannot invoke repository-configured helpers.
Intentionally tracked generated documentation is still source
owned by the repository and is checked. A failed Git inventory query is an error.

A non-Git source snapshot uses a sorted filesystem inventory. The validator
excludes dependency directories (`node_modules`, `vendor`, virtual environments),
generated output (`dist`, `build`, `target`, `coverage`, `generated`), caches and
local artifacts. It never follows a file link outside the snapshot. A snapshot
can verify integrity; Git comparison checks still require an available baseline.
The canonical implementation is `tooling/validators/validate_documentation.py`;
`.proof/validators/validate_documentation.py` is its installed public path.
