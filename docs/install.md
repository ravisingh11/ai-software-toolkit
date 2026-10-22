# Install with the `ai-toolkit` CLI

The `ai-toolkit` command is one front door for Proof, shared skills, and
QA bootstrap. It is a facade: `init`, `doctor`, `check`, `providers`, `skills`,
`qa`, and `update` dispatch to the existing installer, diagnostics, scanner,
configuration, and skill sources under `tooling/`. It adds discovery, the
`toolkit.toml` and `toolkit.lock.json` files, and unified reports. It does not
reimplement evaluation, and an installed repository never imports it at
evaluation time.

Three entry points use the same code: the CLI, the
[`toolkit-setup` skill](../skills/toolkit-setup/SKILL.md) for Codex and
Claude Code, and the [`AI Toolkit Setup` starter workflow](../workflows/README.md#starter-workflow)
for GitHub. Python 3.11+ is the only prerequisite.

## Get the CLI

Either run it from a source checkout:

```bash
python3 <toolkit-root>/tooling/ai_toolkit --version
```

or use the single-file archive built with `tooling/build_archive.py`:

```bash
python3 tooling/build_archive.py --output dist/ai-toolkit.pyz
python3 tooling/build_archive.py --verify dist/ai-toolkit.pyz
python3 dist/ai-toolkit.pyz --version
```

The archive bundles the source subset installation needs. On first run it
extracts that payload to `~/.cache/ai-toolkit/<checksum>/` (override with
`AI_TOOLKIT_CACHE`) and runs the CLI from there, so `init` copies real files
into your repository exactly as a checkout does. Always verify a downloaded
archive against its `.sha256` asset from the same pinned release; `update`
never fetches anything on its own.

## Fresh starter installation (v2.3.0)

On the v2.3.0 source line, fresh `init` defaults to `--install-set starter`
with `--components proof,skills` and the existing seven starter skills for the
selected clients. Published older releases retain their original behavior.

Starter installs these 11 workflows: scorecard, repository validation (including
documentation and ground truth), PR size, PR metadata, build, unit tests,
changed-code coverage, format/lint, migrations, Semgrep CE, and Gitleaks.
The existing Core policy still selects all 12 advisory checks. A missing scanner
or command remains unverified; lean installation does not waive coverage.

`--install-set full` explicitly installs the legacy Core workflow collection,
including Trivy and lifecycle templates. It does not select the GitHub profile
or Pages. The low-level `tooling/install.py` retains its full legacy default;
use the CLI for the fresh starter path.

Trivy and lifecycle templates are absent from starter. Adopt a particular workflow
explicitly by copying its template from `workflows/` into `.github/workflows/`,
reviewing its prerequisites, and selecting/configuring its provider separately.
See the [activation index](activation.md) and
[independent security guide](providers/independent-security.md). Lifecycle runs
remain manual. `--profile github` and the optional scorecard badge/Pages setup
are separate choices.

Existing configurations and locks without `install_set` keep full behavior.
Existing client directories alone do not establish a previous toolkit install.
A fresh merge records the canonical baseline for an existing customized skill,
so a later update preserves it as a conflict. There is no automatic migration or pruning, and changing an existing set with
`init` is refused. Updates preserve configurations, owned workflows, custom
files, and recorded skills. A manually adopted optional workflow in a starter
installation is left in place. Proof-only installations create no client skill
directories; Claude-only installs populate `.claude/skills/` only.

## Set up a repository

```bash
python3 ai-toolkit.pyz discover --target .        # read-only
python3 ai-toolkit.pyz init --target . --preview   # nothing is written
python3 ai-toolkit.pyz init --target . --yes       # apply
```

`discover` detects Python and Node projects, candidate build/test/lint
commands, existing workflows and provider integrations (SonarQube, Snyk,
FOSSA, CodeQL, Semgrep, Gitleaks), documentation, and installed agent clients.
In a polyglot repository the commands for one capability are chained with
`&&` so every detected suite must run and pass.
Python discovery reads development dependencies from `[dependency-groups]`
as well as project dependencies, extras, and requirements files. It proposes
pytest when declared. Without a pytest declaration, it proposes unittest only
when every discovered test file contains explicit `unittest.TestCase` or
`IsolatedAsyncioTestCase` classes with test methods, including normal import
aliases. Imports of helpers such as `unittest.mock` do not establish a runner.
Mixed suites containing standalone test functions or plain test classes, and
unrecognized shapes such as custom base classes, need an explicitly configured
test command; discovery does not guess a runner that would omit those tests.
The default unittest command also requires `__init__.py` in every directory
between nested test files and the repository root. Custom layouts without
those package markers need an explicit command with the appropriate start
directory.
`init` previews the files it would write and applies them only after `--yes`
or an interactive confirmation. Options:

| Option | Effect |
| --- | --- |
| `--install-set starter\|full` | Fresh default: starter; persisted in configuration and lock. Existing missing metadata retains full behavior |
| `--components proof,skills,qa` | Choose components; fresh default is proof,skills; QA orchestration requires explicit adoption |
| `--clients codex,claude-code` | Project skill directories to populate (`.agents/skills`, `.claude/skills`); defaults to detected clients |
| `--skills starter\|all\|name,...` | Skills to install; the starter set is small and review-oriented |
| `--profile github` | Add the optional GitHub provider profile |
| `--no-actions` | Install the runtime without workflow files |
| `--apply-variables` | Store discovered commands as GitHub repository variables with `gh` |

On a repository that already has `.proof/`, `init` fills gaps only and
records the installation; it never rewrites an installed runtime. Use `update`
to refresh.

### Repository commands stay in repository variables

Discovered commands are printed as `gh variable set PROOF_..._COMMAND`
lines and, with `--apply-variables`, set through `gh`. They are never written
into `toolkit.toml` or any committed file, so a pull request cannot change
what CI executes. Local scans read the same names from the environment
(`export PROOF_UNIT_TEST_COMMAND=...`).

### `toolkit.toml`

Commit this file. It holds only what nothing else owns:

```toml
[toolkit]
revision = "v2.3.0"
components = ["proof", "skills"]
install_set = "starter"

[agents]
clients = ["codex", "claude-code"]
skills_dir = ".agents/skills"

[proof]
policy = ".proof/policy.yaml"
providers = ".proof/providers.yaml"
profiles = ".proof/profiles.yaml"
actions = true            # false after init --no-actions; update never adds workflows then
github_profile = false    # true after init --profile github
```

`install_set` is also stored under `toolkit` in the managed-file lock; its absence
means the full legacy plan. The lock format remains version 1.

`actions` and `github_profile` record the installation mode chosen at `init`
so `update` reproduces it even when a workflow file of the same name is
consumer-owned or the installed policy is missing. Policy modes and provider
selection stay in `.proof/` and change only through
`.proof/configure.py` (or `ai-toolkit providers select CAPABILITY=PROVIDER`).

### `toolkit.lock.json`

Commit this file too. It records the toolkit revision, installed components,
and a SHA-256 for every managed file: the `.proof/` runtime, installed
workflows, and installed skills. `update` uses it to tell unmodified files
(refreshed) from modified ones (preserved and reported) and unmanaged files
(never touched). Installations made before the lock existed are bootstrapped
from the installer's ownership markers on the first `update`.

## Diagnose: `doctor`

```bash
python3 ai-toolkit.pyz doctor --target .
```

`doctor` is read-only; it never executes producers or configured commands.
Each component and capability is reported as one of:

| State | Meaning | Source |
| --- | --- | --- |
| `installed` | Managed files are present | lock and filesystem |
| `configured` | Required commands, workflows, and provider selections are declared | the existing setup diagnostic |
| `verified` | Evidence bound to the current `HEAD` shows `passed` or `failed` from the authoritative provider | `.artifacts/proof/evidence.json` from `check`, or a CI scorecard |

Every gap prints one concrete next action. `verified` describes the evidence
that exists; it is not a pass.

## Check: what ran, what failed, what remains unverified

```bash
python3 ai-toolkit.pyz check --target .
```

`check` runs the installed scanner (`.proof/scan.py`) and groups the
result: what ran and passed, what failed, what remains unverified (`blocked`
or `no_result` with the producer's reason), and what is not activated. Each
failed capability names the repair skill to run with the finding attached;
running it is a separate, explicit step. The exit code follows the scorecard
decision.

## Providers, skills, QA

```bash
python3 ai-toolkit.pyz providers                       # list with credentials and templates
python3 ai-toolkit.pyz providers show sonarqube
python3 ai-toolkit.pyz providers select deep-sast=snyk-code
python3 ai-toolkit.pyz skills install --skill starter --client codex,claude-code
python3 ai-toolkit.pyz skills refresh --skill all --user
python3 ai-toolkit.pyz qa status
python3 ai-toolkit.pyz qa bootstrap --client claude-code
```

Skills have one canonical source under `skills/` and are copied to
client-specific locations: `.agents/skills` (Codex) and `.claude/skills`
(Claude Code) in the project, or the clients' user directories with `--user`.
`qa bootstrap` installs the `qa-bootstrap` skill; your agent then runs it to
generate the `qa` orchestrator. Functional QA stays advisory.

## Update and roll back

```bash
python3 ai-toolkit.pyz update --target . --dry-run
python3 ai-toolkit.pyz update --target .
python3 ai-toolkit.pyz update --target . --rollback
```

`update` refreshes unmodified managed files from the running toolkit
revision, preserves modified files and lists them as conflicts with the
canonical version copied beside them under `.artifacts/ai-toolkit/conflicts/`,
restores missing files (including a partially deleted `.proof/`), and
rewrites the lock. Only skills the previous lock recorded are refreshed
(their canonical files are rewritten; files you added inside the directory
are kept) or restored when the directory was deleted; a directory you created
under a canonical skill name is left alone and listed until you adopt it with
`ai-toolkit skills install`, which records project installs in the lock and
adds the `skills` component (and `qa bootstrap` the `qa` component) to
`toolkit.toml`, so a later `update` keeps managing them instead of treating
them as removed. The install that first activates a component installs and
records the selected skills for every client the configuration already lists,
not only the client named on the command line, so `doctor` never reports a
managed client with nothing behind it. Every destination and both records are
checked before the first file is written (including that files a refresh would
overwrite are writable), the component is adopted only after every client has
its files and lock entries, and if an install or a record write still fails,
the installed files, `toolkit.toml`, and the lock are restored together.
Re-running `init` on an installed repository keeps the lock's baseline for
files it did not rewrite, so your local edits still surface as conflicts
later, and keeps every component and client already installed; removing one
is a separate, explicit step. Only the components named in that run install
anything new: re-running `init --components proof` on a repository with a
narrowly selected skill set leaves the selection alone, while asking for
`skills` or `qa` again installs the default set for any client that lacks it.
For the same reason a re-run without `skills` or `qa` never adopts a new
agent client: a detected client is left alone and a client named with
`--clients` is refused, because adopting one means installing skills for it.
A managed skill whose directory is missing at re-init time keeps its lock
entries, so the next `update` restores it instead of forgetting it.
A preserved conflict records the offered canonical version's hash in the
lock, so successive upgrades continue to preserve local edits and report
conflicts. Accepting the offered `.toolkit` copy resolves that conflict for
the next upgrade. This also applies to installations without a prior lock;
the baseline never comes from the preserved local bytes.
A backup of every managed file
is kept under `.artifacts/ai-toolkit/backup/<timestamp>-<unique-id>/`; even
updates within the same second have separate backups. `--rollback`
restores it and the previous lock. `update`, a project `skills install`, and
`qa bootstrap` refuse before touching any file when `toolkit.toml` or
`toolkit.lock.json` cannot be rewritten (either is a symlink, a directory, or
another non-regular entry, or the file or its directory is not writable), and
if writing them fails after the refresh, the managed
files, configuration, and lock are all restored together so the tree never
disagrees with the lock that describes it; the records are put back by
replacing the directory entry, so a symlink that appeared in the meantime is
never followed. Running `update` at the same
revision with nothing changed is a no-op.

## Trust boundaries

- `doctor` never executes anything; `verified` comes only from existing
  revision-bound evidence.
- Commands live in repository variables and the local environment, never in
  committed files.
- `.proof/` remains the public runtime contract; the CLI writes it
  through the installer and reads it through the installed scripts.
- Credentials stay in GitHub secrets or the provider platform.
- The archive is pinned by release tag and checksum; nothing is fetched at
  run time.

## Installing and verifying action skills

The standalone installer supports both agent clients. Preview a selected
Claude Code install with `tooling/install-skills.sh --client claude-code
--skill fix-ci --dry-run`; use `--client codex` for Codex. An explicit
`--target` overrides the selected client's default skills directory. The installer uses
`rsync` when it is available and otherwise falls back to `cp` and `find` with
the same install, merge, and replace results.

Without `rsync`, replacement uses `mktemp` and `mv` to stage a complete copy
beside the destination before moving the installed skill. Copy failures leave
the existing skill untouched; promotion failures restore it. HUP, INT, and TERM
also attempt restoration. If restoration fails or the destination is occupied,
the original is retained in the staging directory and its recovery path is
printed. Successful replacements remove the temporary backup. This protection
is per skill, not a transaction across the whole installation; uncatchable
termination can leave a staging directory for manual recovery.

Source and target roots must not overlap (including aliases resolved through
existing filesystem links); this is checked before installing any skill.
Redundant path separators and dot components are normalized before link checks.
For both copy backends, a write operation refuses a symlink at the target
skills directory or skill destination, or any symlink inside an existing skill.
This includes dangling links. Resolve these links explicitly before merging or
replacing a skill; skipping an existing skill remains read-only. Use a trusted
local destination that other processes do not modify during installation.

`--skill` takes a skill directory name as `--list` prints it; paths, `.`, and
`..` are rejected before anything is written.

The five action skills ship seeded tasks and per-client `VERIFICATION.md`
ledgers. Installation is not evidence that an agent completed a task.
`tooling/validate-skills.py` rejects duplicate client rows and requires each
verified row's Git revision to match the current skill bundle and fixture.
Verified rows also require a real date, agent version, outcome, and an evidence
link or explicit withholding reason. Both client rows remain unverified until
representative runs are recorded.

QA bootstrap copies plan and finding rules into the generated QA skill.
Agent-authored rows may claim only agent provenance. Sanitized non-passing
reports preserve the failure reason without passing the policy check;
missing regressions and flaky results remain blocked. Commands from PR
plans or findings are suggestions, not execution authority: use trusted
repository configuration or an approved allowlist.

QA CI checks out the exact PR base into `qa-trusted` for its prompt, skills,
config, plans, and findings. All executable test intent, including exploratory
prose, comes from that snapshot; missing trusted setup blocks execution. The
app under test remains at PR head. This does not make the PR-editable QA
workflow a tamper-resistant security gate.

A standalone `address-pr-findings` install bundles review contracts but does
not install sibling action skills. A routed finding blocks with the missing
skill named until its required sibling is installed; triage is still available.

Affirmative skill verification rows require Outcome `passed`; a failed, blocked,
or inconclusive run must remain unverified even when its evidence is recorded.
