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
| fix-ci | [Patch](fix-ci.patch.json) | Pending |
| generate-unit-tests | [Patch](generate-unit-tests.patch.json) | Pending |
| fix-security-finding | [Patch](fix-security-finding.patch.json) | Pending |
| dependency-upgrade | [Patch](dependency-upgrade.patch.json) | Pending |
| address-pr-findings | [Patch](address-pr-findings.patch.json) | Pending |

The existing Unit Tests workflow runs
`tooling/tests/test_action_skill_demonstrations.py` in hosted CI. It applies each
patch to its original seed, preserves existing tests, checks the fixed behavior,
and rejects original implementations or behavior mutations. Dependency
installation uses an isolated hosted virtual environment. The advisory/scanner
fixtures are synthetic; they do not establish real Snyk or Dependabot results.

No client is marked verified until those checks and the skill-specific criteria
have passed. CI verifies the captured code and tests; the private transcript is
separate evidence of the actual client invocation, not native provenance or an
independent attestation of agent identity. Claude Code was not selected for this
verification and remains unverified. No provider, lifecycle or polyglot workflow
was enabled or dispatched.
