# SDLC checkpoints: coding through merge

A guardrail supports a decision: **What action are we considering, what has
been checked, and does that evidence justify proceeding?** Git events provide
opportunities to run checks. A checkpoint describes the decision being made.
This guide serves both human contributors and agents.

All 33 catalog checks remain available to discover and optional to adopt.
Core defaults remain advisory. A successful early check supports its recorded
decision; merge, publication and deployment each retain their own evidence and
authorization boundaries. Lifecycle and polyglot execution remain manual.

## Current support and recommendations

- **Supported now:** Proof evaluates `change` and `release`, with subjects
  `git-commit`, `pull-request`, `artifact` and `environment`. See the
  [public model](proof/README.md#public-model) and
  [producer contract](proof/producer-contract.md). The checkpoint names below
  are guidance, not new operation names, subject types or CLI flags.
- **Supported now:** optional local hooks invoke Semgrep against the checkout
  and Gitleaks against Git history. Both use `pass_filenames: false`. Their
  installation and exact scan scope do not prove that the proposed staged
  snapshot passed. See [local hook setup](quickstart.md#1-preview-and-install-the-starter-set)
  and the [installer implementation](../tooling/install.py).
- **Supported now:** standard PR templates generally run on opened, updated
  (`synchronize`) and reopened PRs; metadata also responds to edits. Source
  workflows explicitly check out the PR head. These templates do not
  automatically validate a combined merge candidate or run after every merge.
  A consuming repository owns any additional main-branch or merge-queue CI.
- **Recommended placement:** the checkpoint and catalog tables describe when
  a capability is useful. They do not install it, change policy selection,
  schedule execution or establish passing evidence.
- **Future capabilities:** exact staged-snapshot evaluation, commit-message
  validation and first-class checkpoint scheduling would need separately
  designed producers/contracts. Commit-message conventions are repository
  guidance today, not a new built-in check. Do not fabricate `git-commit`
  evidence for an uncommitted index or working tree.

Execution, evaluation and enforcement are separate. A producer executes a
check; Proof evaluates matching authoritative evidence; a separately adopted
hook or platform rule can gate an action. Local hooks can be bypassed and do
not establish a centrally enforced boundary. An advisory result can inform a
human decision without becoming a required check. Even `allow` grants no
permission to commit, push, merge, publish or deploy.

A committed revision can still use the existing `change` evaluation after
merge; merging alone does not turn it into a `release` evaluation. Operation
and subject applicability continue to follow the current catalog and policy.

## Checkpoint decisions

The IDs C1–C8 below are navigation labels for this document. They are not
configuration keys. Select useful checks for the repository, changed scope
and decision; do not run every mapped check at every event.

### C1 — Coding finished

- **Decision and subject:** ready to prepare a commit? Review the current
  working diff, including untracked files, against requirements and repository
  ground truth. Working changes have no supported immutable Proof subject yet.
- **Checks and location:** human/agent review, test-gap analysis, documentation
  impact and selected focused checks on the workstation or isolated preview.
  A review procedure is distinct from a completed producer result.
- **Authority and next action:** advisory feedback supports preparing and
  staging the change, subject to user authorization. It does not certify the
  staged contents or satisfy a required CI check by default.
- **Invalidate:** edits, relevant untracked files, a changed comparison base,
  requirements, configuration or tool inputs require reassessing affected work.

### C2 — Pre-commit

- **Decision and subject:** ready to record exactly the staged contents? The
  proposed input is the index, including partially staged files; it can differ
  from both the working tree and the existing HEAD commit.
- **Checks and location:** fast lint/format, staged-secret and file/config
  checks are recommended for a deliberately adopted local hook or manual step.
  Exact staged-snapshot coverage requires a producer that actually inspects it;
  the existing hook bundle does not supply this guarantee.
- **Authority and next action:** a configured local hook can reject the commit
  attempt, but remains bypassable. Passing supports that attempt only, not
  permission to push or merge. Checks must not silently stage or rewrite files.
- **Invalidate:** any index change or relevant checker/configuration change.
  Re-establish the checked index identity before relying on the result.

### C3 — Commit creation

- **Decision and subject:** is the proposed commit record acceptable? The
  input is the commit message and required change references, when adopted.
- **Checks and location:** repository-owned message conventions can be checked
  by an optional `commit-msg` hook. The toolkit currently documents conventions
  but supplies no built-in commit-message producer or corresponding catalog ID.
- **Authority and next action:** an adopted hook may reject creation; success
  supports creating the commit. This is separate from PR title/body validation
  and does not establish source correctness or signing validity.
- **Invalidate:** a changed proposed message, references or conventions.

### C4 — Post-commit

- **Decision and subject:** what is known about the newly created commit?
  Record its exact SHA and the original subject identities of existing results.
- **Checks and location:** selected build/tests/static checks can provide
  slower local feedback when authorized. Hosted CI requires the revision to
  be available remotely, normally after a push; a local commit alone cannot
  trigger a remote workflow.
- **Authority and next action:** feedback informs the next push or PR decision.
  A post-commit hook cannot prevent the commit that has already happened;
  [Git documents it as a notification hook](https://git-scm.com/docs/githooks).
  It must not silently push, amend, revert or rewrite history.
- **Invalidate:** amend/rebase creates another commit identity; changes to
  relevant inputs, tools, policy or provider authority require reassessment.

### C5 — Pre-push

- **Decision and subject:** ready to share the outgoing commits? Identify the
  remote/ref, outgoing revision range and comparison base explicitly.
- **Checks and location:** range-aware secret detection and selected useful
  early checks may run in an optional local `pre-push` hook or manual step.
  This is recommended placement, not an installed toolkit push hook. A result
  for the tip alone does not prove every outgoing commit was scanned.
- **Authority and next action:** an adopted hook may reject the local push;
  server-side protection is a separate boundary. Passing supports sharing that
  range and does not establish PR review or integration readiness.
- **Invalidate:** changed outgoing commits, destination ref/range, comparison
  base, configuration or scanner inputs.

### C6 — PR created or updated

- **Decision and subject:** is the proposed change ready for review? Source
  evidence identifies the head commit; diff-based checks also need the actual
  base/range. Mutable metadata uses its own `pull-request` subject snapshot.
- **Checks and location:** adopted CI build/tests, coverage, security,
  dependency, migration, repository/documentation checks and review. Functional
  QA needs an authorized branch-owned running target and recorded source
  identity; a live production deployment cannot stand in for PR QA.
- **Authority and next action:** CI/review supports reviewing the proposal.
  Only separately configured platform requirements gate merging. AI reviews
  and functional QA remain advisory-only under the current catalog contract.
- **Invalidate:** head changes, changed baselines for diff-based checks, PR
  metadata edits, dismissed approvals, or relevant producer/policy changes.
  Reassess affected evidence, rather than assuming every result remains valid.

### C7 — Pre-merge

- **Decision and subject:** ready to integrate into the current target? Name
  the tested head and base, and the integration candidate when one is tested.
- **Checks and location:** inspect current required checks, approvals and
  resolved review discussions on the platform. Where adopted, integration CI
  can evaluate the combined candidate. The standard head-pinned templates do
  not automatically provide that evidence. GitHub merge queues require
  [CI support for merge groups](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue).
- **Authority and next action:** repository protection and separately granted
  human/agent authorization govern the merge. A Proof `allow` result alone
  does not prove mergeability or authorize a bypass. The next boundary is
  verification of the actual resulting main revision.
- **Invalidate:** head or target-base changes, integration candidate changes,
  stale/dismissed approvals, unresolved findings or changed gate policy.

### C8 — Post-merge

- **Decision and subject:** is the resulting main revision healthy? Use the
  actual merge, squash or fast-forward result, not an assumed PR-head identity.
- **Checks and location:** repository-adopted main-branch CI or authorized
  verification checks the merged revision. Reassess integration-sensitive
  build/tests and relevant configuration, migration, documentation or security
  evidence. Main-branch execution is not enabled by this guide.
- **Authority and next action:** a failing result informs the repository's
  response procedure; it does not automatically authorize a revert or deploy.
  A healthy main revision can be handed to release preparation.
- **Invalidate:** a newer main commit or changed verification inputs. Preserve
  the original tested revision and any explicit comparison/reuse justification;
  do not relabel prior evidence as a run on the merged SHA.

## Placement of all 33 catalog checks

Each link opens the existing activation entry for purpose, prerequisites,
provider selection and evidence verification. Placements describe useful
applications of a capability, not new producer modes or enforcement defaults.
C1/C2/C5 suggestions require appropriate local scope; current commit-bound
results cannot be relabeled as working-tree, index or range evidence. C4/C8
execution requires an adopted runner. C7 review can inspect existing acceptable
evidence; it need not rerun every producer before every merge.

| Catalog check | Recommended checkpoint or handoff | Scope and limits |
| --- | --- | --- |
| [repository-validation](activation.md#repository-validation) | C1, C2; C6–C8 | Adapt early feedback to the actual files inspected; commit-bound CI validates installed contracts. |
| [documentation-validation](activation.md#documentation-validation) | C1; C6–C8 | Use declared code-to-document mappings and a valid comparison baseline. |
| [repository-ground-truth](activation.md#repository-ground-truth) | C1; C6–C8 | Review architecture/engineering contracts and validate declared ground truth. |
| [change-scope](activation.md#change-scope) | C1, C5; C6–C7 | The inspector accepts explicit base/head refs; record the compared range and relate it to the actual PR when used for review. |
| [pr-metadata](activation.md#pr-metadata) | C6–C7 | Use the current mutable PR snapshot; this is not commit-message validation. |
| [format-and-lint](activation.md#format-and-lint) | C1, C2, C5; C6–C8 | Local subset and full CI scope must remain distinguishable. |
| [migration-validation](activation.md#migration-validation) | C1; C6–C8 | Assess applicable repository migration contracts and compatibility; retain the real command scope. |
| [build](activation.md#build) | C1, C4, C5; C6–C8 | Distinguish incremental/source builds from any later packaged artifact. |
| [unit-tests](activation.md#unit-tests) | C1, C4, C5; C6–C8 | Record focused subsets separately from the adopted full suite. |
| [functional-qa](activation.md#functional-qa) | C1; C6–C7 | Requires an authorized running change target and source identity; advisory-only. |
| [changed-code-coverage](activation.md#changed-code-coverage) | C6–C7 | Requires instrumented test evidence and the actual head/base comparison. |
| [custom-static-analysis](activation.md#custom-static-analysis) | C1, C2, C4, C5; C6–C8 | Document whether the rules inspected changed files, checkout or another scope. |
| [secret-detection](activation.md#secret-detection) | C1, C2, C5; C6–C8 | Staged content, outgoing history and committed-history scans are different scopes. |
| [deep-sast](activation.md#deep-sast) | C6–C7 | Use the accepted source revision, configured languages and authoritative producer. |
| [dependency-change-review](activation.md#dependency-change-review) | C1; C6–C7 | Early risk review informs the change; the built-in producer needs the actual PR comparison. |
| [platform-secret-protection](activation.md#platform-secret-protection) | C5 context; C6–C7 | Platform configuration/evidence is separate from a local secret scan or hook. |
| [dependency-remediation](activation.md#dependency-remediation) | C6–C7 | Configuration/remediation evidence does not establish that dependencies have no vulnerabilities. |
| [artifact-provenance](activation.md#artifact-provenance) | Later: release | Bind provenance evidence to the actual artifact and build identity. |
| [static-quality](activation.md#static-quality) | C1; C6–C7 | Early tool feedback and a revision-bound quality gate have different scope/authority. |
| [dependency-vulnerability](activation.md#dependency-vulnerability) | C1, C5; C6–C7 | Record resolved dependency scope, advisory inputs and scanner availability. |
| [license-compliance](activation.md#license-compliance) | C1; C6–C7 | Assess selected dependency licenses against repository policy. |
| [ai-engineering-review](activation.md#ai-engineering-review) | C1; C6–C7 | Record reviewed source/context; advisory-only. |
| [ai-qa-review](activation.md#ai-qa-review) | C1; C6–C7 | Review test assertions and gaps; not evidence that tests ran; advisory-only. |
| [ai-security-review](activation.md#ai-security-review) | C1; C6–C7 | Review trust boundaries and source; not a replacement scanner result; advisory-only. |
| [ai-repository-standards-review](activation.md#ai-repository-standards-review) | C1; C6–C7 | Review against repository-owned ground truth; advisory-only. |
| [runtime-soak](activation.md#runtime-soak) | Later: pre-release | Requires an identified running environment and observation interval. |
| [container-vulnerability](activation.md#container-vulnerability) | Later: release | Scan the actual identified container artifact. |
| [iac-misconfiguration](activation.md#iac-misconfiguration) | C1; C6–C8; later release | Source analysis covers IaC files; it does not prove deployed environment state. |
| [artifact-sbom](activation.md#artifact-sbom) | Later: release | Inventory the actual artifact; an SBOM alone does not establish absence of vulnerabilities. |
| [artifact-vulnerability](activation.md#artifact-vulnerability) | Later: release | Use the actual artifact identity and scanner/database context. |
| [deployment-policy](activation.md#deployment-policy) | Later: deployment | Evaluate the identified environment and deployment decision. |
| [dynamic-application-security](activation.md#dynamic-application-security) | Later: post-deployment | Requires an explicitly authorized running target and matching environment identity. |
| [runtime-assurance](activation.md#runtime-assurance) | Later: runtime | Requires deployment/environment identity and current runtime observations. |

## Evidence and decision record

For a checkpoint decision, retain the checkpoint/action, changed scope, tested
subject identity, actual comparison base/range where applicable, check command
and subset, producer/tool/configuration identity, original result, evidence link,
and the policy/runtime authority used to evaluate it. Include approvals and
any separately granted action authorization. This is a documentation checklist,
not a new wire format or a claim that every existing producer records every item.
If a required identity or input cannot be established, report that limitation.

Reuse is an explicit evidence decision, not a blanket optimization based only
on matching filenames or a SHA. Source identity, scope, comparison base, tool
inputs, provider authority and relevant freshness rules must still apply.
Current Proof evidence matches its declared subject exactly; these recommendations
do not add cross-revision reuse to the evaluator. See the
[evidence subject rules](proof/README.md#evidence-belongs-to-one-subject).

## Worked examples

### Partial staging

A contributor stages a safe edit, then makes a second unstaged edit in the same
file. A working-directory lint pass checked the combined file, not necessarily
the index that will be committed. Record the pass with its actual scope. Exact
staged-content assurance needs an index-aware producer and stable snapshot;
otherwise leave that guarantee unverified. Do not automatically restage the file
or claim HEAD evidence for the proposed new commit.

### PR-body edit

Head H passes source tests. The PR body then changes without a source commit.
The metadata producer fingerprints repository, PR number, head, update time,
title and body; its previous snapshot no longer describes the current state.
Reassess metadata and affected review/approval rules. The original source-test
result still describes H under its original inputs; it is not automatically
invalidated by a prose-only edit or promoted to a new metadata pass.

### New commit or comparison base

Head H1 passes tests against base B1. A push creates H2: preserve H1's result
and obtain acceptable evidence for H2. If the target base becomes B2 while H1
is unchanged, recompute affected diff-based checks such as changed coverage,
PR scope and dependency changes, and reconsider integration validity. A
source-only result may still describe H1; it does not establish success for
the changed comparison or combined integration candidate.

### Squash or merge

A PR head H passes CI; squash produces main commit M. Keep the run linked to H.
If comparing trees establishes equal source bytes, record that comparison and
its limits explicitly; equal trees do not mean equal commit identities or
identical history, parent-sensitive inputs or runtime behavior. Repository
policy decides whether that comparison supports the next decision. A result
claiming M requires evidence actually bound to M. Do not rewrite H's result,
assume a main-branch workflow exists, or treat merging as deployment evidence.

### Missing prerequisites or excluded execution

A selected scanner has no credential, or the user excludes local test execution.
Keep reported failures, `blocked` and `not_run` outcomes intact. Local execution
stays not run; usable hosted evidence remains scoped to its actual subject.
Stale/mismatched evidence cannot satisfy the requested subject. A successful
setup step, available tool or installed workflow never substitutes a result.
Report the missing prerequisite or next permitted action without installing
credentials, running producers or changing gates automatically.

### Selective adoption

A repository selects unit tests and lint as advisory and leaves deep SAST
unselected. An exact-subject passing unit-test result counts; missing selected
lint evidence remains unresolved. Unselected deep SAST is an adoption option,
not a failed requirement or an extra pass. Apply the existing selection,
operation, subject, authority and scoring rules unchanged. A checkpoint's
recommended list never activates another check or adds it to a score.

## Handoff after healthy main

Post-merge readiness can inform release preparation. A release still needs
its own artifact identity and applicable verification; deployment still needs
its own authorization, environment identity and live observations. The later
catalog entries above remain discoverable without being requirements for every
PR or healthy main revision. Their detailed checkpoint model is a later step.

This guide installs no hooks, adds no triggers, changes no schemas or scores,
and activates/enforces nothing. Existing installations, defaults and historical
evidence retain their contracts. For prerequisites use the [activation index](activation.md);
for operating existing checks use the [operating guide](proof/operating-guide.md).
