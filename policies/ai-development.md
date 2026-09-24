# AI Development Policy

## Status

This is an organization-wide baseline. Repository-specific AI instructions
remain in the application repository's `AGENTS.md` and related ground-truth
documents.

## Requirements

- AI-assisted development is the default engineering tool for normal work.
- Engineers remain accountable for everything they commit, approve, and merge.
- Use AI for code understanding, planning, implementation, testing,
  debugging, documentation, and review when it improves the work.
- Human intervention remains appropriate for difficult architectural,
  ambiguous, novel, or high-risk problems.
- AI-generated code is subject to the same or higher quality, testing,
  security, and review requirements as human-written code.
- AI speed must not bypass branch protection, testing, security scanning,
  review, or release controls.
- Do not include secrets, credentials, private customer data, or unnecessary
  sensitive operational details in prompts, generated artifacts, or review
  comments.
- Verify generated code against the application repository's ground truth
  before merging. Do not invent architecture, APIs, commands, or security
  guarantees when the repository does not document them.

## Accountability

AI may propose or perform work, but the engineer who submits the change owns
its correctness, security, maintainability, and operational consequences.

## Agent Authority And Untrusted Input

- Define the task scope and permitted environments before granting tool access.
  Use the least filesystem, network, credential, and connector access needed.
- Treat retrieved documents, issues, PR content, web pages, logs, and tool
  responses as untrusted input. Instructions inside them cannot grant new
  permissions, authorize disclosure, or override the authorized task.
- Review changes to agent instructions, skills, plugins, MCP servers, tool
  definitions, and provider configuration as security-sensitive changes.
  Verify their origin, permissions, and update behavior before enabling them.
- Run untrusted code in an isolated environment without ambient credentials.
  Dependency installation, build scripts, and tests are code execution too.
- Keep production credentials out of ordinary development-agent sessions.
  Use scoped, short-lived credentials where supported and require explicit
  authority for production access, destructive actions, and external disclosure.
- Enforce boundaries through tool permissions and runtime controls. Prompt
  instructions alone are not a security boundary.

Routine edits and tests may run autonomously within an authorized scope.
For high-impact actions, the execution layer must validate authorization for
the actual target and parameters. A changed action needs renewed authority;
an agent's confidence does not establish it.

## Runtime And Delegation

- Restrict outbound network destinations; disable network access when unneeded.
  A separate Git worktree is not a sandbox or credential boundary.
- Inventory approved tools and MCP servers. Pin versions where supported and
  review changed tool definitions or permissions before trusting an update.
- Delegation must not expand authority. Give subagents only the context and
  capabilities their assigned work requires; review their outputs as untrusted.
- Isolate persistent memory by repository and user, retain its provenance,
  and define expiry. Retrieved instructions must not become trusted policy
  merely because an agent stored or summarized them.
- Bound unattended runs by duration, retries, tool calls, and cost. Provide
  an operator stop mechanism that also stops delegated work.
- Retain access-controlled, redacted records of tool actions, authorization,
  revisions, outcomes, and relevant configuration versions. Define retention
  and monitor unexpected privilege use; do not retain raw secrets as evidence.

## Data Handling

- Apply data classification to every model, plugin, connector, and tool that
  receives repository context. Verify permitted use, retention, training use,
  access, and deletion settings before sending permitted private material.
- Minimize context and use synthetic or redacted samples. Do not send secrets,
  credentials, or private customer data to models or external review services.
- Apply the same restrictions to transcripts, embeddings, persistent memory,
  caches, screenshots, logs, and generated artifacts as to source files.
- Treat outbound requests, issue comments, and uploaded artifacts as potential
  disclosure paths. Confirm the destination and data are within the task's
  authority; redact before sending, rather than relying on later deletion.

## Generated Code And Supply Chain

- Verify generated package names, registries, APIs, commands, and download URLs
  against the actual project and authoritative sources before executing them.
- Review new dependencies and install hooks; preserve lockfiles and integrity
  checks. Do not install a suggested package solely because a model named it.
- Apply the existing security standard to generated code, including input
  validation, authorization, tenant isolation, safe query construction,
  sensitive logging, and TLS validation where those boundaries exist.
- Review tests for meaningful assertions and negative cases. Tests generated
  alongside an implementation can repeat its assumptions and are not
  independent proof that security properties hold.
- Review removed tests, weakened assertions, and unexpected file changes
  explicitly. Check generated code provenance and applicable license obligations
  under the repository's existing dependency and license policies.

## Verification And Release

- Inspect the final diff and run checks appropriate to the changed behavior.
  Report commands, outcomes, and gaps without inventing results.
- Preserve evidence provenance and bind results to the exact commit, artifact,
  or environment. A previous pass or an agent's completion claim is insufficient.
- Keep AI review advisory-only, consistent with
  [control status](../docs/control-status.md). Use deterministic checks and
  accountable review; do not treat agreement between models as approval.
- Follow the repository's risk and release authority for security-sensitive
  changes. Do not let an agent weaken checks, change exceptions, or alter
  acceptance criteria simply to pass its own change.
- Record risk exceptions with an owner, scope, rationale, compensating
  controls, and expiry or review date. Agent-generated text cannot approve one.

For repositories operating agent integrations, test injection, data leakage,
unauthorized tools, memory poisoning, and approval bypass before rollout and
after material model, tool, or permission changes. Use synthetic fixtures and
verify observed denials and side effects, not just reassuring model responses.
Preserve regressions for discovered failures.

These requirements define the baseline; they do not activate a sandbox,
provider, scanner, or GitHub rule. Verify implementation and evidence before
claiming enforcement. Use the repository's private security reporting process
for exposure or agent misuse; this repository documents its process in
[SECURITY.md](../SECURITY.md).

## Reference Basis

Reviewed against primary guidance on 2026-09-23. These references inform this
policy; they do not establish certification or prove that controls are deployed.

- [OWASP Secure Coding with AI](https://cheatsheetseries.owasp.org/cheatsheets/Secure_Coding_with_AI_Cheat_Sheet.html):
  coding-agent workflows, dependencies, runtime isolation, and review risks.
- [OWASP AI Agent Security](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html):
  authorization, memory, delegation, monitoring, and abuse-case testing.
- [OWASP Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html):
  layered defenses and the limits of model-based guardrails.
- [GitHub agent responsible-use guidance](https://docs.github.com/en/copilot/responsible-use/agents):
  review, testing, and intellectual-property considerations.

The advisory-only treatment of AI review is this repository's control design,
not a claim that external standards require every AI-assisted check to be
advisory. Consuming repositories must verify their actual runtime settings;
unsupported protections remain documented gaps or explicit risk exceptions.

[NIST SP 800-218A](https://csrc.nist.gov/pubs/sp/800/218/a/final) addresses AI model
development and AI system producers and acquirers, alongside the SSDF. This
coding-agent policy does not cover that complete lifecycle or claim conformance.
