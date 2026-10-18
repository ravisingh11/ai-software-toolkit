# Optional TypeScript quality recipes

This example demonstrates separate formatting, real type-aware linting, type
checking, defensive tests, and import boundaries. It does not install tools,
activate Proof controls, or choose enforcement for any repository.

Run the defensive tests with Node.js 22.18+:

```sh
node --test tests/defensive.test.mjs
```

The other package scripts expect repository-selected compatible versions of
Prettier, ESLint, typescript-eslint, TypeScript, and dependency-cruiser on PATH.
The example deliberately declares no dependencies: it is not an installable
standalone toolchain or a new toolkit runtime dependency. Copy and adapt the
configuration in a consuming repository that selects those engines, then
record its versions and lockfile there. The TypeScript lint configuration only
includes `src/`; framework configuration and tests need their own lint scope
in a real application.

`src/server/access.ts` contains illustrative behavior, not reusable production
authentication code. `tests/defensive.test.mjs` checks tenant isolation,
authorization and invalid input. The architecture configuration rejects cycles,
unresolved imports, client-to-server dependencies, and contracts importing
application code. Replace its example paths with your repository's architecture.

Follow the [optional quality-check guide](../../docs/standards/optional-quality-checks.md)
for fresh JUnit reports, changed-code coverage, Proof command composition,
failure demonstrations, and limitations.
