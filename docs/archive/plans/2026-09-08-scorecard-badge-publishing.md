# Scorecard Badge Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish both an accurate native workflow badge and an optional static badge that reports the latest accepted PR Guardrails score.

**Architecture:** Keep `Guardrail Scorecard` read-only. A separate default-branch `workflow_run` publisher downloads the exact completed scorecard artifact, validates it with repository-owned Python, renders a static report and SVG, and deploys that bounded output to GitHub Pages. The installer treats badge publishing as an explicit optional feature with symmetric install, refresh, and removal behavior.

**Tech Stack:** Python 3 standard library, GitHub Actions, GitHub Pages, SVG, HTML, JSON, `unittest`

**Spec:** `docs/superpowers/specs/2026-09-08-scorecard-badge-publishing-design.md`

## Global Constraints

- The existing scorecard workflow remains read-only.
- Badge publishing is optional and requires no PAT, Gist, repository secret, or `contents: write` permission.
- The publisher executes only default-branch code and never executes downloaded artifact content.
- Authenticated GitHub API requests never auto-follow artifact redirects. The signed archive URL is fetched separately over HTTPS without credentials.
- The publisher has no manual-dispatch entry point. `workflow_run` and a low-frequency `schedule` are the only triggers, so privileged workflow YAML always comes from the default branch and transient failures are retried.
- The read-only scorecard workflow adds a trusted `source.json` artifact binding containing the source run ID, run attempt, event, repository, PR number, head SHA, base branch, and base SHA from the event payload. Its artifact name includes both run ID and attempt.
- A source run is eligible only when that binding matches the run, scorecard subject, current pull-request API record, and repository default branch. Do not depend on `workflow_run.pull_requests` or apply one event type's `head_sha` semantics to another.
- The publisher proves the bound base SHA is an ancestor of the current default branch and verifies the bound head SHA equals the scorecard subject and current PR head SHA.
- Publishing is monotonic by source run creation time, run ID, and run attempt. Older or replayed attempts are validation-only and cannot replace newer published metadata; failure to read non-404 current metadata fails closed.
- Each publisher run paginates completed scorecard runs newest-first until it finds a fully valid candidate newer than the currently published tuple or reaches that tuple. With no prior publication, the first valid candidate wins. Shared concurrency may coalesce pending triggers, but a surviving run must recover the newest valid result rather than trust only its trigger; API or pagination failure fails closed.
- A valid `RED / block` artifact is publishable even when the source workflow conclusion is `failure`; canceled, skipped, or artifact-less failures are not.
- The standalone publisher requires `GUARDRAILS_SCORECARD_BADGE_PAGES_MODE=dedicated` and must not replace an existing repository Pages site.
- Exactly one bounded, non-symlink scorecard JSON, its paired Markdown report, and one trusted `source.json` binding are accepted. Published metadata includes the source run creation time for monotonic deployment checks.
- Pages receives only an allowlisted public projection: aggregate status/counts, run ID/attempt and timestamps, and a SHA-256 subject digest. Never copy controls, findings, evidence, reasons, provider details, check URLs, raw revisions, or source report text.
- The score badge is labeled as the latest PR scorecard, not default-branch state.
- Every external action is pinned to a full commit SHA.
- Current approved action pins are:
  - `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`
  - `actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d` (`v6.0.0`)
  - `actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9` (`v5.0.0`)
  - `actions/deploy-pages@368f82528645a54fb793d4d04e342629a3f51346` (`v5.0.1`)

---

### Task 1: Build the bounded scorecard badge renderer

**Files:**
- Create: `tooling/render_scorecard_badge.py`
- Create: `tooling/tests/test_render_scorecard_badge.py`
- Create after tests pass: `.guardrails/render_scorecard_badge.py`

**Interfaces:**
- Consumes: `inspect_scorecard(source_dir: Path) -> dict[str, object]` and `render_badge(source_dir: Path, output_dir: Path, repository: str, run_id: int, run_attempt: int, run_url: str, source_run_created_at: str, expected_revision: str) -> dict[str, object]`
- Produces: `guardrails-badge.svg`, `scorecard.json`, `scorecard.md`, and `index.html` under `output_dir`
- CLI inspection: `python3 .guardrails/render_scorecard_badge.py --source-dir PATH --inspect-output PATH`
- CLI rendering: `python3 .guardrails/render_scorecard_badge.py --source-dir PATH --output-dir PATH --repository OWNER/REPO --run-id INTEGER --run-attempt INTEGER --run-url HTTPS_URL --source-run-created-at RFC3339 --expected-revision 40_HEX_SHA`

- [ ] **Step 1: Write failing happy-path renderer tests**

Create a minimal valid GREEN scorecard fixture in a temporary source directory with one `scorecard-20260908-120000Z.json` and paired Markdown file. Assert that returned metadata and all four output files contain the intended public fields: `GREEN`, `14/14`, repository, source run/attempt, timestamps, and the SHA-256 revision digest. Assert the raw revision and all fixture controls, findings, evidence, reasons, provider values, check URLs, and source Markdown text are absent from every published file.

```python
metadata = MODULE.render_badge(
    source,
    output,
    "owner/repo",
    12345,
    2,
    "https://github.com/owner/repo/actions/runs/12345/attempts/2",
    "2026-09-08T12:00:00Z",
    "a" * 40,
)
self.assertEqual(metadata["message"], "GREEN 14/14")
self.assertIn("GREEN 14/14", (output / "guardrails-badge.svg").read_text())
self.assertEqual(json.loads((output / "scorecard.json").read_text())["source_run_id"], 12345)
self.assertEqual(json.loads((output / "scorecard.json").read_text())["source_run_attempt"], 2)
self.assertEqual(json.loads((output / "scorecard.json").read_text())["source_run_created_at"], "2026-09-08T12:00:00Z")
```

- [ ] **Step 2: Write failing color and validation tests**

Cover ORANGE and RED rendering, invalid or inconsistent version/operation/status/decision/count combinations, booleans masquerading as integers, passed counts greater than totals, zero active controls, invalid run attempts, mismatched revision, invalid RFC 3339 source timestamps, non-HTTPS or cross-repository run-attempt URL, missing/duplicate JSON, missing paired Markdown, files over 64 KiB, aggregate input over 1 MiB, nested files, and symlinks. Reject examples such as GREEN with a miss, ORANGE with all controls passing, RED with no enforced miss, RED/allow, and GREEN/block. Assert every invalid case raises `ValueError` and leaves no published output. Assert inspection validates the same bounded source and writes only trusted normalized metadata to its requested output path. Test Pages URL derivation for both `owner/repo` and the root-site repository `owner/owner.github.io`.

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```sh
python3 -m unittest tooling.tests.test_render_scorecard_badge
```

Expected: import or missing-interface failures because the renderer does not exist.

- [ ] **Step 4: Implement strict input validation and rendering**

Implement only with the standard library. Require the scorecard document to contain:

```python
VALID_STATUSES = {"GREEN": "#2da44e", "ORANGE": "#bf8700", "RED": "#cf222e"}
VALID_DECISIONS = {"allow", "block"}
MAX_MEMBER_BYTES = 64_000
MAX_SOURCE_BYTES = 1_000_000
```

Validate `version == 2`, `operation == "change"`, `subject.type == "git-commit"`, `subject.revision == expected_revision`, exact 40-character lowercase hexadecimal revisions, integer nonnegative `passed`/`total` values with `passed <= total`, and `enforced.total + advisory.total > 0`. Require GREEN exactly when every active control passed, ORANGE exactly when every enforced control passed and at least one advisory control missed, and RED exactly when at least one enforced control missed. Require `decision == "allow"` for GREEN/ORANGE and `decision == "block"` for RED. Derive the badge count from both modes and publish only an allowlisted summary plus `sha256(expected_revision)`; do not copy source objects or Markdown. Escape all SVG and HTML text with `html.escape`. Write into a temporary sibling directory and replace `output_dir` only after every file has been rendered successfully.

- [ ] **Step 5: Add the CLI and prove invalid invocations fail closed**

Use `argparse`; validate `run_id > 0`, `run_attempt > 0`, repository format `owner/name`, an RFC 3339 source run creation time, and an exact GitHub Actions run-attempt URL for that repository, run ID, and attempt. Derive the Pages base URL, special-casing a repository named `OWNER.github.io` to use the root site. Inspection and rendering are mutually exclusive modes. Inspection writes normalized status, decision, counts, and subject revision as JSON to `--inspect-output`; rendering prints a one-line `Published badge input: STATUS passed/total` message on success. Print `ERROR ...` to stderr with exit code `2` on validation failure.

- [ ] **Step 6: Run focused tests and synchronize the installed source**

Run:

```sh
python3 -m unittest tooling.tests.test_render_scorecard_badge
```

Expected: all renderer tests pass. Copy the exact canonical bytes to `.guardrails/render_scorecard_badge.py` and assert byte equality in the distribution tests added in Task 2.

- [ ] **Step 7: Commit the renderer**

```sh
git add tooling/render_scorecard_badge.py tooling/tests/test_render_scorecard_badge.py .guardrails/render_scorecard_badge.py
git commit -m "feat(badge): render validated scorecard status"
```

### Task 2: Add optional installer lifecycle support

**Files:**
- Modify: `tooling/install.py`
- Modify: `tooling/tests/test_install.py`
- Modify: `tooling/tests/test_action_distribution.py`

**Interfaces:**
- Extends: `install(..., scorecard_badge: bool = False, remove_scorecard_badge: bool = False) -> list[InstallItem]`
- Adds CLI: `--scorecard-badge` and `--remove-scorecard-badge`
- Installs: `.guardrails/render_scorecard_badge.py`, `.guardrails/reconcile_scorecard_badge.py`, and `.github/workflows/guardrails-scorecard-badge.yml`

- [ ] **Step 1: Write failing default and opt-in installation tests**

Assert a default install contains none of the three badge-publishing files. Assert `scorecard_badge=True` installs both exact canonical runtime files and the workflow while preserving the existing Core/GitHub workflow sets. For a repository with Guardrails already installed, require refresh mode to add the optional set; prove `refresh_existing=True, scorecard_badge=True` adds only the three badge-owned files and rejects symlinks or collisions with unowned destinations.

- [ ] **Step 2: Write failing refresh and removal tests**

Assert refresh detects an existing installer-owned badge workflow and refreshes all three files without requiring the option again. Assert `remove_scorecard_badge=True` removes only the three installer-owned files, appears as `kind == "remove"` in dry-run output, rejects simultaneous `scorecard_badge=True`, and refuses to remove an unmarked consumer workflow or symlink.

- [ ] **Step 3: Run installer tests and verify failure**

Run:

```sh
python3 -m unittest tooling.tests.test_install tooling.tests.test_action_distribution
```

Expected: failures for missing arguments, workflow map, runtime source, and removal behavior.

- [ ] **Step 4: Implement the optional install set**

Add:

```python
BADGE_WORKFLOWS = {
    "guardrails-scorecard-badge.yml": ROOT / "workflows" / "guardrails-scorecard-badge.yml",
}
BADGE_RUNTIME = InstallItem(
    ROOT / "tooling" / "render_scorecard_badge.py",
    target / ".guardrails/render_scorecard_badge.py",
)
```

Add a matching runtime item for `tooling/reconcile_scorecard_badge.py` at
`.guardrails/reconcile_scorecard_badge.py`.

Include both only for explicit opt-in or refresh detection. A clean installation accepts `--scorecard-badge`; an existing installation requires `--refresh-existing --scorecard-badge`. Keep `--no-actions --scorecard-badge` invalid because the feature requires an Actions publisher.

- [ ] **Step 5: Implement fail-safe removal**

Represent removals as exact `InstallItem` destinations with `kind="remove"`. Before changing state, reject symlinks and require the workflow to begin with `INSTALLER_MARKER`; require each runtime's exact bytes or a repository-owned marker header. Apply removal with `Path.unlink()` only to those exact files and prune no directories. Print `- remove:` for removal plan entries.

- [ ] **Step 6: Run installer and distribution tests**

Run:

```sh
python3 -m unittest tooling.tests.test_install tooling.tests.test_action_distribution
```

Expected: all tests pass and default consumers remain unchanged.

- [ ] **Step 7: Commit installer support**

```sh
git add tooling/install.py tooling/tests/test_install.py tooling/tests/test_action_distribution.py
git commit -m "feat(installer): manage scorecard badge publishing"
```

### Task 3: Add the trusted Pages publisher workflow

**Files:**
- Create: `workflows/guardrails-scorecard-badge.yml`
- Create after contract tests pass: `.github/workflows/guardrails-scorecard-badge.yml`
- Create: `tooling/reconcile_scorecard_badge.py`
- Create after tests pass: `.guardrails/reconcile_scorecard_badge.py`
- Create: `tooling/tests/test_scorecard_badge_workflow.py`
- Create: `tooling/tests/test_reconcile_scorecard_badge.py`
- Modify: `workflows/guardrails-scorecard.yml`
- Modify: `.github/workflows/guardrails-scorecard.yml`
- Modify: `tooling/tests/test_repository_commands.py`

**Interfaces:**
- Trigger: `workflow_run` for `Guardrail Scorecard` completion plus scheduled default-branch reconciliation; no manual dispatch
- Feature flag: repository variable `GUARDRAILS_SCORECARD_BADGE_ENABLED == 'true'`
- Pages ownership acknowledgement: repository variable `GUARDRAILS_SCORECARD_BADGE_PAGES_MODE == 'dedicated'`
- Deploys: renderer output through the `github-pages` environment

- [ ] **Step 1: Write failing workflow contract tests**

Parse both canonical and self-installed workflow text. Require:

```yaml
on:
  workflow_run:
    workflows: [Guardrail Scorecard]
    types: [completed]
  schedule:
    - cron: "17 */6 * * *"
```

Assert only `actions: read`, `contents: read`, `pull-requests: read`, `pages: write`, and `id-token: write` permissions; `concurrency.group: guardrails-scorecard-pages`; `cancel-in-progress: false`; the `github-pages` environment; the exact action pins; no `workflow_dispatch`; a low-frequency schedule; no checkout of a PR repository/ref; `fetch-depth: 0` on the default-branch checkout; and invocation of `.guardrails/reconcile_scorecard_badge.py` from that checkout. Prove scheduled runs use the same feature gates and reconciliation path and can recover after a transient prior failure.

Require both feature variables before deployment. Document and test that this
standalone workflow owns the repository's complete Pages deployment and is not
safe to enable alongside an existing Pages site.

Require the trusted source binding, pull-request API lookup, default-branch
ancestry check, normalized inspection output, newest-first paginated reconciliation,
and monotonic comparison with the currently published `scorecard.json`. Assert
stale candidates cannot reach any Pages configuration, upload, or deployment
step. Assert a surviving run selects the second-newest valid candidate when the
newest completed run is missing, expired, malformed, or otherwise invalid.
Assert reconciliation crosses more than 20 rejected runs and stops only after
selecting a newer valid candidate or reaching the published tuple.
Assert the authenticated artifact request cannot auto-follow redirects and the
second HTTPS archive request contains no authorization header.

- [ ] **Step 2: Write failing source-run validation assertions**

Require the workflow to reject source runs unless all are true:

```text
repository.full_name == github.repository
name == Guardrail Scorecard
path == .github/workflows/guardrails-scorecard.yml
or path == .github/workflows/guardrails-scorecard.yml@<default-branch>
or path == .github/workflows/guardrails-scorecard.yml@refs/heads/<default-branch>
conclusion in {success, failure}
event in {pull_request_target, pull_request_review}
source.json run ID, run attempt, repository, and event equal the source run
artifact name == guardrail-scorecard-<run-id>-<run-attempt>
source.json PR number resolves to a PR in this repository
source.json and the current PR identify the repository default branch as base
source.json base SHA is exactly 40 hexadecimal characters and is an ancestor of the current default branch
source.json head SHA equals both the current PR head SHA and validated scorecard subject revision
```

Reject every other workflow-path suffix, including attacker-controlled refs.
The workflow must not expose manual dispatch because GitHub permits dispatching
a workflow definition from a non-default ref.

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```sh
python3 -m unittest tooling.tests.test_scorecard_badge_workflow tooling.tests.test_reconcile_scorecard_badge
```

Expected: failure because the publisher workflow does not exist.

- [ ] **Step 4: Implement the workflow**

First update the canonical and self-installed scorecard workflows to write `source.json` from `GITHUB_EVENT_PATH` before the scorecard rendering step. Use repository-owned Python, not shell interpolation, to require a PR payload and record only normalized run ID, run attempt, event, repository, PR number, head SHA, base repository, base branch, and base SHA. Name the artifact `guardrail-scorecard-<run-id>-<run-attempt>`. The scorecard workflow permissions remain unchanged and read-only. Contract-test ordering and the `RED / block` path so a nonzero renderer exit cannot skip the binding; cover reruns whose attempts have different conclusions and artifacts.

Implement the reconciliation helper with the Python standard library. Fetch the current published `scorecard.json` first, then paginate completed runs for `.github/workflows/guardrails-scorecard.yml` newest-first. Filter repository, workflow name/path, event, conclusion, and run attempt and inspect each run's exact non-expired `guardrail-scorecard-<run-id>-<run-attempt>` artifact. Continue across pages and rejected candidates until selecting the first fully valid candidate newer than the published tuple or reaching that tuple. With no prior publication, stop at the first valid candidate. Fail closed on API, pagination, or authentication errors. For artifact archives, disable automatic redirects on the authenticated GitHub API request, require an HTTPS redirect target, and stream a second request with no credentials, matching the established `tooling/github_evidence.py` pattern. Enforce a 2 MiB compressed limit, reject unsafe ZIP paths, links, duplicate members, oversized members, or aggregate expansion over 1 MiB, and extract only the expected scorecard pair and `source.json` into a fresh directory. Add regression tests that distinguish retained artifacts from different attempts and record both download requests to prove only the GitHub API request carries authorization.

Invoke the renderer's inspection mode to obtain a normalized subject revision, validate `source.json` against the source run and attempt, then query the exact pull request with `pull-requests: read`. Check out the default branch with `fetch-depth: 0`, prove the bound base SHA is an ancestor of its complete history, and validate the binding against the current PR record. Cover the case where the default branch advanced after the scorecard event. Invoke rendering with the selected run's repository, run ID, run attempt, exact attempt URL, creation time, and validated PR head SHA. A `failure` conclusion is accepted only when the downloaded artifact validates as a `RED / block` scorecard; a `success` conclusion must contain an `allow` scorecard. Reject an invalid candidate and continue to the next candidate; fail closed if API state cannot be authenticated or no valid candidate exists.

Before configuring or uploading Pages, fetch the current published `scorecard.json`. HTTP 404 means no prior publication; every other fetch or validation failure is non-passing. Compare `(source_run_created_at, source_run_id, source_run_attempt)` tuples. When the candidate is older, report validation success but skip every Pages action. Equal tuples may idempotently republish; newer tuples may deploy. Write normalized `publish`, source-run, source-attempt, Pages base URL, and output-directory values to `GITHUB_OUTPUT`; the workflow gates every Pages action on `publish == 'true'`. Append a job summary containing the derived Pages URL, exact source attempt URL, rejected newer candidates, and whether the selected candidate was deployed or stale.

Do not use source-controlled shell from the artifact, `pull_request` checkout values, `contents: write`, or any secret other than the automatic `GITHUB_TOKEN` consumed by official actions.

- [ ] **Step 5: Synchronize canonical and self-installed workflows**

Copy the exact canonical workflow bytes to `.github/workflows/guardrails-scorecard-badge.yml`. Add byte-equality assertions so future installer refreshes cannot diverge from the self-hosting repository.

- [ ] **Step 6: Run workflow and repository contract tests**

Run:

```sh
python3 -m unittest tooling.tests.test_scorecard_badge_workflow tooling.tests.test_reconcile_scorecard_badge tooling.tests.test_action_distribution tooling.tests.test_repository_commands
```

Expected: all tests pass and YAML validation accepts both copies.

- [ ] **Step 7: Commit the publisher**

```sh
git add workflows/guardrails-scorecard.yml .github/workflows/guardrails-scorecard.yml workflows/guardrails-scorecard-badge.yml .github/workflows/guardrails-scorecard-badge.yml tooling/reconcile_scorecard_badge.py .guardrails/reconcile_scorecard_badge.py tooling/tests/test_scorecard_badge_workflow.py tooling/tests/test_reconcile_scorecard_badge.py tooling/tests/test_repository_commands.py
git commit -m "feat(actions): publish latest guardrail score badge"
```

### Task 4: Document both badge contracts and installation

**Files:**
- Modify: `README.md`
- Modify: `docs/quickstart.md`
- Modify: `docs/guardrails.md`
- Modify: `docs/architecture.md`
- Modify: `docs/guardrails-implementation.md`
- Modify: `docs/control-setup.md`
- Modify: `workflows/README.md`
- Modify: `examples/python-demo/README.md`

**Interfaces:**
- Native badge URL: `https://github.com/OWNER/REPOSITORY/actions/workflows/guardrails-scorecard.yml/badge.svg?event=pull_request_target`
- Score badge URL: `https://OWNER.github.io/REPOSITORY/guardrails-badge.svg`
- Report URL: `https://OWNER.github.io/REPOSITORY/`
- Root-site exception: when `REPOSITORY == OWNER.github.io`, use `https://OWNER.github.io/guardrails-badge.svg` and `https://OWNER.github.io/`

- [ ] **Step 1: Fix the native workflow badge**

Replace `?branch=main` in the README badge source with `?event=pull_request_target` and call it `Scorecard Workflow`. Explain that the event filter selects the core PR scorecard execution explicitly and avoids default-branch badge fallback behavior. Test the exact endpoint and require an SVG response that does not contain `no status`.

- [ ] **Step 2: Add concise installation and removal commands**

Document:

```sh
python3 tooling/install.py --target /path/to/repo --scorecard-badge --dry-run
python3 tooling/install.py --target /path/to/repo --scorecard-badge
python3 tooling/install.py --target /path/to/existing-repo --refresh-existing --scorecard-badge --dry-run
python3 tooling/install.py --target /path/to/existing-repo --refresh-existing --scorecard-badge
python3 tooling/install.py --target /path/to/existing-repo --refresh-existing --remove-scorecard-badge --dry-run
python3 tooling/install.py --target /path/to/existing-repo --refresh-existing --remove-scorecard-badge
```

State that GitHub Pages must use GitHub Actions as its source and that both
`GUARDRAILS_SCORECARD_BADGE_ENABLED=true` and
`GUARDRAILS_SCORECARD_BADGE_PAGES_MODE=dedicated` activate publication. Warn
that the standalone workflow owns the complete Pages deployment; repositories
with an existing Pages site must integrate the renderer output into that site's
workflow instead.

- [ ] **Step 3: Explain semantics and trust boundaries consistently**

Every relevant document must distinguish:

```text
Scorecard Workflow = GitHub workflow execution conclusion
Latest PR Scorecard = validated Guardrails readiness and passed/active count
```

State that a successful workflow may still contain an advisory ORANGE score and the latest PR badge does not attest current `main`. Explain the public projection and disclosure boundary: aggregate status/counts, source run metadata, and a revision digest are published; controls, findings, evidence, reasons, provider data, check URLs, raw revisions, and source Markdown remain only in the Actions artifact.

- [ ] **Step 4: Update diagrams and workflow inventory**

Add the publisher as an optional post-scorecard path, not a provider or control. Keep it out of required status-check lists and explain that Pages publication never influences `allow`/`block`.

- [ ] **Step 5: Run documentation and link validation**

Run:

```sh
python3 tooling/validators/validate_documentation.py
python3 tooling/validators/validate_repository.py
tooling/lint.sh
git diff --check
```

Expected: all validation passes with no broken internal links or stale badge guidance.

- [ ] **Step 6: Commit documentation**

```sh
git add README.md docs workflows/README.md examples/python-demo/README.md
git commit -m "docs(badges): explain workflow and score signals"
```

### Task 5: Verify, merge, activate Pages, and prove publication

**Files:**
- Modify after successful Pages deployment: `README.md`

**Interfaces:**
- Repository variable: `GUARDRAILS_SCORECARD_BADGE_ENABLED=true`
- Pages mode variable: `GUARDRAILS_SCORECARD_BADGE_PAGES_MODE=dedicated`
- Pages build type: `workflow`
- Proof: published SVG and scorecard JSON bind the same source run and revision

- [ ] **Step 1: Run complete local validation**

Run:

```sh
tooling/build.sh
tooling/test.sh
GUARDRAILS_COVERAGE_BASE_REF=origin/main tooling/changed_code_coverage.sh
python3 examples/python-demo/tools/validate_demo.py --documentation
python3 tooling/validate-skills.py
python3 tooling/validators/validate_repository.py
python3 tooling/validators/validate_documentation.py
python3 tooling/validators/validate_no_migrations.py
tooling/lint.sh
git diff --check
```

Expected: all commands exit zero and changed Python coverage is at least 90%.

- [ ] **Step 2: Open and review the implementation PR**

Push the implementation branch, open a PR, wait for every selected producer and the scorecard, inspect the timestamped scorecard artifact, run Codex review on the exact head, resolve valid findings, and repeat validation after changes.

- [ ] **Step 3: Merge the implementation PR**

Merge only with no blocking check failures or unresolved review threads. Delete the merged feature branch and update local `main`.

- [ ] **Step 4: Configure this repository's Pages publisher**

Set the repository variable and Pages build type:

```sh
gh variable set GUARDRAILS_SCORECARD_BADGE_ENABLED --body true
gh variable set GUARDRAILS_SCORECARD_BADGE_PAGES_MODE --body dedicated
gh api --method POST repos/ravisingh11/engineering-standards/pages -f build_type=workflow
```

If Pages already exists, use the corresponding update endpoint with
`build_type=workflow`. Verify the API reports the expected Pages URL and build
type before triggering publication.

- [ ] **Step 5: Open a minimal proof PR**

Add the live score badge to `README.md` only after Pages is configured:

```markdown
[![Latest PR Scorecard](https://ravisingh11.github.io/engineering-standards/guardrails-badge.svg)](https://ravisingh11.github.io/engineering-standards/)
```

Push the proof branch and open a PR. Wait for its `Guardrail Scorecard`, then
wait for the publisher triggered by that exact run.

- [ ] **Step 6: Verify the deployed result end to end**

Fetch the deployed JSON and SVG without authentication. Assert that:

```text
status == source scorecard status
passed/total == source scorecard passed/total
subject revision digest == sha256(proof PR head SHA)
source_run_id == triggering Guardrail Scorecard run ID
source_run_attempt == triggering Guardrail Scorecard run attempt
SVG title and visible message match the JSON
```

Verify the native workflow badge no longer returns `no status` and the score
badge returns HTTP 200 with the expected GREEN/ORANGE/RED message.

- [ ] **Step 7: Merge the proof PR and perform the final audit**

Require a clean exact-head review and scorecard, merge the proof PR, remove
merged branches, confirm `main == origin/main`, and verify that only explicitly
excluded Dependabot PRs remain open.
