# Specification-driven development

Write down intent and acceptance evidence before substantial features, unclear
requirements, cross-client changes, or risky refactors. Use Markdown, an issue
tracker, your team's templates, or an optional specification tool. No tool is
required by this standard or by Proof.

## Artifacts and procedure

1. Capture the outcome, user journeys, constraints, assumptions, and edge cases.
2. Resolve ambiguities that change scope or safety before implementation.
3. Record technical decisions, contracts, risks, and release gates in a plan.
4. Split work into independently reviewable and testable tasks.
5. Check consistency between the intent, plan, tasks, and acceptance evidence.
6. Update the documents when implementation changes the agreed behavior.

Keep intent separate from implementation decisions. A possible layout is
`specs/<id>-<name>/{spec.md,plan.md,tasks.md}`; existing repository conventions
are equally valid. Link the owning issue and make acceptance evidence traceable
to the evaluated revision. Tiny corrections can use an issue or PR description.
Urgent fixes can record the evidence directly without scaffolding a full spec.

Never put credentials, customer data, private logs, or sensitive operational
details in specifications, plans, tasks, or checklists.

## Optional Spec Kit integration

[GitHub Spec Kit](https://github.com/github/spec-kit) is one implementation of
this process. Initialize it separately, then explicitly install the optional
[engineering standards preset](../../tooling/speckit/engineering-standards/README.md).
The compatibility identifier remains `engineering-standards`, independently
versioned at 1.0.0. Proof and the seven starter skills do not require it.

From a Spec Kit initialized consumer, use the preset from a source checkout:

```sh
specify preset add --dev /path/to/ai-software-toolkit/tooling/speckit/engineering-standards --priority 5
specify preset list
specify preset resolve spec-template
```

Use the upstream constitution, specify, clarify, plan, tasks, analyze, and
implement commands only when that workflow suits the repository. A previously
published [v2.2.1 preset asset](https://github.com/ravisingh11/ai-software-toolkit/releases/download/v2.2.1/spec-kit-preset-engineering-standards-v1.0.0.zip)
remains available; the preset README covers explicit packaging and installation.

## Related standards

- [Release evidence](release-evidence-standard.md)
- [Error handling](error-handling-standard.md)

These standards describe outcomes; the chosen specification tool helps record them.
