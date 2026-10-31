# Checkpoint readiness and handoff integrity

The v2.4.0 candidate adds checkpoint planning and integrity verification beside
Proof. The 33 catalog checks, two operations, four Proof subject types, provider
authority and scoring are unchanged. Skills remain in the toolkit; AgentBay is
an optional discovery source. Human work and local/external skills are valid
inputs, not passing evidence by themselves.

The CLI dispatches to `tooling/checkpoints.py`; installed repositories also
receive `.proof/checkpoints.py` and `.proof/assurance.py` through the supported
installer. The portable verifier remains standard-library-only.

If an existing consumer owns a file at a newly introduced checkpoint-helper
path, reinitialization/update preserve its bytes and do not adopt its ownership.
An update offers the canonical helper separately as a conflict. Review that
collision explicitly; do not run a consumer-owned file as a trusted verifier.

## Plan without executing

```sh
python3 tooling/ai_toolkit checkpoint plan --checkpoint pre-commit --target /path/to/repo
python3 tooling/ai_toolkit checkpoint plan --checkpoint pre-merge --target /path/to/repo --json
```

The planner reads installed policy/catalog/provider data using its own trusted
distribution helpers. It does not execute target helpers, repository commands,
scanners, credentials, or Git hooks. It reports all 33 checks, selection, provider,
recommended placement, prerequisites and existing evidence observations. Missing
configuration is a gap. Evidence-file contents are not authenticated execution.
An index can be planned before the first commit; absence of HEAD leaves
commit-bound evidence unavailable without discarding the staged tree identity.

Checkpoint IDs are `coding-finished`, `pre-commit`, `commit-creation`,
`post-commit`, `pre-push`, `pr`, `pre-merge`, `post-merge`, `release`, `deployment`
and `runtime`. These are context labels, not new Proof operations. The existing
[SDLC guide](sdlc-checkpoints.md) describes each decision and its boundaries.
Unsupported execution stays unavailable; the planner never infers an artifact,
environment, outgoing range or proposed message from HEAD. Merge checks,
approvals and review resolution must be inspected separately on the platform.

## Verify a separately bound record

```sh
python3 tooling/ai_toolkit checkpoint verify --receipt /path/to/receipt.json --json
python3 tooling/ai_toolkit checkpoint verify --receipt /path/to/receipt.json --expected-context /path/to/current-context.json --json
```

The version 1 `checkpoint-receipt` contract is defined and validated by
[`tooling/assurance.py`](../tooling/assurance.py). It records a checkpoint, exact
subject, timezone-qualified observation, invocation, dependency identities,
raw results and bounded file references (relative path, size, SHA-256).
Completed results require bound evidence; blocked/not-run results require a
reason. Optional handoff relationships require supporting bound evidence too.

An expected-context object names the current `subject` and dependency keys:
`index_tree`, `source_revision`, `comparison_base`, `pr_metadata_revision`,
`configuration_digest`, and `provider_digest`. Supply only context obtained by
the caller from the intended repository/platform. Uncompared dependencies are
unverified; changed ones invalidate applicability. Missing runtime expiry
leaves freshness unverified. An expired or future-dated observation is not a
current passing result. Metadata edits affect metadata-bound receipts, not
separate commit-only receipts. A merge relation does not rename PR results.

Validation rejects unsupported versions, duplicate JSON keys, unbound passes,
missing/modified files, path traversal and symlink escapes. Raw statuses are
`passed`, `failed`, `blocked` and `not_run`; verification preserves them.
Exit 0 means the reported checks passed with applicable supplied context, exit 1
means unresolved outcomes/context, and exit 2 means invalid/unavailable input.
None of these results authorizes an operation or satisfies a hosted merge gate.

Optional skill references record `name`, `origin` (`toolkit`, `local`, `external`
or `human`), optional revision/content hash and optional bound execution evidence.
Unversioned local skills remain usable. References are reported attribution,
not proof of invocation or an authenticated provider result.

## Packages and later lifecycle events

A version 1 `package-manifest` is immutable content metadata: HTTPS source
repository, commit/tree identities, build tool/version, configuration path/hash,
and an exact regular-file inventory with relative paths, sizes, hashes and
0644/0755 modes. Keep the manifest outside the payload directory it inventories.
The portable verifier checks membership and every file; it never executes the
payload or downloads dependencies:

```sh
python3 tooling/assurance.py package-verify --root /path/to/package/payload --manifest /path/to/package/package-manifest.json
```

`package_digest` is SHA-256 of canonical manifest JSON. Publication, upload,
deployment and live observation use subsequent checkpoint receipts referencing
the package and original evidence. Do not rewrite the content manifest to change
a temporary draft/authorization state. A supported relation is a recorded claim
with bound supporting bytes; independent platform verification is still needed.

Hash equality establishes integrity, not authenticated build provenance or the
truth of supplied results. Existing trusted GitHub collection and lifecycle
signature contracts retain their authority; a new receipt cannot self-assign it.
Cancelled/incomplete runs do not become completed results. Missing artifacts or
reports remain missing. See [producer authority](proof/producer-contract.md).

All checks optional, Core advisory, lifecycle/polyglot manual. No hooks,
credentials, workflow triggers, deployment or enforcement are installed by these
commands. Production deployment and release publication require separate approval.
