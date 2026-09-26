# AI Software Toolkit Skills

This directory is the canonical source for reusable agent skills in the
AI Software Toolkit. Skills are small, task-specific operating
guides that tell Codex how to perform repeatable engineering, security,
QA, release, and repository administration work.

## Choose a starting point

- **Plan and build:** use specification, safe-change, review, and maintenance
  skills with the application's acceptance criteria and architecture.
- **QA and validation:** start with [QA bootstrap](qa-bootstrap/SKILL.md) to
  generate application-specific QA skills; use test-gap and audit skills to
  identify missing coverage. Bootstrap installs the capability; generated
  skills execute the flows. QA also informs requirements and future regressions.
- **Security and release:** use security review and release-readiness skills
  to assess risks and evidence within the application's authority.

See [the delivery lifecycle and maturity map](../docs/vision.md). Choose a
source revision or release containing the desired skill; newer QA additions
are documented under [Unreleased](../CHANGELOG.md#unreleased), not in the
v1.0.0 Guardrails demo. Installing a skill does not prove it has run.

## Policy

- Keep canonical skills here.
- Treat `skills/` in this repository as the active source of truth for shared
  agent skills.
- Prefer linking to these skills from repo-local `AGENTS.md`.
- Copy a skill into a product repo only when the repo needs customization.
- Repo-local copies should live under `docs/ai/skills/<skill-name>/SKILL.md`.
- Keep `_shared-project-ops` with the skill set because multiple skills depend on its scripts and reference templates.
- Do not add machine-local skills such as screen-history or personal-memory tooling to this directory.
- Keep `SKILL.md` concise. Put detailed examples, rubrics, and long procedures under `references/`.
- Every canonical skill must have `agents/openai.yaml`.

## Install Locally

From the repository root:

```bash
tooling/install-skills.sh --list
tooling/install-skills.sh --all --dry-run
tooling/install-skills.sh --all --merge-existing
tooling/install-skills.sh --all --client claude-code   # ~/.claude/skills instead of ~/.codex/skills
```

One canonical source serves both clients: the `SKILL.md` frontmatter (`name`,
`description`) is what Claude Code reads, and `agents/openai.yaml` carries the
Codex interface. `--client` only changes the default destination.

The [`ai-toolkit` CLI](../docs/install.md) installs the same canonical skills
for Codex (`.agents/skills`) and Claude Code (`.claude/skills`) without
`rsync`, and records them in `toolkit.lock.json`:

```bash
python3 tooling/ai_toolkit skills install --skill starter --client codex,claude-code
```

Install behavior:

- First-time installs copy the selected skill and `_shared-project-ops`.
- Existing target skills are skipped by default in non-interactive runs.
- Interactive runs prompt to skip, merge missing files only, or replace.
- `--merge-existing` preserves local files and adds missing canonical files.
- `--replace-existing` fully replaces the target skill and should be used deliberately.

## Skill Catalog

### Action skills

These five skills change code and prove the change. Each defines its inputs,
permitted changes, stop conditions, verification, and outcome report, ships a
seeded fixture under `tooling/tests/fixtures/skills/<name>/`, and keeps a
`VERIFICATION.md` ledger with one row per supported client (Codex, Claude
Code). A skill is verified only when a live run is recorded there;
`tooling/validate-skills.py` requires both rows. `ai-toolkit check` names the
applicable action skill for each failed capability; running it is a separate,
explicit step.

- `fix-ci` — make a red check green by fixing the cause, never by weakening the check.
- `generate-unit-tests` — write behavior-protecting tests for changed or untested code.
- `fix-security-finding` — confirm, remediate, and regression-test one security finding.
- `dependency-upgrade` — move one dependency forward with compatibility proof and rollback notes.
- `address-pr-findings` — resolve or decide every review finding with verification.

The additional skills below are optional shared capabilities. They remain in
this repository because they are reusable, but application repositories should
install only the skills they actually need.

### Core Review And Audit

- `api-contract-auditor`
- `bug-hunter`
- `code-review`
- `config-drift-auditor`
- `data-model-migration-review`
- `dependency-risk-review`
- `docs-sync`
- `frontend-regression-review`
- `full-product-review`
- `qa-bootstrap`
- `full-test-suite`
- `observability-gap-review`
- `onboarding-doc-builder`
- `project-health-check`
- `refactor-safety-check`
- `release-readiness`
- `security-audit-lite`
- `spec-driven-development`
- `test-gap-finder`

### Repository Operations

- `change-guardrail-control`
- `commit-message-enforcer`
- `dependency-remediation`
- `github-actions-hardening`
- `ios-release-qa`
- `ios-testflight-release-cycle`
- `issue-operator`
- `license-compliance`
- `multi-tenant-saas-readiness`
- `repo-admin-hygiene`
- `repo-bootstrap`
- `ruleset-governance`
- `skill-installer`

## Which Skill To Use

- Use `repo-bootstrap` for a new or newly adopted repo.
- Use `change-guardrail-control` whenever a capability, provider, producer,
  evidence contract, activation setting, or enforcement mode changes.
- Use `repo-admin-hygiene` for descriptions, homepages, topics, labels, default branches, Wikis, Projects, and GitHub metadata.
- Use `license-compliance` for root `LICENSE` files and first-party package metadata.
- Use `dependency-remediation` for Dependabot, Snyk, npm audit, package drift, and lockfile cleanup.
- Use `github-actions-hardening` for workflow permissions, secrets, OIDC, action pinning, and CI/CD supply-chain posture.
- Use `ruleset-governance` for branch, tag, push, and required-check rulesets.
- Use `commit-message-enforcer` for commit history hygiene and Conventional Commit enforcement.
- Use `spec-driven-development` for substantial feature work that should start
  from Spec Kit specs, plans, tasks, and release evidence.
- Use `multi-tenant-saas-readiness` before launching or hardening tenant-scoped
  SaaS products.
- Use `ios-release-qa` for release-candidate QA around environment locks,
  accessibility, iPad/device flows, and App Store/TestFlight readiness.
- Use `full-test-suite` for a broad scan-fix-verify loop across the project-ops skills.
- Use `qa-bootstrap` to set up agent-driven functional QA in a product repo: a
  `qa` orchestrator, per-app `qa-<app>` flow menus, and optional GitHub Actions
  workflows with a read-only advisory QA check and trusted sticky-comment reporting.
- Use `fix-ci`, `generate-unit-tests`, `fix-security-finding`,
  `dependency-upgrade`, or `address-pr-findings` when a check, coverage gap,
  scanner finding, advisory, or review has named the work to do; they act and
  verify, where the review skills only report.
- Use `skill-installer` to install or refresh canonical skills locally.
- Use `toolkit-setup` to install, diagnose, or refresh the whole toolkit
  through the shared `ai-toolkit` CLI; it runs the same discovery and
  installation code as the CLI and the GitHub starter workflow.

## Support Bundle

- `_shared-project-ops/references`: shared finding, issue, severity, dedupe, rerun, and verification templates.
- `_shared-project-ops/scripts`: shared state tooling used by `full-test-suite`, `issue-operator`, and audit skills.

## Maintenance

- Add a new skill only when the workflow is repeated, fragile, or broadly useful enough to justify durable instructions.
- Keep frontmatter to `name` and `description`.
- Make the description explicit about when the skill should trigger.
- Add `agents/openai.yaml` with a human-readable display name, short description, and default prompt.
- Put deterministic logic in `scripts/` and long guidance in `references/`.
- Avoid storing secrets, local paths, screenshots, machine-specific history, or personal memory details in skills.
- Run validation before committing.

```bash
python3 tooling/validate-skills.py
```

## Drift Control

When a repo has copied skills, compare its local copy against this directory
before editing. Update copied skills with a scoped commit, issue note, or pull
request when that repository chooses to use PRs, so changes remain visible and
reviewable.

If a product repo diverges from the canonical skill, document why in the repo-local copy. Otherwise, refresh it from this directory.
