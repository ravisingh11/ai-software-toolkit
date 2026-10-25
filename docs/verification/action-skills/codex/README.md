# Captured Codex action-skill demonstrations

Five real Codex CLI 0.163.0 runs used installed project skills from toolkit
revision `984f34aecfb1aa57b96fb3b2823d79d5b06717dd`. Each worked in a separate
seeded Git repository and explicitly read its installed `SKILL.md`. The user
excluded local tests: agents edited files and reported verification pending.
Raw command transcripts were reviewed for that boundary; no local tests,
scanners, application execution or dependency installation ran.

[Capture metadata](captures.json) records source/client identity, initial and
fixed fixture commits, patch hashes and raw transcript hashes. Raw transcripts
and fixture Git bundles remain with the maintainer because they include private
environment paths. The sanitized patches below reproduce the captured outputs
against `tooling/tests/fixtures/skills/<name>/` at the recorded source revision.
Patches are stored as JSON line arrays so context-only blank lines retain their
exact bytes without requiring whitespace exceptions. Join `lines` without a
separator to recover the unified diff; its SHA-256 is the recorded patch hash.

| Skill | Captured output | Hosted verification |
| --- | --- | --- |
| fix-ci | [Patch](fix-ci.patch.json) | Task-specific checks passed; see evidence below |
| generate-unit-tests | [Patch](generate-unit-tests.patch.json) | Task-specific checks passed; see evidence below |
| fix-security-finding | [Patch](fix-security-finding.patch.json) | Task-specific checks passed; see evidence below |
| dependency-upgrade | [Patch](dependency-upgrade.patch.json) | Task-specific checks passed; see evidence below |
| address-pr-findings | [Patch](address-pr-findings.patch.json) | Task-specific checks passed; see evidence below |

The existing Unit Tests workflow runs
`tooling/tests/test_action_skill_demonstrations.py` in hosted CI. It applies each
patch to its original seed, preserves existing tests, checks the fixed behavior,
and rejects original implementations or behavior mutations. Dependency
installation uses an isolated hosted virtual environment. The advisory/scanner
fixtures are synthetic; they do not establish real Snyk or Dependabot results.

The Codex ledger rows record passing seeded-task demonstrations; their scope is
the recorded client, skill bytes and isolated fixture, not every possible task. CI verifies the captured code and tests; the private transcript is
separate evidence of the actual client invocation, not native provenance or an
independent attestation of agent identity. Claude Code was not selected for this
verification and remains unverified. No provider, lifecycle or polyglot workflow
was enabled or dispatched.

## Hosted outcome evidence

All five task-specific checks passed in [run 40153999901](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/40153999901), source
`6a4d899097d6fd7bb99d545f7c5693a556616153`. The earlier
[run 40152952529](https://github.com/ravisingh11/ai-software-toolkit/actions/runs/40152952529) also passed those five cases.
These overall jobs failed elsewhere: the first exposed validator test fixtures
that assumed blank ledgers; the second exposed unsynchronized workflow copies.
Those failures remain part of the history. This PR fixes the fixtures and keeps
templates synchronized; its [current CI checks](https://github.com/ravisingh11/ai-software-toolkit/pull/156/checks) are separate from the recorded per-task outcomes.

Codex finalized the security/dependency reports and finding statuses using the
observed hosted results, without local execution or changes to the verified
implementation/test bytes. Capture metadata retains both initial and finalized
fixture identities and transcript hashes. The findings command is the actual
hosted fixture command, not an untrusted suggested command. The final hosted
checks reapply and verify the complete finalized patches, including metadata.

No changed-line coverage producer or threshold is configured in these isolated
seed repositories; fixture coverage is unavailable and is not reported as passed.
The dependency audit is the named synthetic originating check, plus pip
installation/consistency and the existing tests. A real external provider audit
was not configured and remains unavailable.
