# Workspace and skill onboarding

Use a separate toolkit checkout at the published tag and an existing consumer
repository as the installation target. Start with the [quickstart](quickstart.md);
the default starter set includes Proof and seven skills. Installation never
executes a skill or enables an enforced check.

## Open the correct workspace

Open the consumer's actual repository folder in the agent client. After moving a
checkout, reopen its new location and update any saved project entry that still
points to the old folder. Changing a shell command's working directory does not
change the desktop client's saved project folder.

With the Codex CLI installed, `codex app /path/to/repo` opens that workspace in
the desktop app. Confirm the saved project entry also refers to the new folder;
an old bookmark can remain after opening a directory. Attaching a folder to a
message does not by itself establish that the saved project path changed.

Inspect the folder in the client's terminal:

```sh
pwd
git rev-parse --show-toplevel
git status --short
```

The reported Git root must be the intended repository. If the client still lists
the old path or says it is not a Git repository, correct that saved project
before relying on repository-local skill discovery. Reopening the folder is an
operator action, not a change the toolkit installer makes to desktop settings.

## Client locations

| Source or destination | Role |
| --- | --- |
| Toolkit `skills/<name>/SKILL.md` | Canonical skill source; not itself a consumer installation |
| Consumer `.agents/skills/<name>/SKILL.md` | Codex project discovery |
| Consumer `.claude/skills/<name>/SKILL.md` | Claude Code project discovery |
| `docs/ai/skills/` | Optional documentation; not an automatic discovery destination |

Codex discovers `.agents/skills` between its working directory and the repository
root. Its current documented user-wide location is `$HOME/.agents/skills`.
See [official Codex discovery guidance](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).
The toolkit's existing user-install defaults under `CODEX_HOME` remain unchanged
for compatibility; prefer explicit project destinations for new installations.

Use `--clients codex` or `--clients claude-code` with fresh `init`. Existing
consumers can add a selected skill through the CLI:

```sh
python3 /path/to/toolkit/tooling/ai_toolkit skills install --target /path/to/repo --skill starter --client codex --dry-run
python3 /path/to/toolkit/tooling/ai_toolkit skills install --target /path/to/repo --skill starter --client codex
```

Replace the client with `claude-code` for that client only. Do not run `init`
again merely to change an existing installation set. Preview updates and retain
customized skills as described in the [installation guide](install.md).

## Invoke one relevant skill

The starter set contains `toolkit-setup`, `prepare-safe-change`, `code-review`,
`test-gap-finder`, `security-audit-lite`, `dependency-risk-review` and `qa-bootstrap`.
These are agent procedures, separate from the 11 installed workflows and the
12 advisory Core checks. Additional action skills are explicit selections.

Open the client's skill selector and confirm the expected skill name and path.
If the client exposes both project and user copies, choose the intended copy;
matching names do not establish matching contents. For example:

> Use the code-review skill installed in this repository to review this diff.
> Read AGENTS.md first. Do not run local tests; use the linked hosted CI evidence.
> Report unavailable verification and do not change check enforcement.

Codex also supports explicit `$code-review` invocation. When a skill is absent
from the selector, check the workspace, installation destination and disabled
skill configuration before reinstalling. Do not install all skills to repair
discovery. In the toolkit source repository, follow the canonical task-to-skill
map in [AGENTS.md](../AGENTS.md#choose-a-skill-for-the-task).

## Recognize what has been demonstrated

| State | Evidence |
| --- | --- |
| Installed | Expected skill files are present |
| Discovered | Client exposes the intended name and file path |
| Invoked | Agent run identifies and reads that skill |
| Performed | Agent produces task-specific changes or findings |
| Verified | Required checks demonstrate the outcome for the recorded revision |

A passing skill-file validator establishes structure, not the last three states.
Record invocation evidence separately from hosted test evidence. Follow the
[real-client verification protocol](skill-verification.md) for the five action
skills. Missing credentials, clients or permitted execution remain unavailable
verification; they never become a pass.

All checks remain optional to adopt; Core stays advisory, and lifecycle/polyglot
execution stays manual. Skill routing grants no new permission to merge, deploy,
publish, modify credentials or change branch protection.
