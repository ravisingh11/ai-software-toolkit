"""Exercise the optional example; external engines are explicitly opt-in."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples/typescript-quality"
TOOLS = os.environ.get("PROOF_TYPESCRIPT_TOOLS")


class TypeScriptQualityExampleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "example"
        shutil.copytree(EXAMPLE, self.project)

    def test_defensive_suite_and_test_integrity_runner(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js 22.18+ is needed for the optional TypeScript example")
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if tuple(map(int, version.lstrip("v").split(".")[:2])) < (22, 18):
            self.skipTest("Node.js 22.18+ is needed for TypeScript type stripping")
        command = [sys.executable, str(ROOT / "tooling/check_test_integrity.py"), "--",
                   node, "--test", "--test-reporter=junit", "--test-reporter-destination={report}",
                   "tests/defensive.test.mjs"]
        result = subprocess.run(command, cwd=self.project, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("15 tests, 15 executed", result.stdout)
        source = self.project / "src/server/access.ts"
        source.write_text(source.read_text().replace("session.tenantId !== project.tenantId", "false"))
        broken = subprocess.run(command, cwd=self.project, text=True, capture_output=True)
        self.assertNotEqual(broken.returncode, 0)

    @unittest.skipUnless(TOOLS, "Set PROOF_TYPESCRIPT_TOOLS to opt into external lint/architecture engine tests")
    def test_lint_and_architecture_engines_accept_safe_code_and_reject_violations(self):
        tools = Path(TOOLS).resolve()
        (self.project / "node_modules").symlink_to(tools.parent)

        def run(tool, *args):
            return subprocess.run([str(tools / tool), *args], cwd=self.project, text=True, capture_output=True)

        result = run("tsc", "--noEmit")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run("eslint", "src", "--max-warnings", "0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        unsafe = self.project / "src/server/unsafe.ts"
        unsafe.write_text("Promise.resolve(1);\n")
        result = run("eslint", "src", "--max-warnings", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no-floating-promises", result.stdout)
        unsafe.unlink()
        args = ("--config", "dependency-cruiser.cjs", "src", "--output-type", "err-long")
        result = run("depcruise", *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        violations = (
            ("src/client/view.ts", 'export { parseLimit } from "../server/access.ts";\n', "client-cannot-import-server"),
            ("src/contracts/project.ts", 'export { parseLimit } from "../server/access.ts";\n', "contracts-cannot-import-applications"),
            ("src/missing.ts", 'export { value } from "./absent.ts";\n', "no-unresolved-imports"),
        )
        for path, content, rule in violations:
            with self.subTest(rule=rule):
                target = self.project / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                result = run("depcruise", *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(rule, result.stdout + result.stderr)
                target.unlink()
        (self.project / "src/a.ts").write_text('export { b } from "./b.ts";\nexport const a = 1;\n')
        (self.project / "src/b.ts").write_text('export { a } from "./a.ts";\nexport const b = 2;\n')
        result = run("depcruise", *args)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no-circular-dependencies", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
