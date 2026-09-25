# Run the toolkit against this repository

This repository consumes its installed Guardrails runtime. From a clean,
committed checkout, run:

```sh
tooling/self-check.sh
# Or compare against a different existing local ref or commit:
tooling/self-check.sh HEAD~1
```

The optional positional base defaults to `origin/main`. The launcher resolves it
once to a commit SHA and supplies that same SHA to both the scanner and changed
code coverage. It does not fetch refs; refresh your comparison ref separately
when needed. You can also invoke the script by its absolute path from another
working directory.

## Requirements and boundaries

Use the repository's supported Python environment with the dependencies in
[`tooling/requirements-ci.txt`](../tooling/requirements-ci.txt) available on
`PATH`, including `coverage`, `diff-cover`, `ruff`, and `yamllint`. Git and Bash
are required. The launcher does not install tools or run an inherited setup
command. Semgrep and Gitleaks use the toolkit's pinned Docker images when Docker
is available, or supported host versions (Semgrep 1.175.0 and Gitleaks 8.30.1).
Unavailable tools remain missing evidence. Keep any Python virtual environment
outside the checkout so repository-wide validators inspect project files only.

Tracked edits and nonignored untracked files cause the launcher to stop before
starting the scanner. Evidence describes committed `HEAD`, so commit changes on
a working branch or use an isolated committed snapshot first. A snapshot scan
proves only that snapshot, not the original checkout, a merged change, or a
published release. Ignored artifacts do not make the checkout dirty.

The launcher uses `.guardrails/scan.py` from the repository root and explicitly
selects this repository's installed `.guardrails/policy.yaml`, `profiles.yaml`,
`control-catalog.yaml`, and `providers.yaml`. This preserves the repository's
enforced controls instead of using the shared advisory defaults in the source
distribution. It binds these repository producers, overriding inherited command
settings:

| Producer | Command |
| --- | --- |
| Build | `tooling/build.sh` |
| Unit tests | `tooling/test.sh` |
| Changed code coverage | `tooling/changed_code_coverage.sh` |
| Format and lint | `tooling/lint.sh` |
| Migration validation | `python3 tooling/validators/validate_no_migrations.py` |

The no-migrations validator is deliberate: this toolkit has no application
database. The scanner also invokes available repository, documentation,
ground-truth, and change-scope validators. The launcher does not change policies,
install hooks, make commits, push, or write GitHub settings.

## Reading the result

The scanner prints artifact paths and writes timestamped evidence JSON and a
Markdown scorecard in `.artifacts/guardrails/`, plus the latest evidence at
`.artifacts/guardrails/evidence.json`. Inspect each producer's status and reason.
Missing, skipped, or unconfigured producers are not passes. Local scans cannot
supply GitHub-only provider evidence, so advisory gaps can remain.

The launcher returns the scanner's exit code without masking failures. A zero
exit code means the configured evaluation accepted the evidence; it does not
mean every advisory control passed or a release is approved. Policy modes and
required controls remain unchanged. This command complements the full
validation checklist in [`AGENTS.md`](../AGENTS.md); it does not replace GitHub
checks or deployment evidence.
