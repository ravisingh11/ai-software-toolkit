# Scorecard Badge Publishing Design

## Purpose

Expose two different signals without conflating them:

1. The native GitHub workflow badge shows whether the Guardrail Scorecard
   workflow completed successfully.
2. The Guardrails score badge shows the latest evaluated PR result, including
   its color and passed-control count.

The score badge is optional. Installing Guardrails must continue to work
without GitHub Pages or badge publishing.

## User experience

The project README may display both badges:

```text
Scorecard workflow: passing
Latest PR scorecard: GREEN 14/14
```

The workflow badge uses `event=pull_request_target` so it selects the core PR
scorecard executions explicitly instead of relying on GitHub's default-branch
fallback. The score badge must be labeled as the latest PR scorecard rather
than the state of the default branch.

Consumers enable score publishing explicitly during installation or refresh.
Documentation provides the GitHub Pages setting, repository variable, badge
URL, and removal path.

## Architecture

```text
Guardrail Scorecard workflow
        |
        | trusted JSON and Markdown artifact
        v
Scorecard Badge Publisher (workflow_run)
        |
        | reconcile newest valid bounded artifact; execute no artifact content
        v
Static Pages artifact
        |
        +-- guardrails-badge.svg
        +-- scorecard.json
        +-- scorecard.md
        +-- index.html
```

The existing scorecard workflow keeps read-only permissions and adds a trusted
`source.json` binding to its artifact. The binding records the source run ID,
run attempt, event, repository, pull-request number, head SHA, base branch, and
base SHA from the trusted event payload. The artifact name includes both run ID
and attempt so reruns cannot collide with retained evidence. A separate publisher runs
from the default branch after a completed `Guardrail Scorecard` workflow. Each
trigger is a reconciliation signal, not an instruction to publish that run.
After acquiring its concurrency group, the publisher pages through completed
scorecard runs newest-first until it finds a valid candidate newer than the
currently published tuple or reaches that tuple. It renders a minimal public
projection with repository-owned code and deploys only those generated files
to GitHub Pages.

Only scorecard runs bound to one eligible pull request whose base is the
repository default branch are eligible. GitHub may leave a
`workflow_run.pull_requests` collection empty for `pull_request_target`, and a
`pull_request_review` run may identify the candidate rather than the trusted
base in `head_sha`, so the publisher does not infer PR identity from either
field. It validates the artifact's trusted source binding against the source
run and current pull-request API record. It also proves that the bound base SHA
is an ancestor of the current default branch after fetching complete
default-branch history. The publisher has no manual-dispatch trigger, so its
privileged workflow definition can execute only from the default branch through
`workflow_run`. A low-frequency scheduled reconciliation also runs from the
latest default-branch workflow definition so transient API or Pages failures
recover even when no later PR event occurs.

## Security boundaries

- The publisher never checks out or executes pull-request code.
- The publisher implementation always comes from the default branch.
- The publisher has no `workflow_dispatch` entry point; only completion of the
  named scorecard workflow or its default-branch schedule can trigger its
  privileged Pages deployment.
- The trusted default-branch checkout fetches complete history before testing
  whether the bound base SHA is an ancestor.
- The downloaded archive and selected scorecard member have strict size and
  path limits.
- Artifact download redirects are handled explicitly: the authenticated GitHub
  API request does not auto-follow, and the signed HTTPS archive URL is fetched
  in a second request without `Authorization` or other credentials.
- Exactly one scorecard JSON document for the triggering run is accepted.
- Exactly one trusted source binding is accepted. Its repository, run ID, run
  attempt, event, PR number, head SHA, base branch, and base SHA must agree with
  the source run, artifact name, scorecard subject, current PR record, and
  repository default branch.
- The bound base SHA must be reachable from the current default branch, proving
  that the producer came from trusted repository history for either supported
  PR event type.
- Status, decision, counts, and subject values are schema-validated before
  rendering.
- Scorecard version, change operation, status, decision, and enforced/advisory
  counts must be semantically consistent: GREEN means every active control
  passed, ORANGE means enforced controls passed with advisory misses, and RED
  means at least one enforced miss. Only RED blocks.
- SVG and HTML use only validated enumerations, integers, and escaped text.
- Pages output is an allowlisted projection, never a copy of the source JSON or
  Markdown. It contains aggregate status and counts, source run ID/attempt and
  timestamps, and a SHA-256 digest of the subject revision. It excludes raw
  revisions, controls, findings, evidence, reasons, provider details, and check
  URLs.
- The publisher receives `actions: read`, `contents: read`,
  `pull-requests: read`, `pages: write`, and `id-token: write`; the scorecard
  workflow keeps its current read permissions.
- A valid `RED / block` scorecard is published even though the source scorecard
  workflow reports failure. Canceled runs and failures without valid scorecard
  evidence are not published.
- The scorecard workflow writes `source.json` before rendering, so a renderer
  exit used to signal `RED / block` cannot skip the trusted binding.
- Publishing is serialized. GitHub may replace a pending run in a shared
  concurrency group, so every surviving publisher run paginates newest-first
  back to the currently published source tuple instead of assuming its trigger
  is the candidate. A newer invalid or artifact-less run is rejected and the
  next newest valid candidate remains eligible. With no prior publication, the
  first valid candidate is selected. API or pagination failure fails closed.
- Publication is monotonic. Before deployment, the publisher compares the
  source run creation time, run ID, and run attempt with the currently published metadata.
  An older source run is validated and reported as stale but cannot replace a
  newer badge. A transient failure reading existing metadata fails closed.

## Published result

The badge color follows the scorecard result:

| Scorecard | Badge color | Message |
| --- | --- | --- |
| `GREEN` | green | `GREEN <passed>/<total>` |
| `ORANGE` | orange | `ORANGE <passed>/<total>` |
| `RED` | red | `RED <passed>/<total>` |

The count uses all active controls: enforced total plus advisory total. A
zero-control or malformed scorecard is rejected rather than presented as a
successful badge.

The published report identifies its source repository, workflow run, subject
revision digest, operation, and generation time. The badge links to the
published report page; the workflow badge links to GitHub Actions. Repository
identity and aggregate scorecard metadata become visible wherever the Pages
site is visible; consumers that cannot accept that disclosure must not enable
the standalone publisher.

Project repositories publish under `https://OWNER.github.io/REPOSITORY/`.
Repositories named `OWNER.github.io` publish at the root
`https://OWNER.github.io/`; badge and report URLs use the derived base.

## Installation and configuration

The installer gains an explicit badge-publishing option. When selected, it
installs the publisher workflow and renderer alongside the normal runtime.
Refresh updates those files; cleanup removes files previously owned by that
option when it is disabled.

A clean install may select badge publishing directly. An existing Guardrails
installation adds or removes the optional files through explicit refresh mode,
which preserves the installer's existing collision and ownership checks.

Activation requires:

1. GitHub Pages configured with **GitHub Actions** as the build source.
2. The installed publisher workflow present on the default branch.
3. Repository Actions allowed to create Pages deployments.
4. The documented badge URLs added to the consumer README.
5. The repository variable `GUARDRAILS_SCORECARD_BADGE_ENABLED=true`.
6. The repository variable
   `GUARDRAILS_SCORECARD_BADGE_PAGES_MODE=dedicated`, acknowledging that this
   publisher owns the complete Pages deployment for the repository.

The standalone publisher must not be enabled for a repository that already
uses GitHub Pages for documentation or another site. GitHub Pages has one active
deployment per repository, so deploying only the badge output would replace the
existing site. Such repositories should render these files inside their
existing Pages build instead of installing the standalone publisher; that
integration remains repository-owned.

No personal access token, repository secret, Gist, or contents-write
permission is required.

## Failure behavior

- A scorecard workflow failure with a valid `RED / block` artifact publishes
  that red result. A failure without a valid scorecard artifact leaves the
  previously published badge intact and makes the publisher non-passing.
- Canceled or skipped source runs are rejected without deploying.
- Missing or invalid evidence fails the publisher without deploying.
- A scheduled default-branch reconciliation retries transient API, artifact,
  or Pages failures without allowing arbitrary-ref manual dispatch.
- A Pages configuration error fails only the optional publisher. It does not
  alter the original scorecard decision.
- Re-running the currently published scorecard may republish the same immutable
  subject. A reconciliation that encounters an older scorecard validates it
  without deployment when a newer source run has already been published.

## Documentation changes

Update the README, quickstart, Guardrails guide, implementation guide, workflow
catalog, control setup guide, and example documentation to explain:

- the difference between the workflow and score badges;
- why the native badge uses `event=pull_request_target`;
- what the latest PR score means;
- how to install, enable, verify, and remove badge publishing;
- the Pages permissions and trust boundary;
- how to construct badge URLs for a consuming repository.

## Verification

The implementation must include:

- renderer unit tests for green, orange, red, malformed, ambiguous, oversized,
  and unsafe input;
- workflow contract tests for trigger, permissions, immutable action pins,
  source-run binding, and no PR-code execution;
- installer and refresh/cleanup distribution tests;
- Markdown link and YAML validation;
- an end-to-end run in this repository that publishes a badge matching the
  exact scorecard artifact;
- a follow-up PR proving the native workflow badge and latest PR score badge
  both render.

## Acceptance criteria

- The native badge no longer displays `no status`.
- The published score badge matches the latest accepted PR scorecard.
- Badge publishing is opt-in for consumers and enabled for this repository.
- The scorecard workflow remains read-only.
- No additional credential is required.
- Existing installations remain compatible until the option is enabled.
