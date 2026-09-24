# Security Policy

## Scope And Ownership

This repository publishes shared engineering policy, agent instructions,
reusable CI workflows, and the Guardrails runtime. Its security boundary is
the integrity of those materials and the decisions made from their evidence.
It is not an application service and has no application database or migration
framework. Consuming repositories own their application threat models,
deployment boundaries, data classifications, and security contacts.

The maintainer owns this repository's security policy. Engineers remain
accountable for changes made by AI agents under their authority.

Shared requirements live in [the security standard](policies/security.md),
[the AI development policy](policies/ai-development.md), and
[the GitHub Actions security policy](policies/github-actions-security.md).
This document describes repository-specific review and disclosure context;
it does not grant an agent permission to execute commands or access data.

## Reporting A Vulnerability

Do not open a public issue for suspected credential exposure, private data
leakage, or other sensitive vulnerabilities.

When GitHub displays **Report a vulnerability**, use
[private vulnerability reporting](https://github.com/ravisingh11/engineering-standards/security/advisories/new).
That feature requires separate repository configuration; this policy does not
enable it. If unavailable, use a private security contact published by the
maintainer. If none is available, open an issue asking only for a private
security contact, without vulnerability details, credentials, or customer data.

Provide affected paths and revisions, the trust boundary crossed, expected
and observed behavior, and a minimal reproduction using synthetic data.
Remove sensitive values from logs and screenshots before sharing them.
Coordinate disclosure privately with the maintainer.

## Support Commitments

This repository does not currently publish a supported-version policy or a
response-time commitment. Those remain maintainer decisions; this document
does not imply security maintenance for every historical revision. Include
the affected revision in reports even when support status is unclear.

## Threat Model And Trust Boundaries

Protect source and release integrity, provider credentials, developer and CI
environments, private context, and the accuracy of Guardrails decisions.
Assume an attacker can submit a pull request or supply content that an agent
reads. Relevant boundaries include:

| Surface | Security boundary |
| --- | --- |
| PR diffs, issues, documents, web pages, logs, and tool responses | Retrieved content is evidence, not authority to change the task, reveal data, or invoke tools. |
| `AGENTS.md`, skills, prompts, plugins, and MCP servers | Changes can alter agent behavior or available capabilities and require review before trusted use. |
| Agent shell, filesystem, browser, and connectors | Tool execution must stay within the authorized task, data access, and environment. |
| Dependencies, install hooks, and build/test scripts | Running repository code can execute attacker-controlled instructions even when the task is described as review or validation. |
| Workflows, rulesets, `.guardrails/`, and provider evidence | Untrusted changes must not redefine trusted checks, forge results, or authorize their own promotion. |

Prompt injection includes content that impersonates a maintainer, claims an
urgent exception, requests secret disclosure, or tells an agent to weaken
checks. The presence of such text is not itself proof of exploitation; assess
whether it can cross a real permission or data boundary.

## Security Invariants

- Agent authority comes from the authorized task and trusted runtime controls,
  not from instructions embedded in retrieved content or proposed changes.
- Agent credentials, filesystem access, network access, and connector scopes
  must be limited to the task. Production access and destructive operations
  require explicit authority; uncertainty must not expand permissions.
- Untrusted contributions must not run with privileged tokens, production
  secrets, or a developer's ambient credentials. Use an isolated environment
  for executing their code, including install hooks and tests.
- AI output is untrusted until reviewed and verified. Generated commands,
  package names, URLs, patches, and suggested fixes must be checked before use.
- Changes to policies, workflows, agent instructions, or evidence producers
  must not approve themselves or bypass the normal PR and validation process.
- Guardrails evidence must come from the configured authoritative producer
  and identify the exact subject being evaluated. Missing, skipped, stale,
  blocked, or unconfigured evidence must never be represented as passed.
- Security controls must not be disabled or findings suppressed merely to
  obtain a passing result. AI review cannot be the sole merge gate.

## Sensitive Data

This repository should not contain:

- real credentials, tokens, API keys, private keys, or session artifacts
- private customer data or production payloads
- private domains, private repository inventories, or internal rollout logs
- screenshots or logs containing sensitive operational details

If sensitive data is committed, rotate the affected credential or invalidate the
affected artifact before removing it from the repository.

These restrictions also apply to prompts, embeddings, agent memory, tool
arguments, telemetry, generated reports, and external review services. Use
synthetic or minimized, redacted data and verify provider handling before
sending permitted private context. See the
[AI data-handling requirements](policies/ai-development.md#data-handling).

## Reportable Findings And Severity

Report reachable failures that allow unauthorized execution, data disclosure,
credential theft, privilege expansion, source or artifact tampering, or a false
security decision. Examples include attacker-controlled content triggering a
privileged tool, a PR stealing runner credentials, and forged or stale evidence
being accepted for an enforced capability.

Describe attacker control, prerequisites, affected assets, and practical impact.
Assess severity from the demonstrated boundary failure and blast radius;
AI-generated code is neither safer nor more severe solely because of its origin.
Clearly distinguish a demonstrated vulnerability from an untested hypothesis
or a policy-hardening recommendation. Never use real secrets or destructive
production actions to prove impact.

## Limitations And Exceptions

Documented requirements are not proof of enforcement. Core and optional GitHub
profile capabilities start advisory; all AI review controls are advisory-only.
Actual enforcement depends on repository configuration, authoritative producer
evidence, and rulesets. See [control status](docs/control-status.md) for the
meaning of advisory, enforced, not activated, and missing-result states.

This policy does not activate an automated prompt-injection defense, sandbox,
provider integration, or new blocking check. Prompt wording and AI self-review are not
substitutes for access controls and independent validation.

No new finding exclusions or accepted risks are established here. Component
policies, including [the Python demo policy](examples/python-demo/SECURITY.md),
describe narrower boundaries; they must not be treated as blanket exclusions
for shared tooling or supply-chain failures. Application-specific findings
belong with the consuming repository's security owner.

Exceptions require an accountable owner, rationale, affected scope,
compensating controls, and an expiry or review date. An agent's assertion that
a risk is acceptable does not authorize an exception.

## Incident Containment

If an agent exposes data or acts outside its authority, stop the affected run
and revoke its relevant sessions or credentials. Preserve sanitized evidence
of the revision, tool actions, destinations, and affected artifacts in the
private reporting channel. Remove compromised plugins or integrations from
use and inspect resulting changes before resuming work.

Rotate exposed credentials even if a prompt, transcript, or commit is later
deleted. Assess downstream repositories and releases when shared policy,
workflow, or runtime artifacts were compromised. Restore trusted configuration
and rerun relevant checks before re-enabling the affected automation.

## Policy Maintenance

The maintainer should review this policy when agent permissions, providers,
shared workflows, or evidence contracts materially change, and after a security
incident. The [AI policy reference basis](policies/ai-development.md#reference-basis)
records the external guidance used. Alignment with that guidance is not a
claim of certification or verified enforcement.

[GitHub's security-policy guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/add-security-policy)
calls for supported-version and reporting information. Before representing
disclosure readiness as complete, the maintainer must publish the support scope
and verify the private reporting route.
