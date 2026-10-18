from __future__ import annotations

import importlib.util
import os
import yaml
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("fetch_metadata", Path(__file__).resolve().parents[1] / "fetch_pr_metadata.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        (self.repo / ".proof").mkdir()
        (self.repo / ".proof/policy.yaml").write_text('{"version":2}')
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD")

    def test_fetch_uses_authenticated_base_remote_without_checkout(self):
        commands = []
        original = MODULE.git

        def local_fetch(root, *args, env=None):
            commands.append((args, env))
            if args[0] == "fetch":
                args = (*args[:3], str(self.repo), f"{self.head}:refs/proof/base", f"{self.head}:refs/proof/head")
                env = os.environ.copy()
            return original(root, *args, env=env)

        destination = self.root / "objects"
        with patch.object(MODULE, "git", side_effect=local_fetch):
            MODULE.fetch(destination, "owner/private", "https://github.com", self.head, self.head, "42", "secret")
        self.assertEqual(original(destination, "rev-parse", "--is-bare-repository").strip(), b"true")
        self.assertFalse((destination / ".proof").exists())
        args, env = next(row for row in commands if row[0][0] == "fetch")
        self.assertIn("https://github.com/owner/private.git", args)
        self.assertIn("refs/pull/42/head:refs/proof/head", args)
        self.assertNotIn("secret", repr(args))
        self.assertEqual(env["GIT_CONFIG_KEY_2"], "http.extraHeader")
        self.assertEqual(env["GIT_CONFIG_VALUE_1"], "false")
        self.assertNotIn("AUTHORIZATION", (destination / "config").read_text())
        output = self.root / "candidate/.proof/policy.yaml"
        MODULE.policy(destination, self.head, output)
        self.assertEqual(output.read_text(), '{"version":2}')

    def test_rejects_inputs_before_any_git_call(self):
        good = [self.root / "objects", "owner/repo", "https://github.com", self.head, self.head, "42", "secret"]
        for index, value in [(1,"--upload-pack=evil"),(2,"https://evil@github.com"),(2,"file:///tmp/repo"), (3,"HEAD"),(4,"-x"),(5,"1;echo evil")]:
            args = good.copy()
            args[index] = value
            with self.subTest(value=value), patch.object(MODULE, "git") as run:
                with self.assertRaises(ValueError):
                    MODULE.fetch(*args)
                run.assert_not_called()

    def test_moving_pr_head_fails_closed(self):
        with patch.object(MODULE, "git", return_value=b"0" * 40):
            with self.assertRaisesRegex(ValueError, "revision changed"):
                MODULE.fetch(self.root / "objects", "owner/repo", "https://github.com", self.head, self.head, "", "token")

    def test_rejects_symlink_executable_missing_and_large_policy(self):
        policy = self.repo / ".proof/policy.yaml"
        for kind in ("symlink", "executable", "missing", "large", "empty"):
            with self.subTest(kind=kind):
                self.git("reset", "--hard", self.head)
                policy.unlink()
                if kind == "symlink":
                    policy.symlink_to("../../outside")
                elif kind == "executable":
                    policy.write_text("bad")
                    policy.chmod(0o755)
                elif kind in ("large", "empty"):
                    policy.write_text("x" * (MODULE.MAX_POLICY_BYTES + 1) if kind == "large" else "")
                self.git("add", "-A")
                tree = self.git("write-tree")
                with self.assertRaises(ValueError):
                    MODULE.policy(self.repo, tree, self.root / kind / ".proof/policy.yaml")

    def test_rejects_symlink_parent(self):
        self.git("rm", "-r", ".proof")
        (self.repo / ".proof").symlink_to("/tmp")
        self.git("add", ".proof")
        with self.assertRaisesRegex(ValueError, "must be a tree"):
            MODULE.policy(self.repo, self.git("write-tree"), self.root / "out/.proof/policy.yaml")

    def test_git_errors_do_not_disclose_remote_text(self):
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"secret credential")):
            with self.assertRaisesRegex(ValueError, "metadata operation failed") as error:
                MODULE.git(self.repo, "fetch")
            self.assertNotIn("secret", str(error.exception))

    def test_workflows_only_checkout_trusted_revision(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("change-scope.yml", "proof-scorecard.yml"):
            text = (root / "workflows" / name).read_text()
            self.assertEqual(text.count("uses: actions/checkout@"), 1)
            self.assertIn("github.workflow_sha", text)
            self.assertNotIn("allow-unsafe-pr-checkout", text)
            self.assertIn("fetch_pr_metadata.py", text)


    def test_stale_pr_base_does_not_select_target_runtime(self):
        root = Path(__file__).resolve().parents[2]
        stale_base = self.head
        (self.repo / ".proof/fetch_pr_metadata.py").write_text("# newly installed helper\n")
        self.commit()
        workflow_sha = self.head
        self.assertNotEqual(stale_base, workflow_sha)
        for name in ("change-scope.yml", "proof-scorecard.yml"):
            workflow = yaml.safe_load((root / "workflows" / name).read_text())
            job = next(iter(workflow["jobs"].values()))
            checkout = next(step for step in job["steps"] if "uses" in step and "actions/checkout@" in step["uses"])
            expected = "${{ github.workflow_sha }}" if name == "change-scope.yml" else "${{ github.event_name == 'pull_request_review' && github.event.pull_request.base.sha || github.workflow_sha }}"
            self.assertEqual(checkout["with"]["ref"], expected)
            # For target events both expressions select the workflow commit,
            # even when the payload base predates the installed helper.
            self.assertIn("newly installed helper", self.git("show", f"{workflow_sha}:.proof/fetch_pr_metadata.py"))
            with self.assertRaises(subprocess.CalledProcessError):
                self.git("show", f"{stale_base}:.proof/fetch_pr_metadata.py")
            fetch = next(step for step in job["steps"] if step.get("name") == "Fetch candidate metadata without checkout")
            self.assertEqual(fetch["env"]["BASE_SHA"], "${{ github.event.pull_request.base.sha || github.sha }}")
            triggers = workflow.get("on", workflow.get(True))
            self.assertIn("edited", triggers["pull_request_target"]["types"])

    def test_main_success_and_failure(self):
        env = dict(GITHUB_REPOSITORY="owner/repo", GITHUB_SERVER_URL="https://github.com",
                   BASE_SHA=self.head, HEAD_SHA=self.head, GH_TOKEN="secret", PR_NUMBER="42")
        argv = ["fetch_pr_metadata.py", "--repository-root", str(self.root / "objects")]
        with patch.dict(os.environ, env), patch("sys.argv", argv), patch.object(MODULE, "fetch"):
            self.assertEqual(MODULE.main(), 0)
        with patch.dict(os.environ, env), patch("sys.argv", argv + ["--policy-output", "output/policy.yaml"]), patch.object(MODULE, "fetch"), patch.object(MODULE, "policy") as read:
            self.assertEqual(MODULE.main(), 0)
            read.assert_called_once()
        with patch.dict(os.environ, env), patch("sys.argv", argv), patch.object(MODULE, "fetch", side_effect=ValueError("secret")), patch("sys.stderr") as stderr:
            self.assertEqual(MODULE.main(), 1)
            self.assertNotIn("secret", str(stderr.write.call_args_list))
