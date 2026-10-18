from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("command_runner", Path(__file__).resolve().parents[1] / "run_repository_command.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CommandRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / ".proof").mkdir()
        self.config = self.root / ".proof/commands.json"
        self.environment = patch.dict(os.environ, {key: "" for key in [*MODULE.VARIABLES.values(), "PROOF_SETUP_COMMAND", "PROOF_WORKING_DIRECTORY"]})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write(self, **values):
        self.config.write_text(json.dumps({"version": 1, **values}))

    def invoke(self, *args):
        with patch.object(Path, "cwd", return_value=self.root), patch("sys.argv", ["runner", "--command", "build", *args]):
            return MODULE.main()

    def test_fork_without_vars_executes_setup_before_real_command(self):
        self.write(setup="printf setup > sequence", commands={"build": "printf build >> sequence"})
        self.assertEqual(self.invoke(), 0)
        self.assertEqual((self.root / "sequence").read_text(), "setupbuild")

    def test_environment_overrides_file_and_working_directory(self):
        (self.root / "package").mkdir()
        self.write(setup="exit 5", commands={"build": "exit 6"}, working_directory=".")
        with patch.dict(os.environ, PROOF_BUILD_COMMAND="printf override > result", PROOF_SETUP_COMMAND="true", PROOF_WORKING_DIRECTORY="package"):
            self.assertEqual(self.invoke(), 0)
        self.assertEqual((self.root / "package/result").read_text(), "override")

    def test_discovery_never_runs_commands_and_absence_is_false(self):
        with patch.object(MODULE.subprocess, "run") as run, patch("builtins.print") as output:
            self.assertEqual(self.invoke("--configured"), 0)
            output.assert_called_once_with("false")
            run.assert_not_called()
        self.write(setup="exit 10", commands={"build": "exit 11"})
        with patch.object(MODULE.subprocess, "run") as run, patch("builtins.print") as output:
            self.assertEqual(self.invoke("--configured"), 0)
            output.assert_called_once_with("true")
            run.assert_not_called()

    def test_missing_and_blank_commands_fail_without_running_setup(self):
        for command in (None, "", "  "):
            self.write(setup="touch unexpected", commands={} if command is None else {"build": command})
            with patch.object(MODULE.subprocess, "run") as run, patch("sys.stderr"):
                self.assertEqual(self.invoke(), 1)
                run.assert_not_called()

    def test_setup_and_producer_failures_propagate(self):
        self.write(setup="exit 7", commands={"build": "touch unexpected"})
        self.assertEqual(self.invoke(), 7)
        self.assertFalse((self.root / "unexpected").exists())
        self.write(commands={"build": "false | true"})
        self.assertEqual(self.invoke(), 1)
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], -15)):
            self.assertEqual(self.invoke(), 1)

    def test_rejects_invalid_configuration(self):
        for text in ("{}", "[]", "bad", '{"version":1.0}', '{"version":true}', '{"version":1,"unknown":1}', '{"version":1,"commands":[]}', '{"version":1,"commands":{"unknown":"true"}}', '{"version":1,"commands":{"build":42}}', '{"version":1,"setup":null}', "x" * (MODULE.MAX_BYTES + 1), ""):
            with self.subTest(text=text[:80]):
                self.config.write_text(text)
                with self.assertRaises(ValueError):
                    MODULE.configuration(self.root)

    def test_rejects_nonregular_or_symlink_configuration(self):
        self.config.symlink_to(self.root / "absent")
        with self.assertRaises(ValueError):
            MODULE.configuration(self.root)
        self.config.unlink()
        os.mkfifo(self.config)
        with self.assertRaises(ValueError):
            MODULE.configuration(self.root)
        self.config.unlink()
        (self.root / ".proof").rmdir()
        (self.root / ".proof").symlink_to(self.root / "absent")
        with self.assertRaises(ValueError):
            MODULE.configuration(self.root)

    def test_rejects_working_directory_escape_missing_absolute_and_symlink(self):
        (self.root / "escape").symlink_to(self.root.parent)
        for directory in ("../", str(self.root), "missing", "escape"):
            self.write(commands={"build": "true"}, working_directory=directory)
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                MODULE.selected(self.root, "build")

    def test_errors_do_not_log_commands(self):
        self.config.write_text("private command text")
        with patch("sys.stderr") as stderr:
            self.assertEqual(self.invoke(), 1)
            self.assertNotIn("private command", str(stderr.write.call_args_list))

    def test_installer_does_not_own_consumer_configuration(self):
        spec = importlib.util.spec_from_file_location("installer_for_commands", Path(__file__).resolve().parents[1] / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        self.assertNotIn(self.config, [item.destination for item in installer.runtime_sources(self.root)])

    def test_optional_coverage_producer_depends_on_discovery(self):
        text = (Path(__file__).resolve().parents[2] / "workflows/changed-code-coverage.yml").read_text()
        self.assertIn("needs: configuration", text)
        self.assertIn("if: ${{ needs.configuration.outputs.configured == 'true' }}", text)
        self.assertIn("--command changed-code-coverage --configured", text)
        self.assertNotIn("pull_request_target", text)

    def test_rejects_configuration_that_grows_after_stat(self):
        self.config.write_text('{"version":1}' + " " * MODULE.MAX_BYTES)
        info = self.config.stat()
        small = os.stat_result((*info[:6], 12, *info[7:]))
        with patch.object(MODULE.os, "fstat", return_value=small):
            with self.assertRaisesRegex(ValueError, "grew beyond"):
                MODULE.configuration(self.root)

    def test_setup_configuration_is_not_inherited_by_producer(self):
        self.write(commands={"build": 'test -z "${PROOF_SETUP_COMMAND+x}" && test -f setup-ran'})
        with patch.dict(os.environ, PROOF_SETUP_COMMAND="touch setup-ran"):
            self.assertEqual(self.invoke(), 0)
        self.assertTrue((self.root / "setup-ran").is_file())

    def test_separate_phases_do_not_repeat_setup(self):
        self.write(setup="printf setup >> sequence", commands={"build": "printf producer >> sequence"})
        self.assertEqual(self.invoke("--phase", "setup"), 0)
        self.assertEqual((self.root / "sequence").read_text(), "setup")
        self.assertEqual(self.invoke("--phase", "producer"), 0)
        self.assertEqual((self.root / "sequence").read_text(), "setupproducer")

    def test_setup_phase_propagates_failure_without_running_producer(self):
        self.write(setup="exit 9", commands={"build": "touch unexpected"})
        self.assertEqual(self.invoke("--phase", "setup"), 9)
        self.assertFalse((self.root / "unexpected").exists())

    def test_producer_phase_uses_updated_environment_without_rerunning_setup(self):
        self.write(setup="exit 9", commands={"build": 'test "$SETUP_RESULT" = ready && test -z "${PROOF_SETUP_COMMAND+x}"'})
        with patch.dict(os.environ, SETUP_RESULT="ready", PROOF_SETUP_COMMAND="exit 10"):
            self.assertEqual(self.invoke("--phase", "producer"), 0)

    def test_workflows_keep_setup_environment_updates_in_separate_steps(self):
        root = Path(__file__).resolve().parents[2]
        for name in MODULE.VARIABLES:
            text = (root / "workflows" / f"{name}.yml").read_text()
            steps = text.split("      - name:")
            setup = next(step for step in steps if " --phase setup" in step)
            producer = next(step for step in steps if " --phase producer" in step)
            self.assertLess(steps.index(setup), steps.index(producer))
            self.assertIn("PROOF_SETUP_COMMAND:", setup)
            self.assertNotIn("PROOF_SETUP_COMMAND:", producer)
