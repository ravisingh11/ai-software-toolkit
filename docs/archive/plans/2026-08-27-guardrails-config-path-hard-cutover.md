# Guardrails Configuration Path Hard Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every Guardrails-owned repository configuration file from `.ai/` to `.guardrails/`, reject ambiguous legacy installations before writing, and leave the local scanner, GitHub workflows, composite action, embedded demo, and documentation working from one canonical path contract.

**Architecture:** Keep reusable implementation, schemas, and baseline data under non-dot `guardrails/`, keep consumer-installed runtime and repository-selected configuration under `.guardrails/`, and reserve `.ai/` for genuinely AI-owned files. The installer performs a preflight rejection for the five retired paths, then uses its existing overwrite protections. Runtime code has no legacy fallback. Distribution tests enforce that legacy path strings remain only in installer rejection code, focused installer tests, and the approved design record.

**Tech Stack:** Python 3 standard library, JSON-compatible YAML, GitHub Actions YAML, composite GitHub Action metadata, Markdown, `unittest`.

**Spec:** [Guardrails Configuration Path Hard Cutover](../specs/2026-08-27-guardrails-config-path-hard-cutover-design.md)

## Global Constraints

- Preserve control IDs, status-context names, evidence schemas, decision behavior, and advisory/enforced semantics.
- Do not read, copy, delete, or silently migrate the five retired `.ai/` configuration files.
- Reject all five retired paths before writes in normal, dry-run, merge-existing, and refresh-existing modes.
- Do not reject unrelated `.ai/` files.
- Keep repository-specific ground truth in each repository; shared defaults may provide only a starter inventory, never application facts.
- Keep `guardrails/` as source/distribution code and `.guardrails/` as installed runtime/configuration.
- Use JSON-compatible YAML for every `.yaml` file added or moved.
- Keep duplicated installed runtime files byte-for-byte aligned with their canonical tooling sources.
- Make each commit independently testable and reviewable.

---

## Task 1: Lock and implement the installer path contract

**Files:**

- Modify: `tooling/tests/test_install.py`
- Modify: `tooling/install.py`
- Create: `guardrails/defaults/documentation.yaml`
- Create: `guardrails/defaults/change-scope.yaml`
- Create: `guardrails/defaults/ground-truth-ai.yaml`

- [ ] **Step 1: Add failing fresh-install assertions**

  Update `test_dry_run_does_not_write`, `test_installs_small_core`, and optional workflow/provider plan-length assertions so a fresh installation expects these five configuration destinations:

  ```python
  expected_configuration = {
      Path(".guardrails/policy.yaml"),
      Path(".guardrails/control-catalog.yaml"),
      Path(".guardrails/documentation.yaml"),
      Path(".guardrails/change-scope.yaml"),
      Path(".guardrails/ground-truth-ai.yaml"),
  }
  self.assertTrue(
      expected_configuration <= {
          item.destination.relative_to(target) for item in plan
      }
  )
  self.assertFalse((target / ".ai").exists())
  ```

  Assert the three starter configurations parse with `json.loads`. Assert the installed policy and catalog equal their existing distribution sources.

- [ ] **Step 2: Add failing legacy-preflight tests**

  Add one subtest per mapping and one subtest per installer mode:

  ```python
  legacy_paths = {
      ".ai/guardrails.yaml": ".guardrails/policy.yaml",
      ".ai/control-catalog.yaml": ".guardrails/control-catalog.yaml",
      ".ai/documentation.yaml": ".guardrails/documentation.yaml",
      ".ai/change-scope.yaml": ".guardrails/change-scope.yaml",
      ".ai/ground-truth.yaml": ".guardrails/ground-truth-ai.yaml",
  }
  ```

  Each test must prove:

  - `install(...)` raises `ValueError` containing every detected old-to-new mapping and a `git mv` instruction;
  - no `.guardrails/` product file was written;
  - detection still runs with `dry_run=True`, `merge_existing=True`, and `refresh_existing=True`;
  - multiple legacy files are reported in one error;
  - `.ai/application-config.yaml` alone does not block installation.

- [ ] **Step 3: Run the focused tests and confirm the expected failure**

  Run:

  ```sh
  python3 -m unittest tooling.tests.test_install -v
  ```

  Expected: failures show the installer still targets `.ai/`, installs only the old plan size, and does not reject the five legacy paths.

- [ ] **Step 4: Add reusable starter configuration sources**

  Add `guardrails/defaults/` files with these contracts:

  - `documentation.yaml`: version 1, a conservative `application-code` mapping from `src/**`, `app/**`, and `lib/**` to `README.md`; consumers customize mappings for their repository.
  - `change-scope.yaml`: version 1 and the existing advisory thresholds (`12` files, `300` added lines, `500` changed lines, `150` added lines per file) plus the existing generated/vendor/document exclusions.
  - `ground-truth-ai.yaml`: version 1 and a starter inventory containing only `README.md`; consumers explicitly add architecture, standards, testing, security, deployment, and contribution documents that actually exist.

  These are installation defaults, not claims about a consuming application.

- [ ] **Step 5: Implement the installer destinations and preflight**

  Add source constants and an ordered legacy mapping:

  ```python
  DOCUMENTATION_POLICY = ROOT / "guardrails" / "defaults" / "documentation.yaml"
  CHANGE_SCOPE_POLICY = ROOT / "guardrails" / "defaults" / "change-scope.yaml"
  GROUND_TRUTH_POLICY = ROOT / "guardrails" / "defaults" / "ground-truth-ai.yaml"

  LEGACY_CONFIG_PATHS = {
      Path(".ai/guardrails.yaml"): Path(".guardrails/policy.yaml"),
      Path(".ai/control-catalog.yaml"): Path(".guardrails/control-catalog.yaml"),
      Path(".ai/documentation.yaml"): Path(".guardrails/documentation.yaml"),
      Path(".ai/change-scope.yaml"): Path(".guardrails/change-scope.yaml"),
      Path(".ai/ground-truth.yaml"): Path(".guardrails/ground-truth-ai.yaml"),
  }
  ```

  Implement `reject_legacy_configuration(target)` and call it immediately after target-directory validation, before `build_plan`. Treat a file, symlink, or directory at an exact retired path as an unresolved conflict. Build one deterministic message listing every conflict as:

  ```text
  legacy Guardrails configuration must be moved before installation:
  - git mv .ai/guardrails.yaml .guardrails/policy.yaml
  ```

  Change `build_plan` to install all five canonical configuration files. During `--refresh-existing`, preserve an existing `.guardrails/policy.yaml`, `.guardrails/documentation.yaml`, `.guardrails/change-scope.yaml`, and `.guardrails/ground-truth-ai.yaml`; continue preserving the catalog/provider/manifest/workflow according to their existing ownership rules. Do not add these five paths to cleanup or migration logic.

- [ ] **Step 6: Run the installer tests**

  Run:

  ```sh
  python3 -m unittest tooling.tests.test_install -v
  ```

  Expected: all installer tests pass; a fresh target gets five canonical config files and no `.ai/` directory.

- [ ] **Step 7: Commit Task 1**

  ```sh
  git add tooling/install.py tooling/tests/test_install.py guardrails/defaults
  git commit -m "fix(installer): enforce guardrails config cutover"
  ```

---

## Task 2: Move repository configuration and update Python defaults

**Files:**

- Move: `.ai/guardrails.yaml` → `.guardrails/policy.yaml`
- Move: `.ai/control-catalog.yaml` → `.guardrails/control-catalog.yaml`
- Move: `.ai/documentation.yaml` → `.guardrails/documentation.yaml`
- Move: `.ai/change-scope.yaml` → `.guardrails/change-scope.yaml`
- Move: `.ai/ground-truth.yaml` → `.guardrails/ground-truth-ai.yaml`
- Modify: `tooling/configure_guardrails.py`
- Modify: `tooling/scan_repository.py`
- Modify: `tooling/attest_staged_change.py`
- Modify: `tooling/validators/validate_documentation.py`
- Modify: `tooling/validators/inspect_change_scope.py`
- Modify: `tooling/validators/validate_ground_truth.py`
- Modify: `.guardrails/configure.py`
- Modify: `.guardrails/scan.py`
- Modify: `.guardrails/validate_ground_truth.py`
- Modify: `tooling/tests/test_configure_guardrails.py`
- Modify: `tooling/tests/test_scan_repository.py`
- Modify: `tooling/tests/test_staged_attestation.py`
- Modify: `tooling/validators/tests/test_validate_documentation.py`
- Modify: `tooling/validators/tests/test_inspect_change_scope.py`
- Create: `tooling/validators/tests/test_validate_ground_truth.py`

- [ ] **Step 1: Add failing canonical-default tests**

  Update existing tests to assert:

  ```python
  MODULE.DEFAULT_POLICY == MODULE.ROOT / ".guardrails" / "documentation.yaml"
  SCOPE.DEFAULT_POLICY == SCOPE.ROOT / ".guardrails" / "change-scope.yaml"
  ```

  Update scanner tests to expect `.guardrails/policy.yaml` and `.guardrails/control-catalog.yaml`, with fallback only to `guardrails/baseline.yaml` and `policies/control-catalog.yaml` for an uninstalled standards source checkout.

  Update staged-attestation tests so the staged snapshot loads:

  ```text
  .guardrails/policy.yaml
  .guardrails/change-scope.yaml
  ```

  Add focused ground-truth validator subprocess tests for:

  - a valid inventory;
  - a missing declared document;
  - malformed JSON-compatible YAML;
  - an unreadable/missing policy path;
  - the default path `.guardrails/ground-truth-ai.yaml`.

- [ ] **Step 2: Run focused tests and confirm old defaults fail**

  ```sh
  python3 -m unittest \
    tooling.tests.test_configure_guardrails \
    tooling.tests.test_scan_repository \
    tooling.tests.test_staged_attestation \
    tooling.validators.tests.test_validate_documentation \
    tooling.validators.tests.test_inspect_change_scope \
    tooling.validators.tests.test_validate_ground_truth -v
  ```

  Expected: path assertions fail because code still resolves `.ai/`.

- [ ] **Step 3: Move the canonical files without changing their policy content**

  Preserve JSON payloads. Keep the shared repository policy schema reference as `../guardrails/policy.schema.json`, which remains correct from `.guardrails/policy.yaml`. Remove `.ai/` only when empty.

- [ ] **Step 4: Update canonical tooling defaults**

  Use these exact defaults everywhere:

  ```text
  policy:        .guardrails/policy.yaml
  catalog:       .guardrails/control-catalog.yaml
  documentation: .guardrails/documentation.yaml
  change scope:  .guardrails/change-scope.yaml
  ground truth:  .guardrails/ground-truth-ai.yaml
  ```

  Update `tooling/scan_repository.py` fallback calls without adding legacy probing. Update `tooling/attest_staged_change.py` snapshot lookups. Update validator `DEFAULT_POLICY` constants and ground-truth CLI default.

- [ ] **Step 5: Synchronize installed runtime copies**

  Make these pairs byte-for-byte equal after updating canonical sources:

  ```text
  tooling/configure_guardrails.py             .guardrails/configure.py
  tooling/scan_repository.py                  .guardrails/scan.py
  tooling/validators/validate_ground_truth.py .guardrails/validate_ground_truth.py
  ```

  Do not add a fallback to the retired names.

- [ ] **Step 6: Run focused tests and direct commands**

  ```sh
  python3 -m unittest \
    tooling.tests.test_configure_guardrails \
    tooling.tests.test_scan_repository \
    tooling.tests.test_staged_attestation \
    tooling.validators.tests.test_validate_documentation \
    tooling.validators.tests.test_inspect_change_scope \
    tooling.validators.tests.test_validate_ground_truth -v
  python3 tooling/validators/validate_ground_truth.py
  python3 tooling/validators/validate_documentation.py
  python3 tooling/validators/inspect_change_scope.py --output /tmp/guardrails-scope.json
  python3 tooling/scan_repository.py --all-catalog-controls
  ```

  Expected: tests and validators pass; the local scan reads only `.guardrails/` configuration and writes its normal timestamped report.

- [ ] **Step 7: Commit Task 2**

  ```sh
  git add .ai .guardrails tooling
  git commit -m "refactor(config): move guardrails policy out of ai"
  ```

---

## Task 3: Cut over the composite action and GitHub workflows

**Files:**

- Modify: `action.yml`
- Modify: `.github/workflows/validate.yml`
- Modify: `.github/workflows/guardrail-checks.yml`
- Modify: `.github/workflows/guardrails-attestation.yml`
- Modify: `.github/workflows/dependabot-verification.yml`
- Modify: `docs/examples/guardrails.yml`
- Modify: `tooling/tests/test_action_distribution.py`

- [ ] **Step 1: Add failing distribution contract assertions**

  Extend `test_action_distribution.py` to assert:

  - `action.yml` defaults `policy-file` to `.guardrails/policy.yaml` and its missing-policy error names that path;
  - validation uses `.guardrails/ground-truth-ai.yaml`;
  - scorecard workflows use `.guardrails/policy.yaml` and `.guardrails/control-catalog.yaml`;
  - repository workflow defaults for documentation and scope resolve their `.guardrails/` files;
  - installed runtime copies equal canonical sources for configurator, scanner, GitHub evidence collector, and ground-truth validator.

  Add a repository-wide active-reference test. Scan tracked `.py`, `.yml`, `.yaml`, and `.md` files while excluding:

  ```text
  tooling/install.py
  tooling/tests/test_install.py
  docs/superpowers/specs/
  docs/superpowers/plans/
  ```

  Fail if any remaining file contains one of the five retired path strings.

- [ ] **Step 2: Run the distribution tests and confirm failures**

  ```sh
  python3 -m unittest tooling.tests.test_action_distribution -v
  ```

  Expected: failures identify every action/workflow still passing `.ai/` paths.

- [ ] **Step 3: Update the action and workflow commands**

  Change the composite action default and error copy to `.guardrails/policy.yaml`. Update every explicit workflow argument to the five canonical paths. Preserve workflow names, job names, permissions, pinned action SHAs, revision selection, evidence destinations, and PR-comment behavior.

- [ ] **Step 4: Run distribution and YAML syntax checks**

  ```sh
  python3 -m unittest tooling.tests.test_action_distribution -v
  ruby -e 'require "yaml"; Dir["{.github/workflows,workflows,docs/examples}/**/*.{yml,yaml}"].each { |f| YAML.safe_load_file(f, aliases: true) }'
  ```

  Expected: distribution tests pass and all workflow/template YAML parses.

- [ ] **Step 5: Commit Task 3**

  ```sh
  git add action.yml .github/workflows docs/examples/guardrails.yml tooling/tests/test_action_distribution.py
  git commit -m "ci(guardrails): use canonical configuration paths"
  ```

---

## Task 4: Reinstall and validate the embedded Python demo

**Files:**

- Move: `examples/python-demo/.ai/guardrails.yaml` → `examples/python-demo/.guardrails/policy.yaml`
- Move: `examples/python-demo/.ai/control-catalog.yaml` → `examples/python-demo/.guardrails/control-catalog.yaml`
- Move: `examples/python-demo/.ai/ground-truth.yaml` → `examples/python-demo/.guardrails/ground-truth-ai.yaml`
- Create: `examples/python-demo/.guardrails/documentation.yaml`
- Create: `examples/python-demo/.guardrails/change-scope.yaml`
- Modify: `examples/python-demo/.guardrails/configure.py`
- Modify: `examples/python-demo/.guardrails/scan.py`
- Modify: `examples/python-demo/.guardrails/validate_ground_truth.py`
- Modify: `examples/python-demo/.github/workflows/validate.yml`
- Modify: `examples/python-demo/.github/workflows/guardrails-scorecard.yml`
- Modify: `examples/python-demo/.github/workflows/dependabot-verification.yml`
- Modify: `examples/python-demo/.agents/skills/prepare-safe-change/SKILL.md`
- Modify: `examples/python-demo/tools/validate_demo.py`
- Modify: `examples/python-demo/README.md`

- [ ] **Step 1: Strengthen the demo validator first**

  Change `validate_demo.py` to require and parse all five canonical files. Assert:

  - no `examples/python-demo/.ai/` directory exists;
  - every selected control exists in `.guardrails/control-catalog.yaml`;
  - every ground-truth path exists;
  - runtime defaults contain canonical paths and no retired paths;
  - demo workflows invoke canonical paths.

- [ ] **Step 2: Run the demo validator and observe the expected failure**

  ```sh
  python3 examples/python-demo/tools/validate_demo.py --documentation
  ```

  Expected: missing canonical demo configuration and old workflow/runtime references are reported.

- [ ] **Step 3: Move demo configuration and install the two missing repository policies**

  Preserve the demo-specific policy, catalog, and seven-document ground-truth inventory. Add:

  - `.guardrails/documentation.yaml` with mappings from `app.py` and `test_app.py` to `README.md`, `ARCHITECTURE.md`, `STANDARDS.md`, and `TESTING.md` as appropriate;
  - `.guardrails/change-scope.yaml` using the shared starter thresholds.

  If the moved policy retains `$schema`, point it to the canonical public schema URL so the installed demo does not claim a nonexistent local schema.

- [ ] **Step 4: Refresh demo runtime, skills, and workflows**

  Copy the already-tested canonical runtime sources into the demo runtime copies, update demo workflow arguments, and update the installed skill text. Do not modify demo control IDs or check names.

- [ ] **Step 5: Run demo tests, validation, and scan**

  ```sh
  python3 -m unittest discover -s examples/python-demo -p 'test_*.py'
  python3 examples/python-demo/tools/validate_demo.py --documentation
  (
    cd examples/python-demo
    python3 .guardrails/scan.py --all-catalog-controls
  )
  ```

  Expected: application tests and demo validation pass; the scan prints a detailed scorecard and writes `.artifacts/guardrails/scorecard-<UTC timestamp>.md`.

- [ ] **Step 6: Commit Task 4**

  ```sh
  git add examples/python-demo
  git commit -m "test(demo): exercise canonical guardrails configuration"
  ```

---

## Task 5: Update skills and user documentation

**Files:**

- Modify: `README.md`
- Modify: `docs/quickstart.md`
- Modify: `docs/compliance.md`
- Modify: `docs/control-setup.md`
- Modify: `docs/producer-contract.md`
- Modify: `tooling/validators/README.md`
- Modify: `skills/prepare-safe-change/SKILL.md`
- Modify: `.agents/skills/prepare-safe-change/SKILL.md`
- Modify: any additional active Markdown file found by the legacy-reference test

- [ ] **Step 1: Write one canonical directory explanation**

  Add one concise section to `README.md` or `docs/compliance.md`:

  ```text
  guardrails/   Shared source: evaluator, schemas, baseline, and tests.
  .guardrails/  Repository installation: selected policy, control catalog,
                repository validation policies, provider configuration,
                producer manifest, and runtime commands.
  .ai/          Reserved for configuration owned by AI features, not Guardrails.
  ```

  Link other documents to this section instead of repeating a long explanation.

- [ ] **Step 2: Update install, configure, scan, refresh, and migration guidance**

  Replace all five retired paths in commands and prose. Document the hard-cutover failure before the refresh command:

  ```sh
  mkdir -p .guardrails
  git mv .ai/guardrails.yaml .guardrails/policy.yaml
  git mv .ai/control-catalog.yaml .guardrails/control-catalog.yaml
  git mv .ai/documentation.yaml .guardrails/documentation.yaml
  git mv .ai/change-scope.yaml .guardrails/change-scope.yaml
  git mv .ai/ground-truth.yaml .guardrails/ground-truth-ai.yaml
  ```

  State that users should run only the commands for files they actually have, review relative schema paths, then rerun installer `--dry-run`. Do not imply automatic migration or deletion.

- [ ] **Step 3: Update source and installed skill guidance**

  Change the prepare-safe-change skill to read `.guardrails/policy.yaml`. Keep source and checked-in installed copies byte-for-byte equal. Do not move the skill itself; `.agents/` remains the correct agent capability location.

- [ ] **Step 4: Validate documentation and skill packaging**

  ```sh
  python3 tooling/validators/validate_documentation.py
  python3 tooling/validate-skills.py
  python3 -m unittest tooling.tests.test_action_distribution -v
  ```

  Expected: Markdown links pass, skills validate, and the active legacy-reference assertion passes.

- [ ] **Step 5: Commit Task 5**

  ```sh
  git add README.md docs tooling/validators/README.md skills/prepare-safe-change .agents/skills/prepare-safe-change
  git commit -m "docs(guardrails): document canonical config layout"
  ```

---

## Task 6: Run the full release-quality verification

**Files:**

- Verify only; modify the smallest relevant file if a check exposes a defect.

- [ ] **Step 1: Confirm the retired directory is gone from active repositories**

  ```sh
  test ! -d .ai
  test ! -d examples/python-demo/.ai
  rg --hidden -n "\.ai/(guardrails|control-catalog|documentation|change-scope|ground-truth)\.yaml" \
    --glob '!.git/**' \
    --glob '!docs/superpowers/specs/**' \
    --glob '!docs/superpowers/plans/**' \
    --glob '!tooling/install.py' \
    --glob '!tooling/tests/test_install.py' \
    .
  ```

  Expected: `test` succeeds and `rg` exits `1` with no active matches.

- [ ] **Step 2: Validate JSON-compatible YAML**

  ```sh
  python3 - <<'PY'
  import json
  from pathlib import Path

  for root in (Path('.guardrails'), Path('guardrails/defaults'), Path('examples/python-demo/.guardrails')):
      for path in sorted(root.glob('*.yaml')):
          json.loads(path.read_text(encoding='utf-8'))
          print(path)
  PY
  ```

  Expected: every configuration path prints and no parse exception occurs.

- [ ] **Step 3: Run every repository test and validator required by `AGENTS.md`**

  ```sh
  python3 -m unittest discover -s guardrails/tests -p 'test_*.py'
  python3 -m unittest discover -s tooling/tests -p 'test_*.py'
  python3 -m unittest discover -s tooling/validators/tests -p 'test_*.py'
  python3 -m unittest discover -s examples/python-demo -p 'test_*.py'
  python3 examples/python-demo/tools/validate_demo.py --documentation
  python3 tooling/validate-skills.py
  python3 tooling/validators/validate_repository.py
  python3 tooling/validators/validate_documentation.py
  git diff --check
  ```

  Expected: every command exits `0`.

- [ ] **Step 4: Exercise a clean consumer installation**

  ```sh
  consumer_dir="$(mktemp -d)"
  printf '# Consumer\n' > "$consumer_dir/README.md"
  python3 tooling/install.py --target "$consumer_dir" --github-actions
  python3 "$consumer_dir/.guardrails/scan.py" \
    --target "$consumer_dir" \
    --all-catalog-controls
  find "$consumer_dir/.guardrails" -maxdepth 1 -type f -print | sort
  test ! -d "$consumer_dir/.ai"
  ```

  Expected: installation and local scan complete, five canonical configuration files are present, and no `.ai/` directory is created.

- [ ] **Step 5: Review the final diff against the approved spec**

  Confirm:

  - all seven verification requirements in the spec have evidence;
  - only installer rejection code and focused tests contain retired path strings outside historical design/plan records;
  - no control IDs, status contexts, or evidence semantics changed;
  - no credentials, generated scorecards, or `.artifacts/` files are staged;
  - commits remain focused and the pull request description includes the manual `git mv` migration map.

- [ ] **Step 6: Commit any verification-only correction, then push the branch**

  If verification required a correction, stage only the files changed by that
  correction and commit them with
  `test(guardrails): close config cutover gaps`.

  Then:

  ```sh
  git status --short
  git log --oneline --decorate -6
  git push
  ```

  Stop when the branch is clean, the full verification suite passes, and the existing pull request contains the complete hard-cutover implementation.
