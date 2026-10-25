# Real-client action-skill verification

The five action skills have seeded tasks and per-client `VERIFICATION.md`
ledgers. Verify a client through an actual invocation and revision-bound outcome
evidence. Do not infer execution from a copied `SKILL.md`, an installed fixture,
or a passing structural validator.

| Skill | Required demonstration |
| --- | --- |
| `fix-ci` | Fix the seeded implementation defect without weakening its test |
| `generate-unit-tests` | Cover success, rejection and boundary behavior; demonstrate that mutations fail |
| `fix-security-finding` | Remove the seeded shell-injection path; scanner clears and a mocked regression fails against the original |
| `dependency-upgrade` | Upgrade the affected manifest pin; verify installation, tests and synthetic advisory without changing unrelated pins |
| `address-pr-findings` | Resolve validation/cache findings; decide the naming finding explicitly and retain truthful verification states |

## Capture an actual invocation

1. Identify the toolkit source commit and the client version. Copy the seeded
   task to an isolated Git repository outside the toolkit checkout; install the
   named canonical skill for that client through the supported installer.
2. Commit the initial fixture. Invoke the client with the skill explicitly named
   and preserve the transcript identifying its read of that installed skill.
3. Apply the user's execution constraints. If local tests are excluded, tell the
   agent to change files only and defer test, scanner and dependency-installation
   execution to hosted CI. The agent must report those checks as pending.
4. Record the fixed fixture commit, patch, skill revision, client version, outcome
   report and file hashes. Review the diff for permitted scope and preservation
   of the original checks. Keep raw transcripts and private environment details
   outside published repository files.

## Verify behavior separately

Hosted CI can apply the captured patch to the exact seeded fixture, then run
the existing tests and task-specific negative controls. This verifies the
captured output; it does not independently attest which agent produced it.
Keep the actual invocation transcript as separate evidence of client use.

Before setting a ledger row to `yes`, require all of the skill's verification
criteria, the original failing control where relevant, the fixed passing result,
and negative controls that detect weakened tests or missing fixes. Record the
hosted run URL and exact tested source revision. A synthetic advisory scanner is
not evidence that a real Snyk or Dependabot finding has been resolved.

The Codex and Claude Code rows are independent. A Codex demonstration does not
verify Claude Code; leave an unavailable client's row `no` with an explicit
blocked or not-run outcome. Do not install a second client or provision its
credentials merely to make the table green.

The Unit Tests and standards-source templates fetch recorded source history
only when `tooling/validate-skills.py` exists after the initial checkout. This
lets the ledger validator compare recorded source commits; ordinary consumers
without that maintainer script retain shallow checkouts. Shipped and installed
workflow copies stay synchronized. Validator unit
tests create their own blank ledger rows for negative controls; production
verification records must not serve as mutable test inputs.

Each ledger links its skill-specific task and outcome criteria. The existing
validator checks ledger shape and source freshness; it cannot establish that
the transcript is authentic or that an agent performed the work. Changes to the
skill or seed invalidate prior verification. User permission and repository
policy remain separate from the verification result.
