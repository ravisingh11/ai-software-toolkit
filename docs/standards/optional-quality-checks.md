# Optional quality checks

Each consuming repository chooses its checks, source scope, thresholds, and
Proof modes. These recipes do not change shared profiles, require status
checks, edit branch protection, or activate a provider. A diagnostic command
returns a nonzero exit status when its selected criteria are unmet; whether
that result blocks delivery belongs to the repository's policy and CI.

## Choose tools for your language

**The supplied lint and architecture configurations are TypeScript examples,
not a universal or multi-language lint pack.** Quality goals are shared;
linters, formatters, compiler checks, and architecture rules depend on the
language and build system. Use another language's native tools and configure
its repository commands, or add a separately tested toolkit adapter/recipe.
Do not extend the example's ESLint rules expecting them to analyze Java.
Some analysis platforms support multiple languages, but their language-specific
rules, build requirements, and configuration still need to be selected.

| Language | Example lint/static-analysis tools | What this change supplies |
| --- | --- | --- |
| TypeScript | ESLint with typescript-eslint | Example configuration and engine verification; tools remain consumer-installed |
| Java | [Checkstyle](https://checkstyle.org/checks/), [PMD](https://pmd.github.io/pmd/pmd_languages_java.html), [SpotBugs](https://spotbugs.github.io/spotbugs-maven-plugin/index.html) | Tool-selection guidance; no Java configuration or tested adapter |
| Python | [Ruff](https://docs.astral.sh/ruff/) | Command guidance; the toolkit's own Python lint configuration is not an application-wide preset |
| Swift | [SwiftLint](https://github.com/realm/SwiftLint) | Tool-selection guidance; no Swift configuration or tested adapter |
| Kotlin | [detekt](https://detekt.dev/) | Tool-selection guidance; no Kotlin configuration or tested adapter |

These are choices, not a required combined stack. For Java, a repository might
select [google-java-format](https://github.com/google/google-java-format) for
formatting and [ArchUnit](https://www.archunit.org/userguide/html/000_Index.html)
for architecture tests, then connect its configured Maven or Gradle tasks to
Proof. The TypeScript dependency-cruiser rules do not analyze Java classes.
Automatic command discovery currently recognizes Python and Node projects;
Java and other languages need manually supplied commands or a new tested
discovery adapter. Naming tools here does not install or activate them.

The two Python report helpers are reusable across application languages, but
their input contracts still apply. The test helper needs a fresh compatible
JUnit XML report; a build emitting multiple reports needs a repository-owned
aggregation step or a different test command/provider. The coverage helper
accepts Cobertura XML, not arbitrary XML. Java's native
[JaCoCo XML](https://www.jacoco.org/jacoco/trunk/doc/report-mojo.html) needs a
compatible conversion step, or the repository can use its own changed-coverage
command/provider. These integrations are not implemented or verified here.
The helpers need a Python interpreter even when testing another language.

## Included building blocks

| Area | Building block | Repository-owned decision |
| --- | --- | --- |
| Real linting | [TypeScript configuration](../../examples/typescript-quality/eslint.config.mjs) | Linter, rules, paths, baseline, formatting and type-check commands |
| Test integrity | `tooling/check_test_integrity.py` | Suite, minimum discovered tests, skipped-test budget |
| Defensive behavior | [Executable example](../../examples/typescript-quality/tests/defensive.test.mjs) and [scenarios](../../policies/defensive-testing.md) | Product invariants and real integration tests |
| Changed-code coverage | `tooling/check_changed_coverage.py` | Comparison commit, covered source paths, percentage |
| Architecture | [dependency-cruiser configuration](../../examples/typescript-quality/dependency-cruiser.cjs) | Allowed dependency directions, entry points, exceptions |

New installations and refreshes also copy the two Python helpers to
`.proof/check_test_integrity.py` and `.proof/check_changed_coverage.py`.
Copying them does not execute them. Existing installations need a reviewed
toolkit update before using those paths. In this toolkit checkout, run the
`tooling/` source paths instead.

## Separate formatting, linting, and type checking

Keep distinct commands such as `format:check`, `lint`, and `typecheck`.
`tsc --noEmit` detects type errors; it is not a formatting or lint check.
Discovery withholds recognizable compiler-only `lint`/`check` scripts,
including local script aliases, and explains the gap. Unknown wrappers remain
proposed commands requiring review; discovery does not prove they lint.

The TypeScript example enables type-aware rules for floating/misused promises,
unsafe values, non-null assertions, empty catches, and unsafe finally blocks.
Its formatting command is separate. Install compatible external tools only in
repositories that select this recipe; the toolkit adds no Node dependencies
and never downloads these engines during discovery or installation.

For Python, the corresponding consumer command can combine
`ruff format --check .`, `ruff check .`, and a separately selected type checker.
Baseline existing debt deliberately instead of silently excluding changed code.

## Require an actual test result

Run a JUnit-producing test command through the helper. It substitutes a fresh
absolute report path into `{report}` and runs argv without a shell:

```sh
python3 .proof/check_test_integrity.py --min-tests 1 --max-skipped-percent 10 -- \
  pnpm exec vitest run --reporter=junit --outputFile={report}
```

The minimum counts discovered testcase elements; the skipped percentage is a
separate budget. An entirely skipped suite always fails. Missing, empty,
malformed or contradictory reports, zero cases, test failures, command
failures, and unsupported XML declarations fail the diagnostic. Aggregate
counts cannot substitute for actual testcase elements. An earlier report at
another path cannot satisfy this invocation.

This establishes test execution and report integrity, not meaningful assertions,
complete discovery, or trusted CI provenance. A deliberately fabricated report
is still self-reported data. Review suite scope and use behavioral regression
tests, including a failing demonstration when practical.

## Test defensive behavior

Use the same runner for a separately selected defensive suite, or include that
suite in the repository's normal test command. The example runs with Node.js
22.18+ without a test-framework dependency:

```sh
python3 tooling/check_test_integrity.py \
  --working-directory examples/typescript-quality -- \
  node --test --test-reporter=junit --test-reporter-destination={report} \
  tests/defensive.test.mjs
```

It checks unauthorized callers, foreign-tenant identifiers, insufficient roles,
and invalid pagination inputs. These are examples, not proof about a consuming
application. That application owns tests through its actual auth, routing,
storage, and integration boundaries. The [defensive testing policy](../../policies/defensive-testing.md)
also covers retries, idempotency, errors, resource limits, and concurrency.

## Measure changed-code coverage

The generic helper uses the existing pinned `diff-cover` dependency from
`tooling/requirements-ci.txt`. The repository supplies a Cobertura-producing
coverage command, explicit source paths, comparison ref, and target:

```sh
python3 .proof/check_changed_coverage.py \
  --base origin/main --threshold 90 --source src -- \
  pnpm exec vitest run --coverage --coverage.reporter=cobertura \
  --coverage.reportsDirectory={report_dir}
```

`90` illustrates a repository choice, not a shared enforced threshold.
`{report}` supports tools that accept an XML filename; `{report_dir}` supports
tools that emit `cobertura-coverage.xml` into a directory. The report must be
created by this invocation. The helper resolves the Git merge base and checks
a committed, clean tracked tree. Commit candidate source changes first;
fetch enough history to resolve the requested base in CI. Run from the
repository root or choose `--working-directory` explicitly.

Choose `--source` paths containing the code you intend to measure, not build
output, documentation, or tests. Repeat the option for multiple source roots.
Missing changed source files, malformed reports, failed commands and missing
comparison history cannot become coverage passes. Deletion-only or out-of-scope
changes are reported as not applicable with no fabricated percentage.

Coverage producers must include zero-hit executable lines. Report completeness
within a reported file remains the producer's responsibility: this helper
cannot detect deliberately omitted instrumentation or incorrect exclusions.
This check measures lines, not branch coverage or assertion strength.

The toolkit's own `tooling/changed_code_coverage.sh` remains its existing
repository-specific check; its selected target is not changed by this recipe.

## Check architecture boundaries

The optional TypeScript dependency-cruiser example checks cycles, unresolved imports,
client-to-server imports, and contracts importing application code. A consumer
can adapt its paths and run:

```sh
pnpm exec depcruise --config dependency-cruiser.cjs src --output-type err-long
```

Adapt TypeScript path aliases and module resolution to the real repository.
Include type-only dependencies when they matter. Static import analysis does
not establish runtime tenant isolation or catch every computed/dynamic import.

## Connect to Proof only when selected

Use existing repository-owned commands and capabilities. For example, set
`PROOF_FORMAT_LINT_COMMAND` to the selected formatting, lint, typecheck, and
architecture commands; `PROOF_UNIT_TEST_COMMAND` to test-integrity wrapper(s);
and `PROOF_CHANGED_COVERAGE_COMMAND` to the chosen coverage command. Compose
selected commands with `&&` so earlier diagnostic failures are retained.
Do not put secrets in commands or committed configuration.

The existing Proof modes remain `not_activated`, `advisory`, and `enforced`.
Repository owners may keep checks advisory, disable them, or separately choose
enforcement. No new catalog controls or default required checks are introduced
here. Composed checks share their selected existing capability's scorecard row;
they do not become separate rows.

## Verify the recipes

`tooling/tests/test_check_test_integrity.py` and
`tooling/tests/test_check_changed_coverage.py` cover successful and failing
reports, stale/missing output and configuration failures. The coverage suite
also exercises real diff-cover when installed.
`tooling/tests/test_typescript_quality_example.py` runs the defensive example,
removes its tenant check in a temporary copy, and confirms the tests fail.

To opt into tests against installed external lint/architecture engines, set
`PROOF_TYPESCRIPT_TOOLS` to the absolute `node_modules/.bin` directory of a
compatible local installation, then run that example test module. The tests
exercise real ESLint and dependency-cruiser failures; they do not install tools.
Without that variable the external-engine test is explicitly skipped. Normal
toolkit validation does not require a consumer to adopt those tools.
