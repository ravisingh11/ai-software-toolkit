# AI Software Toolkit: vision and scope

AI Software Toolkit helps development, QA, security, and release teams turn
AI-assisted work into software they can verify and maintain. It brings shared
skills, standards, verification workflows, and the Guardrails evidence runtime
together. Teams adopt the components that fit their repository and workflow.

This document describes direction and maturity. It does not introduce new
enforced controls or promise delivery dates.

## A shared delivery lifecycle

| Activity | Shared responsibility | Relevant capabilities in this source tree |
| --- | --- | --- |
| Plan | Define user outcomes, acceptance criteria, risks, and testability with QA involved early | [Spec-driven development](../skills/spec-driven-development/SKILL.md), [safe change preparation](../skills/prepare-safe-change/SKILL.md) |
| Build | Implement scoped changes, review design, and preserve application contracts | [Code review](../skills/code-review/SKILL.md), [dependency remediation](../skills/dependency-remediation/SKILL.md) |
| Validate | Combine automated checks with exploratory judgment and evidence from user flows | [QA bootstrap](../skills/qa-bootstrap/SKILL.md), [test-gap analysis](../skills/test-gap-finder/SKILL.md), [testing policy](../policies/testing.md) |
| Release | Assess readiness, examine evidence, and follow the application's release authority | [Release readiness](../skills/release-readiness/SKILL.md), [Guardrails](guardrails/README.md) |
| Improve | Investigate failures, refine acceptance criteria, and improve future verification | [Bug investigation](../skills/bug-hunter/SKILL.md), QA learned failure modes, prospective delivery measurement |

These activities are connected, not sequential handoffs between departments.
QA expertise informs risk selection and acceptance criteria before implementation,
exploratory work during validation, and regression coverage after incidents.
Security and operational constraints likewise influence planning and design.
Agents assist; accountable people own decisions and outcomes.

## How the components fit

- **Standards** define expectations and security boundaries.
- **Skills** guide agents through repeatable tasks using repository ground truth.
- **Verification** produces observations from tests, QA sessions, and scanners.
- **Guardrails** evaluates provider evidence for the exact subject and selected
  policy. Its architecture and public runtime remain [Guardrails v2](guardrails/architecture.md).
- **Measurement**, a future area of work, would connect delivery outcomes to
  improvements in the preceding activities.

## What exists and what remains aspirational

| Area | Current maturity | What adoption still requires |
| --- | --- | --- |
| Guardrails Core and GitHub integration | Available runtime, installer, providers, and workflow configuration; the README demo pins v1.0.0 | Real consumer commands, applicable credentials/settings, and observed evidence |
| Shared skills | Source catalog with a separate [skills installer](../skills/README.md#install-locally) | Choose a revision containing the desired skill and supply application context; installation is not execution |
| Agent-driven functional QA | Newer source capability recorded under [Unreleased](../CHANGELOG.md#unreleased), outside default profiles | Run QA bootstrap, configure usable drivers and environments, execute generated QA, and inspect its evidence; it is not part of the v1.0.0 demo |
| AI security guidance | Policy covering agent authority, data, tools, memory, and verification | Configure and verify actual agent/runtime protections; policy text does not enable them |
| Release and runtime assurance | Readiness skills exist; several lifecycle capabilities remain [evidence-only contracts](guardrails/architecture.md#evidence-only-lifecycle-capabilities) | Implement and validate the missing producers before claiming runtime assurance |
| DORA and AI delivery diagnostics | Aspiration; no measurement pipeline or dashboard is established by this documentation | Define service boundaries and data sources, implement collection, and validate attribution and completeness |

Source availability, release availability, consumer configuration, and a
successful observed run are distinct. Consult the changelog for the revision
you install. An example result does not prove that a consuming application's
flow works or that its deployment is healthy.

QA bootstrap generates a consumer-owned orchestrator, per-app skills, and
optional execution/reporting workflows. The generated QA skill runs the flows;
bootstrap itself does not validate the application. Functional QA is opt-in
and advisory-only under the current provider contract. AI review also remains
advisory-only. Other controls follow the existing [promotion rules](guardrails/control-status.md).

## Aspiration: learn from delivery outcomes

The direction is to connect planning, implementation, QA findings, release
evidence, and production feedback without replacing application-owned systems.
A useful first measurement slice would use DORA's five current delivery metrics:
change lead time, deployment frequency, failed deployment recovery time,
change fail rate, and deployment rework rate. Measure them for an application
or service over time with consistent definitions, rather than ranking people.
See [DORA's definitions and measurement guidance](https://dora.dev/guides/dora-metrics/)
(reviewed 2026-09-24).

Candidate AI diagnostics include idea-to-production time, review wait and
effort, rework before merge, escaped defects, and cost per accepted outcome.
These are proposed diagnostics, not additional official DORA metrics or
implemented toolkit features. They should explain bottlenecks and tradeoffs,
not reward generated lines or model usage.

Any future collector must identify its source, service, measurement window,
and missing data. Production metrics need deployment and incident evidence;
Git activity alone is insufficient. Unknown results must remain unknown.
Delivery measurement should begin as advisory learning, not a per-PR gate.

## Scope and ownership

The toolkit owns reusable methods, contracts, and integrations. Application
repositories own business behavior, architecture, acceptance criteria, test
data, environments, credentials, release authority, and product-specific QA
flows. Shared skills help teams create and maintain that local knowledge.

Future expansion should start with a concrete recurring need, an accountable
owner, and a verifiable result. Add only the reusable part here; keep the
application's decisions and sensitive context with its owners. Follow the
[contribution boundaries](../CONTRIBUTING.md) and [security policy](../SECURITY.md).
