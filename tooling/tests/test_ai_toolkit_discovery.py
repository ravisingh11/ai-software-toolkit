from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tooling"))

from ai_toolkit import discovery  # noqa: E402


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve()

    def write(self, relative: str, content: str = "") -> Path:
        path = self.target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_empty_directory_has_no_languages(self):
        found = discovery.discover(self.target, environment={"HOME": str(self.target)})
        self.assertEqual(found["languages"], [])
        self.assertEqual(found["commands"], {})
        self.assertEqual(found["variables"], {})
        self.assertIn("No Python or Node project markers", discovery.render(found))

    def test_python_pyproject_with_pytest_and_ruff(self):
        self.write("pyproject.toml", '[project]\nname = "x"\n[build-system]\nrequires = ["setuptools"]\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n[tool.ruff]\nline-length = 100\n')
        self.write("requirements-dev.txt", "pytest\n")
        row = discovery.detect_python(self.target)
        self.assertEqual(row["package_manager"], "pip")
        self.assertEqual(row["commands"]["unit-tests"]["command"], "python3 -m pytest")
        self.assertEqual(row["commands"]["build"]["command"], "python3 -m build")
        self.assertEqual(row["commands"]["format-and-lint"]["command"], "ruff check .")
        self.assertEqual(row["commands"]["setup"]["command"], "python3 -m pip install -r requirements-dev.txt")

    def test_python_unittest_flake8_and_alternative_managers(self):
        self.write("app.py", "x = 1\n")
        self.write("test_app.py", "import unittest\n")
        self.write(".flake8", "[flake8]\n")
        row = discovery.detect_python(self.target)
        self.assertEqual(row["commands"]["unit-tests"]["command"], "python3 -m unittest discover")
        self.assertEqual(row["commands"]["build"]["command"], "python3 -m compileall -q .")
        self.assertEqual(row["commands"]["format-and-lint"]["command"], "python3 -m flake8")
        self.assertNotIn("setup", row["commands"])
        for marker, manager, setup in (("poetry.lock", "poetry", "poetry install"), ("uv.lock", "uv", "uv sync"), ("Pipfile", "pipenv", "pipenv install --dev")):
            self.write(marker, "")
            row = discovery.detect_python(self.target)
            self.assertEqual(row["package_manager"], manager)
            self.assertEqual(row["commands"]["setup"]["command"], setup)
            (self.target / marker).unlink()

    def test_python_invalid_pyproject_is_tolerated(self):
        self.write("pyproject.toml", "this is not toml [[[")
        row = discovery.detect_python(self.target)
        self.assertEqual(row["language"], "python")

    def test_node_package_managers_and_scripts(self):
        self.write("package.json", json.dumps({"scripts": {"test": "jest", "build": "tsc", "lint": "eslint ."}}))
        self.write("tsconfig.json", "{}")
        row = discovery.detect_node(self.target)
        self.assertEqual(row["package_manager"], "npm")
        self.assertEqual(row["codeql_language"], "javascript-typescript")
        self.assertEqual(row["commands"]["unit-tests"]["command"], "npm run test")
        self.assertEqual(row["commands"]["format-and-lint"]["command"], "npm run lint")
        self.assertEqual(row["commands"]["setup"]["command"], "npm ci")
        self.write("pnpm-lock.yaml", "")
        self.assertEqual(discovery.detect_node(self.target)["package_manager"], "pnpm")
        (self.target / "pnpm-lock.yaml").unlink()
        self.write("yarn.lock", "")
        self.assertEqual(discovery.detect_node(self.target)["commands"]["setup"]["command"], "yarn install --frozen-lockfile")
        (self.target / "yarn.lock").unlink()
        self.write("bun.lock", "")
        self.assertEqual(discovery.detect_node(self.target)["package_manager"], "bun")
        self.write("package.json", json.dumps({"packageManager": "pnpm@9.0.0", "scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}))
        row = discovery.detect_node(self.target)
        self.assertEqual(row["package_manager"], "pnpm")
        self.assertNotIn("unit-tests", row["commands"])
        (self.target / "bun.lock").unlink()
        self.write("package.json", "not json")
        self.assertEqual(discovery.detect_node(self.target)["commands"]["setup"]["command"], "npm ci")

    def test_workflows_provider_configuration_and_integrations(self):
        self.write(".github/workflows/sonar.yml", "name: 'SonarQube'\njobs:\n  a:\n    steps:\n      - uses: SonarSource/sonarqube-scan-action@sha\n")
        self.write(".github/workflows/build.yml", "# Guardrails v2 installer-owned workflow.\nname: Build\n")
        self.write(".github/workflows/notes.txt", "ignored")
        self.write("sonar-project.properties", "sonar.projectKey=x\n")
        self.write(".snyk", "")
        rows = discovery.detect_workflows(self.target)
        self.assertEqual([row["path"] for row in rows], [".github/workflows/build.yml", ".github/workflows/sonar.yml"])
        self.assertTrue(rows[0]["installer_owned"])
        self.assertEqual(rows[1]["name"], "SonarQube")
        self.assertEqual(rows[1]["integrations"], ["sonarqube"])
        configuration = discovery.detect_provider_configuration(self.target)
        self.assertEqual(configuration, {"sonarqube": ["sonar-project.properties"], "snyk": [".snyk"]})
        found = discovery.discover(self.target, environment={"HOME": str(self.target)})
        integrations = discovery.existing_integrations(found)
        self.assertEqual(sorted(integrations), ["snyk", "sonarqube"])
        self.assertIn(".github/workflows/sonar.yml", integrations["sonarqube"])
        rendered = discovery.render(found)
        self.assertIn("Existing integrations", rendered)
        self.assertIn("not owned by the installer: .github/workflows/sonar.yml", rendered)

    def test_agent_clients_and_toolkit_state(self):
        home = self.target / "home"
        (home / ".codex").mkdir(parents=True)
        (self.target / ".claude" / "skills").mkdir(parents=True)
        clients = discovery.detect_agent_clients(self.target, {"HOME": str(home)})
        self.assertTrue(clients["codex"]["detected"])
        self.assertFalse(clients["claude-code"]["detected"])
        self.assertTrue(clients["claude-code"]["present_in_project"])
        self.assertEqual(clients["codex"]["user_skills_dir"], str(home / ".codex" / "skills"))
        custom = discovery.detect_agent_clients(self.target, {"HOME": str(home), "CODEX_HOME": str(self.target / "cx"), "CLAUDE_CONFIG_DIR": str(self.target / "cl")})
        self.assertFalse(custom["codex"]["detected"])
        self.write(".guardrails/policy.yaml", json.dumps({"version": 2}))
        self.write("toolkit.toml", "")
        self.write("docs/ai/skills/qa/config.yaml", "apps: []\n")
        state = discovery.detect_toolkit_state(self.target)
        self.assertTrue(state["guardrails_installed"])
        self.assertEqual(state["guardrails_version"], 2)
        self.assertTrue(state["toolkit_toml"])
        self.assertFalse(state["toolkit_lock"])
        self.assertEqual(state["qa_configurations"], ["docs/ai/skills/qa/config.yaml"])
        found = discovery.discover(self.target, environment={"HOME": str(home)})
        rendered = discovery.render(found)
        self.assertIn("QA configuration: docs/ai/skills/qa/config.yaml", rendered)
        self.assertIn("Agent clients detected: codex", rendered)

    def test_variables_follow_workflow_names(self):
        self.write("pyproject.toml", "[project]\nname = 'x'\n")
        self.write("package.json", json.dumps({"scripts": {"test": "vitest"}}))
        found = discovery.discover(self.target, environment={"HOME": str(self.target)})
        self.assertEqual(found["variables"]["GUARDRAILS_CODEQL_LANGUAGES"], "python,javascript")
        self.assertEqual(found["variables"]["GUARDRAILS_UNIT_TEST_COMMAND"], "npm run test")
        self.assertIn("GUARDRAILS_UNIT_TEST_COMMAND='npm run test'", discovery.render(found))


if __name__ == "__main__":
    unittest.main()
