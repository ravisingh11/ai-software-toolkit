from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))

from ai_toolkit import cli, config  # noqa: E402
from ai_toolkit.runtime import ToolkitError  # noqa: E402

FAKE_GH = """#!/usr/bin/env bash
if [[ "$1" == "variable" && "$2" == "list" ]]; then
  echo '[{"name": "GUARDRAILS_BUILD_COMMAND"}]'
  exit 0
fi
if [[ "$1" == "variable" && "$2" == "set" ]]; then
  if [[ "$3" == "GUARDRAILS_UNIT_TEST_COMMAND" ]]; then
    echo "boom" >&2
    exit 1
  fi
  exit 0
fi
exit 3
"""


def run_cli(*arguments: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(list(arguments))
    return code, stdout.getvalue(), stderr.getvalue()


class CliFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "repo"
        self.target.mkdir()
        self.home = self.root / "home"
        (self.home / ".codex").mkdir(parents=True)
        self.environment = patch.dict(os.environ, {"HOME": str(self.home), "CODEX_HOME": str(self.home / ".codex"),
                                                   "CLAUDE_CONFIG_DIR": str(self.home / ".claude"), "AI_TOOLKIT_TEST": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for variable in ("GUARDRAILS_BUILD_COMMAND", "GUARDRAILS_UNIT_TEST_COMMAND", "GUARDRAILS_FORMAT_LINT_COMMAND"):
            os.environ.pop(variable, None)
        (self.target / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.target / "test_calc.py").write_text("import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n", encoding="utf-8")
        (self.target / "pyproject.toml").write_text('[project]\nname = "fresh"\nversion = "0.1.0"\n', encoding="utf-8")
        (self.target / "README.md").write_text("# Fresh\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")

    def git(self, *arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=self.target, text=True, capture_output=True, check=True).stdout.strip()

    def commit_all(self, message: str = "toolkit") -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def init(self, *extra: str) -> tuple[int, str, str]:
        return run_cli("init", "--target", str(self.target), "--yes", "--clients", "codex", *extra)


class DiscoverAndInitTests(CliFixture):
    def test_discover_text_and_json(self):
        code, out, _ = run_cli("discover", "--target", str(self.target))
        self.assertEqual(code, 0)
        self.assertIn("python (pip)", out)
        code, out, _ = run_cli("discover", "--target", str(self.target), "--json")
        self.assertEqual(json.loads(out)["kind"], "toolkit-discovery")

    def test_preview_writes_nothing(self):
        code, out, _ = run_cli("init", "--target", str(self.target), "--preview", "--json")
        self.assertEqual(code, 0)
        preview = json.loads(out)
        self.assertTrue(preview["guardrails"])
        self.assertFalse((self.target / ".guardrails").exists())
        self.assertFalse((self.target / config.TOML_NAME).exists())
        self.assertTrue(any(row["detail"].startswith("gh variable set") for row in preview["variables"]))
        code, out, _ = run_cli("init", "--target", str(self.target), "--preview")
        self.assertIn(".gitignore: add .artifacts/, __pycache__/", out)
        self.assertIn("Preview only", out)

    def test_declined_confirmation_writes_nothing(self):
        with patch.object(cli, "_confirm", return_value=False):
            code, out, _ = run_cli("init", "--target", str(self.target))
        self.assertEqual(code, 0)
        self.assertIn("Nothing was written", out)
        self.assertFalse((self.target / ".guardrails").exists())
        with patch.object(cli.sys.stdin, "isatty", return_value=False):
            self.assertFalse(cli._confirm("? "))
        with patch.object(cli.sys.stdin, "isatty", return_value=True), patch("builtins.input", return_value="y"):
            self.assertTrue(cli._confirm("? "))
        with patch.object(cli.sys.stdin, "isatty", return_value=True), patch("builtins.input", side_effect=EOFError):
            self.assertFalse(cli._confirm("? "))

    def test_apply_creates_configuration_lock_and_ignore_rules(self):
        with patch.object(cli, "_confirm", return_value=True):
            code, out, _ = run_cli("init", "--target", str(self.target), "--clients", "codex,claude-code", "--skills", "code-review")
        self.assertEqual(code, 0)
        self.assertIn("Applied.", out)
        self.assertTrue((self.target / ".guardrails" / "policy.yaml").is_file())
        self.assertTrue((self.target / ".github" / "workflows" / "build.yml").is_file())
        self.assertTrue((self.target / ".agents" / "skills" / "code-review" / "SKILL.md").is_file())
        self.assertTrue((self.target / ".claude" / "skills" / "qa-bootstrap" / "SKILL.md").is_file())
        configuration = config.read_configuration(self.target)
        self.assertEqual(configuration["agents"]["clients"], ["codex", "claude-code"])
        lock = config.read_lock(self.target)
        self.assertIn(".guardrails/policy.yaml", lock["managed"])
        self.assertIn(".claude/skills/code-review/SKILL.md", lock["managed"])
        ignore = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".artifacts/\n", ignore)
        self.assertIn("__pycache__/\n", ignore)
        # Re-running init on an installed repository adopts it without rewriting the runtime.
        policy_before = (self.target / ".guardrails" / "policy.yaml").read_bytes()
        code, out, _ = run_cli("init", "--target", str(self.target), "--preview")
        self.assertEqual(code, 0)
        self.assertIn("already installed", out)
        self.assertEqual((self.target / ".guardrails" / "policy.yaml").read_bytes(), policy_before)
        self.assertTrue(json.loads(run_cli("init", "--target", str(self.target), "--preview", "--json")[1])["adopt_existing"])

    def test_component_subsets_profiles_and_no_actions(self):
        code, out, _ = self.init("--components", "skills", "--skills", "starter", "--json")
        self.assertEqual(code, 0)
        self.assertFalse((self.target / ".guardrails").exists())
        self.assertTrue((self.target / ".agents" / "skills" / "toolkit-setup").is_dir())
        for path in (self.target / ".agents", self.target / config.TOML_NAME, self.target / config.LOCK_NAME):
            subprocess.run(["rm", "-rf", str(path)], check=True)
        code, out, _ = self.init("--components", "qa", "--json")
        installed = [row["skill"] for row in json.loads(out)["applied"]["skills"][0]["skills"]]
        self.assertEqual(installed, ["qa-bootstrap", "_shared-project-ops"])
        subprocess.run(["rm", "-rf", str(self.target / ".agents"), str(self.target / config.TOML_NAME), str(self.target / config.LOCK_NAME)], check=True)
        code, out, _ = self.init("--components", "guardrails", "--profile", "github", "--no-actions")
        self.assertEqual(code, 0)
        self.assertTrue((self.target / ".guardrails" / "policy.yaml").is_file())
        self.assertFalse((self.target / ".github" / "workflows").exists())
        self.assertEqual(cli.installed_profiles(self.target), ["core", "github"])

    def test_invalid_inputs(self):
        for arguments in (("--components", "nope"), ("--clients", "vim"), ("--skills", "missing-skill")):
            code, _, err = run_cli("init", "--target", str(self.target), "--yes", *arguments)
            self.assertEqual(code, 2, err)
            self.assertIn("ERROR", err)
        code, _, err = run_cli("discover", "--target", str(self.root / "missing"))
        self.assertEqual(code, 2)

    def test_installer_failures_surface(self):
        (self.target / ".guardrails").mkdir()
        (self.target / ".guardrails" / "policy.yaml").write_text(json.dumps({"version": 1}), encoding="utf-8")
        code, _, err = run_cli("init", "--target", str(self.target), "--preview")
        self.assertEqual(code, 2)
        self.assertIn("installer preview failed", err)

    def test_gitignore_merge_is_idempotent(self):
        (self.target / ".gitignore").write_text("node_modules", encoding="utf-8")
        found = {"languages": [{"language": "python"}]}
        self.assertTrue(cli.ensure_gitignore(self.target, found))
        self.assertEqual((self.target / ".gitignore").read_text(encoding="utf-8"), "node_modules\n# AI Software Toolkit scan artifacts\n.artifacts/\n__pycache__/\n")
        self.assertFalse(cli.ensure_gitignore(self.target, found))
        self.assertEqual(cli.gitignore_additions(self.target, {"languages": []}), [])

    def test_apply_variables_with_and_without_gh(self):
        variables = {"GUARDRAILS_BUILD_COMMAND": "make", "GUARDRAILS_UNIT_TEST_COMMAND": "make test", "GUARDRAILS_CODEQL_LANGUAGES": "python"}
        with patch.dict(os.environ, {"PATH": str(self.root / "nowhere")}):
            rows = cli.apply_variables(self.target, variables, dry_run=False)
        self.assertEqual({row["action"] for row in rows}, {"manual"})
        binaries = self.root / "bin"
        binaries.mkdir()
        gh = binaries / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        with patch.dict(os.environ, {"PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}"}):
            rows = {row["name"]: row for row in cli.apply_variables(self.target, variables, dry_run=False)}
            self.assertEqual(rows["GUARDRAILS_BUILD_COMMAND"]["action"], "kept")
            self.assertEqual(rows["GUARDRAILS_CODEQL_LANGUAGES"]["action"], "set")
            self.assertEqual(rows["GUARDRAILS_UNIT_TEST_COMMAND"]["action"], "failed")
            self.assertIn("boom", rows["GUARDRAILS_UNIT_TEST_COMMAND"]["detail"])
            code, out, _ = self.init("--components", "skills", "--apply-variables", "--json")
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out)["applied"]["variables"])
        gh.write_text("#!/usr/bin/env bash\necho 'not json'\n", encoding="utf-8")
        with patch.dict(os.environ, {"PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}"}):
            self.assertIsNone(cli._existing_variables(self.target))
        gh.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        with patch.dict(os.environ, {"PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}"}):
            self.assertIsNone(cli._existing_variables(self.target))


class DoctorCheckTests(CliFixture):
    def test_doctor_before_installation(self):
        code, out, _ = run_cli("doctor", "--target", str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("missing    guardrails", out)
        self.assertIn("Run `ai-toolkit init`", out)
        code, _, err = run_cli("check", "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("not installed", err)

    def test_init_check_doctor_lifecycle(self):
        self.assertEqual(self.init()[0], 0)
        self.commit_all()
        code, out, _ = run_cli("doctor", "--target", str(self.target), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["components"]["guardrails"]["state"], "installed")
        self.assertEqual(payload["components"]["toolkit"]["state"], "configured")
        self.assertEqual(payload["components"]["qa"]["state"], "missing")
        states = {row["capability"]: row["state"] for row in payload["capabilities"]}
        self.assertEqual(states["build"], "installed")
        self.assertEqual(states["repository-validation"], "configured")
        with patch.dict(os.environ, {"GUARDRAILS_BUILD_COMMAND": "python3 -m compileall -q calc.py", "GUARDRAILS_UNIT_TEST_COMMAND": "python3 -m unittest discover"}):
            code, out, _ = run_cli("check", "--target", str(self.target))
        self.assertEqual(code, 0, out)
        self.assertIn("PASS  unit-tests", out)
        self.assertIn("PASS  build", out)
        self.assertIn("What remains unverified", out)
        self.assertTrue((self.target / ".artifacts" / "guardrails" / "evidence.json").is_file())
        self.assertEqual(self.git("status", "--porcelain"), "")
        code, out, _ = run_cli("doctor", "--target", str(self.target))
        self.assertIn("verified   unit-tests", out)
        self.assertIn("bound to HEAD", out)
        code, out, _ = run_cli("check", "--target", str(self.target), "--json")
        self.assertEqual(json.loads(out)["decision"], "allow")

    def test_check_reports_scan_failures(self):
        self.assertEqual(self.init()[0], 0)
        self.commit_all()
        with patch.object(cli, "run_python", return_value=subprocess.CompletedProcess([], 2, "", "scan exploded")):
            code, _, err = run_cli("check", "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("scan exploded", err)
        with patch.object(cli, "run_python", return_value=subprocess.CompletedProcess([], 0, "not json", "")):
            code, _, err = run_cli("check", "--target", str(self.target))
        self.assertEqual(code, 2)
        with patch.object(cli, "run_python", return_value=subprocess.CompletedProcess([], 2, "", "doctor exploded")):
            code, _, err = run_cli("doctor", "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("doctor exploded", err)


class ProvidersSkillsQaTests(CliFixture):
    def test_providers(self):
        code, out, _ = run_cli("providers", "--target", str(self.target))
        self.assertEqual(code, 0)
        self.assertIn("sonarqube  (SonarQube; external; opt-in)", out)
        code, out, _ = run_cli("providers", "show", "sonarqube", "--target", str(self.target), "--json")
        rows = json.loads(out)["providers"]
        self.assertEqual(rows[0]["credential_names"], ["SONAR_TOKEN"])
        code, _, err = run_cli("providers", "show", "nope", "--target", str(self.target))
        self.assertEqual(code, 2)
        code, _, err = run_cli("providers", "select", "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertEqual(self.init("--components", "guardrails")[0], 0)
        code, out, _ = run_cli("providers", "show", "semgrep-app", "--target", str(self.target))
        self.assertIn("none shipped", out)
        code, out, _ = run_cli("providers", "show", "snyk-code", "--target", str(self.target))
        self.assertIn("adapter-owned (snyk code test", out)
        with patch.object(cli, "run_python", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            code, _, _ = run_cli("providers", "select", "--selection", "deep-sast=snyk-code", "--target", str(self.target))
        self.assertEqual(code, 0)
        self.assertIn("--select-provider", run.call_args.args[1])
        (self.target / ".guardrails" / "providers.yaml").write_text("{", encoding="utf-8")
        self.assertEqual(run_cli("providers", "--target", str(self.target))[0], 2)

    def test_skills_commands(self):
        code, out, _ = run_cli("skills", "--target", str(self.target))
        self.assertIn("toolkit-setup", out.splitlines())
        code, out, _ = run_cli("skills", "list", "--target", str(self.target), "--json")
        self.assertIn("code-review", json.loads(out)["skills"])
        code, out, _ = run_cli("skills", "install", "--skill", "code-review", "--client", "codex,claude-code", "--target", str(self.target))
        self.assertEqual(code, 0)
        self.assertTrue((self.target / ".agents" / "skills" / "code-review" / "SKILL.md").is_file())
        self.assertTrue((self.target / ".claude" / "skills" / "code-review" / "SKILL.md").is_file())
        (self.target / ".agents" / "skills" / "code-review" / "SKILL.md").write_text("edited", encoding="utf-8")
        code, out, _ = run_cli("skills", "install", "--skill", "code-review", "--target", str(self.target), "--dry-run")
        self.assertIn("skip", out)
        code, out, _ = run_cli("skills", "refresh", "--skill", "code-review", "--target", str(self.target), "--json")
        self.assertNotEqual((self.target / ".agents" / "skills" / "code-review" / "SKILL.md").read_text(encoding="utf-8"), "edited")
        code, out, _ = run_cli("skills", "install", "--skill", "toolkit-setup", "--user", "--target", str(self.target))
        self.assertTrue((self.home / ".codex" / "skills" / "toolkit-setup" / "SKILL.md").is_file())
        self.assertEqual(run_cli("skills", "install", "--client", "vim", "--target", str(self.target))[0], 2)

    def test_qa_commands(self):
        code, out, _ = run_cli("qa", "--target", str(self.target))
        self.assertEqual(code, 0)
        self.assertIn("generated qa configuration: none", out)
        code, out, _ = run_cli("qa", "bootstrap", "--target", str(self.target), "--client", "claude-code", "--dry-run", "--json")
        self.assertEqual(json.loads(out)["results"][0]["client"], "claude-code")
        self.assertFalse((self.target / ".claude").exists())
        code, out, _ = run_cli("qa", "bootstrap", "--target", str(self.target))
        self.assertTrue((self.target / ".agents" / "skills" / "qa-bootstrap" / "SKILL.md").is_file())
        qa = self.target / "docs" / "ai" / "skills" / "qa"
        qa.mkdir(parents=True)
        (qa / "config.yaml").write_text("apps: []\n", encoding="utf-8")
        (self.target / ".github" / "workflows").mkdir(parents=True)
        (self.target / ".github" / "workflows" / "qa.yml").write_text("name: QA\n", encoding="utf-8")
        code, out, _ = run_cli("qa", "status", "--target", str(self.target))
        self.assertIn("docs/ai/skills/qa/config.yaml", out)
        self.assertIn(".github/workflows/qa.yml", out)
        self.assertEqual(run_cli("qa", "bootstrap", "--client", "vim", "--target", str(self.target))[0], 2)


class UpdateTests(CliFixture):
    def test_update_requires_configuration(self):
        code, _, err = run_cli("update", "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertIn("toolkit.toml is missing", err)
        code, _, err = run_cli("update", "--target", str(self.target), "--rollback")
        self.assertEqual(code, 2)
        self.assertIn("nothing to roll back", err)

    def test_update_lifecycle(self):
        self.assertEqual(self.init("--skills", "code-review")[0], 0)
        self.commit_all()
        code, out, _ = run_cli("update", "--target", str(self.target), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Up to date", out)
        code, out, _ = run_cli("update", "--target", str(self.target), "--force", "--dry-run", "--json")
        self.assertFalse(json.loads(out)["applied"])

        workflow = self.target / ".github" / "workflows" / "build.yml"
        workflow.write_text("# my own workflow\n" + workflow.read_text(encoding="utf-8").split("\n", 1)[1], encoding="utf-8")
        skill = self.target / ".agents" / "skills" / "code-review" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nlocal note\n", encoding="utf-8")
        documentation = self.target / ".guardrails" / "documentation.yaml"
        documentation.write_text(documentation.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        runtime = self.target / ".guardrails" / "scan.py"
        runtime.write_text(runtime.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        (self.target / ".guardrails" / "doctor.py").unlink()

        code, out, _ = run_cli("update", "--target", str(self.target), "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertTrue(payload["applied"])
        self.assertEqual(payload["classification"]["missing"], [".guardrails/doctor.py"])
        conflicts = {row["path"]: row["canonical"] for row in payload["conflicts"]}
        self.assertEqual(set(conflicts), {".github/workflows/build.yml", ".agents/skills/code-review/SKILL.md", ".guardrails/scan.py"})
        self.assertTrue((self.target / conflicts[".guardrails/scan.py"]).is_file())
        self.assertTrue(workflow.read_text(encoding="utf-8").startswith("# my own workflow"))
        self.assertTrue(skill.read_text(encoding="utf-8").endswith("local note\n"))
        self.assertTrue(runtime.read_text(encoding="utf-8").endswith("# drift\n"))
        self.assertTrue((self.target / ".guardrails" / "doctor.py").is_file())
        lock = config.read_lock(self.target)
        self.assertEqual(lock["previous"]["backup"], payload["backup"])

        code, out, _ = run_cli("update", "--target", str(self.target), "--rollback", "--dry-run")
        self.assertIn("Would restore", out)
        code, out, _ = run_cli("update", "--target", str(self.target), "--rollback")
        self.assertEqual(code, 0)
        self.assertIn("Restored", out)
        self.assertFalse((self.target / ".guardrails" / "doctor.py").exists())
        self.assertNotIn("previous", config.read_lock(self.target))
        self.assertIn(".guardrails/scan.py", config.read_lock(self.target)["managed"])

    def test_update_without_lock_bootstraps_from_ownership(self):
        self.assertEqual(self.init("--skills", "code-review")[0], 0)
        (self.target / config.LOCK_NAME).unlink()
        skill = self.target / ".agents" / "skills" / "code-review" / "SKILL.md"
        skill.write_text("mine\n", encoding="utf-8")
        code, out, _ = run_cli("update", "--target", str(self.target), "--dry-run")
        self.assertIn("ownership was inferred", out)
        self.assertIn(".agents/skills/code-review/SKILL.md", out)
        code, out, _ = run_cli("update", "--target", str(self.target))
        self.assertEqual(code, 0)
        self.assertEqual(skill.read_text(encoding="utf-8"), "mine\n")
        self.assertTrue((self.target / config.LOCK_NAME).is_file())

    def test_update_restores_on_installer_failure(self):
        self.assertEqual(self.init("--components", "guardrails")[0], 0)
        with patch.object(cli, "run_python", return_value=subprocess.CompletedProcess([], 2, "", "refresh failed")):
            code, _, err = run_cli("update", "--target", str(self.target), "--force")
        self.assertEqual(code, 2)
        self.assertIn("previous files were restored", err)
        self.assertTrue((self.target / ".guardrails" / "policy.yaml").is_file())

    def test_rollback_rejects_missing_backup(self):
        self.assertEqual(self.init("--components", "skills")[0], 0)
        lock = config.read_lock(self.target)
        lock["previous"] = {"revision": "v0", "backup": "../elsewhere", "managed": {}}
        config.write_lock(self.target, lock)
        code, _, err = run_cli("update", "--target", str(self.target), "--rollback")
        self.assertEqual(code, 2)
        self.assertIn("missing or outside", err)


class EntryPointTests(unittest.TestCase):
    def test_version_and_error_handling(self):
        with self.assertRaises(SystemExit):
            run_cli("--version")
        with patch.object(cli, "cmd_discover", side_effect=ToolkitError("nope")):
            code, _, err = run_cli("discover")
        self.assertEqual(code, 2)
        self.assertIn("nope", err)
        with patch.object(cli, "cmd_discover", side_effect=OSError("disk")):
            code, _, err = run_cli("discover")
        self.assertEqual(code, 2)
        self.assertIn("disk", err)

    def test_module_entry_point(self):
        completed = subprocess.run([sys.executable, str(ROOT / "tooling" / "ai_toolkit"), "--version"], text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("ai-toolkit", completed.stdout)
        completed = subprocess.run([sys.executable, "-m", "ai_toolkit", "skills", "list"], cwd=ROOT / "tooling", text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
