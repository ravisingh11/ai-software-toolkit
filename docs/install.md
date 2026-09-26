# Install with the `ai-toolkit` CLI

The `ai-toolkit` command is one front door for Guardrails, shared skills, and
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

## Set up a repository

```bash
python3 ai-toolkit.pyz discover --target .        # read-only
python3 ai-toolkit.pyz init --target . --preview   # nothing is written
python3 ai-toolkit.pyz init --target . --yes       # apply
```

`discover` detects Python and Node projects, candidate build/test/lint
commands, existing workflows and provider integrations (SonarQube, Snyk,
FOSSA, CodeQL, Semgrep, Gitleaks), documentation, and installed agent clients.
`init` previews the files it would write and applies them only after `--yes`
or an interactive confirmation. Options:

| Option | Effect |
| --- | --- |
| `--components guardrails,skills,qa` | Install a subset; each component is independently adoptable |
| `--clients codex,claude-code` | Project skill directories to populate (`.agents/skills`, `.claude/skills`); defaults to detected clients |
| `--skills starter\|all\|name,...` | Skills to install; the starter set is small and review-oriented |
| `--profile github` | Add the optional GitHub provider profile |
| `--no-actions` | Install the runtime without workflow files |
| `--apply-variables` | Store discovered commands as GitHub repository variables with `gh` |

On a repository that already has `.guardrails/`, `init` fills gaps only and
records the installation; it never rewrites an installed runtime. Use `update`
to refresh.

### Repository commands stay in repository variables

Discovered commands are printed as `gh variable set GUARDRAILS_..._COMMAND`
lines and, with `--apply-variables`, set through `gh`. They are never written
into `toolkit.toml` or any committed file, so a pull request cannot change
what CI executes. Local scans read the same names from the environment
(`export GUARDRAILS_UNIT_TEST_COMMAND=...`).

### `toolkit.toml`

Commit this file. It holds only what nothing else owns:

```toml
[toolkit]
revision = "v2.1.0"
components = ["guardrails", "skills", "qa"]

[agents]
clients = ["codex", "claude-code"]
skills_dir = ".agents/skills"

[guardrails]
policy = ".guardrails/policy.yaml"
providers = ".guardrails/providers.yaml"
profiles = ".guardrails/profiles.yaml"
```

Policy modes and provider selection stay in `.guardrails/` and change only
through `.guardrails/configure.py` (or `ai-toolkit providers select`).

### `toolkit.lock.json`

Commit this file too. It records the toolkit revision, installed components,
and a SHA-256 for every managed file: the `.guardrails/` runtime, installed
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
| `verified` | Evidence bound to the current `HEAD` shows `passed` or `failed` from the authoritative provider | `.artifacts/guardrails/evidence.json` from `check`, or a CI scorecard |

Every gap prints one concrete next action. `verified` describes the evidence
that exists; it is not a pass.

## Check: what ran, what failed, what remains unverified

```bash
python3 ai-toolkit.pyz check --target .
```

`check` runs the installed scanner (`.guardrails/scan.py`) and groups the
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
restores missing files, and rewrites the lock. A backup of every managed file
is kept under `.artifacts/ai-toolkit/backup/<timestamp>/`; `--rollback`
restores it and the previous lock. Running `update` at the same revision with
nothing changed is a no-op.

## Trust boundaries

- `doctor` never executes anything; `verified` comes only from existing
  revision-bound evidence.
- Commands live in repository variables and the local environment, never in
  committed files.
- `.guardrails/` remains the public runtime contract; the CLI writes it
  through the installer and reads it through the installed scripts.
- Credentials stay in GitHub secrets or the provider platform.
- The archive is pinned by release tag and checksum; nothing is fetched at
  run time.
