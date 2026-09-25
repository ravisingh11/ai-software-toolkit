# Control status

Guardrails reports mode, evidence status, readiness color, and overall decision
separately. Do not infer one from another.

## Status vocabulary

| Layer | Values | Meaning |
| --- | --- | --- |
| Mode | `advisory`, `enforced`, `not_activated` | Whether the capability is selected and whether a missing pass blocks. |
| Producer status | `passed`, `failed`, `blocked`, `not_run` | Raw provider outcome. |
| Public evidence status | `passed`, `failed`, `blocked`, `no_result`, `not_activated` | Scorecard vocabulary; missing and `not_run` normalize to `no_result`. |
| Decision | `allow`, `block` | Whether enforced capabilities and subject binding permit the operation. |

## Readiness colors

| Color | Exact condition |
| --- | --- |
| **GREEN** | The authoritative provider returned `passed` for the exact subject. |
| **ORANGE** | The capability is advisory and its authoritative provider did not return an exact-subject pass. |
| **RED** | The capability is enforced and its authoritative provider did not return an exact-subject pass, or the evidence subject mismatches. |
| **GRAY** | The capability is not activated for this operation and subject type. |

An `ORANGE / ALLOW` scorecard is truthful: unresolved advisory capabilities
remain visible without blocking. `RED / BLOCK` means enforcement or subject
binding failed. `GREEN / ALLOW` means every selected authoritative provider
passed for the exact subject. Default scorecards omit inactive controls;
`GRAY` rows appear only when `--all-catalog-controls` requests the complete
catalog view.

## Common interpretations

| Observation | Interpretation |
| --- | --- |
| Workflow installed | Configuration only; no result yet. |
| Job skipped because a variable is unset | `NO RESULT`. |
| Format/lint or migration command is unset in Actions | The named check fails; locally the capability is `NO RESULT`. |
| Settings token exists | Probe can attempt access; not a pass. |
| Supplemental provider passed | Useful advisory evidence; authoritative result still decides. |
| Prior commit passed | Stale for the current commit; `NO RESULT`. |
| Artifact attestation exists | Relevant only to that exact artifact subject. |
| Scorecard job completed | Aggregation ran; inspect each capability and the overall decision. |
| `PR Change Scope` is neutral | Trusted evidence found an oversized PR under advisory policy; inspect its exact metrics and split guidance. |

## Default profile state

Core is selected by default and all Core capabilities begin advisory. The
GitHub profile is optional and additive; its capabilities also begin advisory.
Capabilities outside selected profiles are omitted by default. In a complete
`--all-catalog-controls` view they appear `GRAY` unless a repository adds a
runnable mode override.

Future lifecycle capabilities marked `evidence-only` are also omitted by
default and appear `GRAY` only in the complete catalog view. They cannot be
selected or promoted until runtime/provider contracts are implemented.

Runnable controls also declare an enforcement policy. `promotable` controls
may move from advisory to enforced after validation. `advisory-only` controls
cannot; all AI review controls are advisory-only so an AI result cannot become
the sole merge gate.

## Promotion gate

Move a capability from advisory to enforced only after:

- the authoritative provider is configured and reliable;
- evidence is bound to the exact commit, artifact, or environment;
- the check name and failure behavior are stable;
- skipped and unavailable states become `NO RESULT` or an explicit failure,
  never success;
- a remediation owner exists; and
- the exact check context is added to the repository ruleset.

See [control setup](control-setup.md), [producer contract](producer-contract.md),
and [ruleset guidance](../../rulesets/README.md).
