from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "sync_workflow_templates.py"
SPEC = importlib.util.spec_from_file_location("sync_workflow_templates", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise AssertionError(f"cannot load module spec: {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

OLD, NEW = "a" * 40, "b" * 40


def workflow(checkout: str, extra: str = "", comment: str = "") -> str:
    return (f"name: Example\njobs:\n  build:\n    steps:\n      - uses: actions/checkout@{checkout}{comment}\n"
            f"      - uses: github/codeql-action/init@{checkout}\n{extra}")


class SyncWorkflowTemplatesTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "workflows").mkdir()
        (self.root / ".github" / "workflows").mkdir(parents=True)

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.write_text(text, encoding="utf-8")
        return path

    def run_main(self, *arguments: str) -> tuple[int, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(MODULE, "NOT_INSTALLED", frozenset({"bundle.yml"})):
            code = MODULE.main(["--root", str(self.root), *arguments])
        return code, stderr.getvalue()

    def test_matching_templates_pass(self) -> None:
        self.write("workflows/build.yml", workflow(NEW))
        self.write(".github/workflows/build.yml", workflow(NEW))
        self.assertEqual(self.run_main(), (0, ""))

    def test_dependabot_pin_bump_is_detected_and_copied_into_templates(self) -> None:
        template = self.write("workflows/build.yml", workflow(OLD))
        self.write(".github/workflows/build.yml", workflow(NEW, comment=" # v7.0.1"))
        uninstalled = self.write("workflows/bundle.yml",
                                 workflow(OLD, "      - uses: github/codeql-action/autobuild@" + OLD + " # v3\n"))
        code, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn(".github/workflows/build.yml: differs from workflows/build.yml", stderr)
        self.assertIn("actions/checkout: pinned to 2 different SHAs", stderr)
        self.assertEqual(self.run_main("--write"), (0, ""))
        self.assertEqual(template.read_text(encoding="utf-8"), workflow(NEW, comment=" # v7.0.1"))
        bundle = uninstalled.read_text(encoding="utf-8")
        self.assertNotIn(OLD, bundle)
        # Sub-actions of one repository move together, with the installed version comment.
        self.assertIn(f"github/codeql-action/autobuild@{NEW}\n", bundle)
        self.assertIn(f"actions/checkout@{NEW} # v7.0.1", bundle)

    def test_non_pin_differences_are_refused(self) -> None:
        template = self.write("workflows/build.yml", workflow(NEW))
        self.write(".github/workflows/build.yml", workflow(NEW, "      - run: echo local change\n"))
        code, stderr = self.run_main("--write")
        self.assertEqual(code, 1)
        self.assertIn("differs beyond action pins", stderr)
        self.assertEqual(template.read_text(encoding="utf-8"), workflow(NEW))

    def test_missing_installed_copy_is_drift(self) -> None:
        self.write("workflows/build.yml", workflow(NEW))
        code, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn(".github/workflows/build.yml: expected copy of workflows/build.yml is missing", stderr)
        self.write(".github/workflows/bundle.yml", workflow(NEW))
        self.write("workflows/bundle.yml", workflow(NEW))
        self.write(".github/workflows/build.yml", workflow(NEW))
        code, stderr = self.run_main()
        self.assertIn("listed as not installed but .github/workflows/bundle.yml exists", stderr)

    def test_demo_copies_are_checked_and_repinned(self) -> None:
        (self.root / "tooling").mkdir()
        self.write("tooling/install.py", 'CORE_WORKFLOWS = {"build.yml": None}\nGITHUB_WORKFLOWS = {"codeql.yml": None}\n')
        self.write("workflows/codeql.yml", workflow(NEW))
        self.write(".github/workflows/codeql.yml", workflow(NEW))
        self.write("workflows/build.yml", workflow(NEW))
        self.write(".github/workflows/build.yml", workflow(NEW))
        demo = self.root / "examples" / "python-demo" / ".github" / "workflows"
        demo.mkdir(parents=True)
        copy = self.write("examples/python-demo/.github/workflows/build.yml", workflow(OLD))
        code, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("examples/python-demo/.github/workflows/build.yml: differs from workflows/build.yml", stderr)
        # The installer lists codeql.yml for the demo, so its absence is drift, not success.
        self.assertIn("examples/python-demo/.github/workflows/codeql.yml: expected copy of workflows/codeql.yml is missing", stderr)
        self.write("examples/python-demo/.github/workflows/codeql.yml", workflow(NEW))
        self.assertEqual(self.run_main("--write"), (0, ""))
        self.assertEqual(copy.read_text(encoding="utf-8"), workflow(NEW))

    def test_unpinned_remote_actions_are_reported(self) -> None:
        self.write("workflows/bundle.yml", workflow(NEW, "      - uses: actions/setup-python@v6\n"
                                                        f"      - uses: actions/cache@{NEW}-tag\n"
                                                        "      - uses: ./local-action\n"
                                                        "      - uses: 'docker://alpine:3'\n"))
        code, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("workflows/bundle.yml: actions/setup-python@v6 is not pinned to a full commit SHA", stderr)
        self.assertIn(f"workflows/bundle.yml: actions/cache@{NEW}-tag is not pinned to a full commit SHA", stderr)
        self.assertNotIn("local-action", stderr)
        self.assertNotIn("docker://", stderr)

    def test_quoted_references_group_and_repin_like_plain_ones(self) -> None:
        self.write("workflows/build.yml", workflow(NEW, comment=" # v7.0.1"))
        self.write(".github/workflows/build.yml", workflow(NEW, comment=" # v7.0.1"))
        bundle = self.write("workflows/bundle.yml", f"jobs:\n  a:\n    steps:\n      - uses: 'actions/checkout@{OLD}'\n"
                                                    f'      - uses: "github/codeql-action/init@{OLD}" # v3\n')
        code, stderr = self.run_main()
        self.assertIn("actions/checkout: pinned to 2 different SHAs", stderr)
        self.assertEqual(self.run_main("--write"), (0, ""))
        self.assertEqual(bundle.read_text(encoding="utf-8"),
                         f"jobs:\n  a:\n    steps:\n      - uses: 'actions/checkout@{NEW}' # v7.0.1\n"
                         f'      - uses: "github/codeql-action/init@{NEW}"\n')

    def test_yaml_suffix_and_flow_style_references_are_checked(self) -> None:
        self.write("workflows/build.yml", workflow(NEW))
        self.write(".github/workflows/build.yml", workflow(NEW))
        self.write("workflows/lint.yaml", f"jobs:\n  a:\n    steps:\n      - {{ uses: actions/checkout@v7 }}\n")
        self.write(".github/workflows/lint.yaml", f"jobs:\n  a:\n    steps:\n      - {{ uses: actions/checkout@v7 }}\n")
        code, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("workflows/lint.yaml: actions/checkout@v7 is not pinned to a full commit SHA", stderr)
        self.write("workflows/lint.yaml", f"jobs:\n  a:\n    steps:\n      - {{ uses: actions/checkout@{OLD}, with: {{ depth: 1 }} }}\n")
        installed = self.write(".github/workflows/lint.yaml",
                               f"jobs:\n  a:\n    steps:\n      - {{ uses: actions/checkout@{NEW}, with: {{ depth: 1 }} }}\n")
        code, stderr = self.run_main()
        self.assertIn(".github/workflows/lint.yaml: differs from workflows/lint.yaml", stderr)
        self.assertEqual(self.run_main("--write"), (0, ""))
        self.assertEqual((self.root / "workflows" / "lint.yaml").read_text(encoding="utf-8"), installed.read_text(encoding="utf-8"))

    def test_multiline_uses_values_are_parsed(self) -> None:
        text = "jobs:\n  a:\n    steps:\n      - uses:\n          actions/checkout@v7\n"
        self.write("workflows/lint.yml", text)
        self.write(".github/workflows/lint.yml", text)
        code, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("workflows/lint.yml: actions/checkout@v7 is not pinned to a full commit SHA", stderr)
        self.write("workflows/lint.yml", "jobs: [unclosed\n")
        code, stderr = self.run_main()
        self.assertIn("is not valid YAML", stderr)

    def test_symlinked_workflows_are_refused_before_any_write(self) -> None:
        outside = self.root / "outside.yml"
        outside.write_text(workflow(OLD), encoding="utf-8")
        (self.root / "workflows" / "build.yml").symlink_to(outside)
        self.write(".github/workflows/build.yml", workflow(NEW))
        code, stderr = self.run_main("--write")
        self.assertEqual(code, 1)
        self.assertIn("workflows/build.yml: is or sits under a symlink; refusing to write", stderr)
        self.assertEqual(outside.read_text(encoding="utf-8"), workflow(OLD))

    def test_multiline_and_unrelated_uses_keys(self) -> None:
        template = self.write("workflows/lint.yml",
                              f"jobs:\n  a:\n    steps:\n      - uses:\n          actions/checkout@{OLD}\n"
                              f"        with: {{ uses: feature }}\n        env:\n          uses: anything\n")
        self.write(".github/workflows/lint.yml",
                   f"jobs:\n  a:\n    steps:\n      - uses:\n          actions/checkout@{NEW}\n"
                   f"        with: {{ uses: feature }}\n        env:\n          uses: anything\n")
        code, stderr = self.run_main()
        # Inputs and env entries named `uses` are not actions; only the stale pin is drift.
        self.assertNotIn("feature", stderr)
        self.assertNotIn("anything", stderr)
        self.assertIn(".github/workflows/lint.yml: differs from workflows/lint.yml", stderr)
        self.assertEqual(self.run_main("--write"), (0, ""))
        self.assertIn(f"actions/checkout@{NEW}\n", template.read_text(encoding="utf-8"))

    def test_aliased_steps_are_rewritten_once_and_renames_are_refused(self) -> None:
        def aliased(sha: str, job: str) -> str:
            return (f"jobs:\n  a:\n    steps:\n      - &checkout\n        uses: actions/checkout@{sha}\n"
                    f"  {job}:\n    steps:\n      - *checkout\n  c:\n    steps:\n      - *checkout\n")
        self.assertTrue(MODULE.pin_only_difference(aliased(OLD, "build"), aliased(NEW, "build")))
        self.assertFalse(MODULE.pin_only_difference(aliased(OLD, "build"), aliased(NEW, "evilx")))
        chosen = {"actions/checkout": (NEW, "# v7")}
        self.assertEqual(MODULE.repin(aliased(OLD, "build"), chosen),
                         aliased(NEW, "build").replace(f"@{NEW}\n", f"@{NEW} # v7\n", 1))

    def test_reusable_workflow_job_uses_is_checked(self) -> None:
        text = "jobs:\n  call:\n    uses: org/repo/.github/workflows/x.yml@main\n"
        self.write("workflows/call.yml", text)
        self.write(".github/workflows/call.yml", text)
        code, stderr = self.run_main()
        self.assertIn("org/repo/.github/workflows/x.yml@main is not pinned to a full commit SHA", stderr)

    def test_pin_only_difference_requires_the_same_action(self) -> None:
        self.assertTrue(MODULE.pin_only_difference(workflow(OLD), workflow(NEW)))
        self.assertFalse(MODULE.pin_only_difference(workflow(OLD), workflow(OLD).replace("actions/checkout", "evil/checkout")))
        self.assertFalse(MODULE.pin_only_difference(workflow(OLD), workflow(OLD) + "x\n"))


class RepositoryWorkflowDriftTests(unittest.TestCase):
    def test_repository_runs_the_templates_it_ships(self) -> None:
        # After a Dependabot pin bump, run: python3 tooling/sync_workflow_templates.py --write
        self.assertEqual(MODULE.drift(ROOT), [])


if __name__ == "__main__":
    unittest.main()
