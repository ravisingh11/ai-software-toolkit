# Codex Standards

These standards keep Codex-generated work useful, auditable, and safe across
repositories.

## File Structure

Use repo-local guidance when behavior depends on that repository:

- `AGENTS.md`: canonical repo instructions for Codex and humans.
- `CODEX.md`: optional Codex-specific quick reference when a repo needs one.
- `.codex/`: optional local Codex workflows, prompts, or generated notes that
  should be versioned for the repo.
- `docs/ai/`: longer AI operating notes, prompt packs, and review checklists.
- `.specify/`: optional Spec Kit project state for spec-driven feature work.

Use centralized guidance only for defaults that apply across repositories.

Reusable templates live in this repository:

- `templates/AGENTS.md`
- `templates/CODEX.md`
- `skills/`
- `prompts/`
- `docs/agent-workflows/`

## Recommended Repo-Level Sections

Each production repo should eventually have an `AGENTS.md` with:

- Project purpose and deployable surfaces.
- Required setup commands.
- Build, test, lint, and smoke-test commands.
- Branch, commit, and change-summary expectations.
- Security and secret-handling rules.
- Known validation gaps or environment limitations.
- Do-not-touch areas and generated files.

## Agent Operating Rules

- Inspect the repo before making assumptions.
- Preserve unrelated user changes.
- Keep commits scoped to a single coherent outcome.
- Run the narrowest meaningful verification first, then broader checks when
  risk justifies it.
- Treat CI as an explicit repository decision. Do not add workflow files or
  hosted runner dependencies unless the repository has selected that model.
- Prefer the narrowest reproducible verification that matches the repository's
  documented release process.
- Pull requests are the normal change path, including for solo-developer
  repositories. Repository rulesets may require additional approvals as the
  team grows.
- Never commit secrets, local credentials, customer data, or private logs.
- Do not rewrite history or delete branches unless explicitly requested.
- Prefer product-safe copy and production UI over demo/spec language.
- Use Spec Kit for substantial feature work when the repository has opted into
  spec-driven development.

## Prompt And Skill Files

- This toolkit publishes reusable prompts in `prompts/`, skills in `skills/`,
  and workflow guides in `docs/agent-workflows/`.
- Consuming repositories choose their own documentation hierarchy; `docs/ai/`
  is one option. Install executable skills in the agent tool's discovery path,
  such as `.agents/skills/`, rather than duplicating their instructions.
- Include inputs, expected outputs, and verification steps in every reusable
  workflow.
- Avoid storing one-off chat transcripts unless they are curated into a durable
  decision record.
