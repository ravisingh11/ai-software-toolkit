from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "workflows" / "proof-scorecard-badge.yml"
INSTALLED = ROOT / ".github" / "workflows" / "proof-scorecard-badge.yml"
SOURCE_WORKFLOWS = (
    ROOT / "workflows" / "proof-scorecard.yml",
    ROOT / ".github" / "workflows" / "proof-scorecard.yml",
)


class ScorecardBadgeWorkflowTests(unittest.TestCase):
    def test_publisher_contract_is_privileged_but_bounded(self) -> None:
        for path in (CANONICAL, INSTALLED):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("workflow_run:", text)
                self.assertIn("workflows: [Proof Scorecard]", text)
                self.assertIn("types: [completed]", text)
                self.assertIn("schedule:", text)
                self.assertIn('cron: "17 */6 * * *"', text)
                self.assertNotIn("workflow_dispatch", text)
                self.assertIn("group: proof-scorecard-pages", text)
                self.assertIn("cancel-in-progress: false", text)
                expected_permissions = {
                    "actions": "read",
                    "contents": "read",
                    "pull-requests": "read",
                    "pages": "write",
                    "id-token": "write",
                }
                permission_block = text.split("permissions:\n", 1)[1].split(
                    "\njobs:", 1
                )[0]
                actual = dict(
                    re.findall(
                        r"^  ([a-z-]+): ([a-z]+)$", permission_block, re.MULTILINE
                    )
                )
                self.assertEqual(actual, expected_permissions)
                self.assertIn("PROOF_SCORECARD_BADGE_ENABLED == 'true'", text)
                self.assertIn(
                    "PROOF_SCORECARD_BADGE_PAGES_MODE == 'dedicated'", text
                )
                self.assertIn("environment:\n      name: github-pages", text)
                self.assertIn("PROOF_SCORECARD_BADGE_PAGES_ACCESS: ${{ vars.PROOF_SCORECARD_BADGE_PAGES_ACCESS }}", text)
                self.assertIn("fetch-depth: 0", text)
                self.assertIn("persist-credentials: false", text)
                self.assertNotIn("github.event.pull_request.head", text)
                self.assertNotIn("github.event.workflow_run.head", text)
                self.assertIn("python3 .proof/reconcile_scorecard_badge.py", text)
                self.assertIn('--github-output "${GITHUB_OUTPUT}"', text)
                self.assertIn('--job-summary "${GITHUB_STEP_SUMMARY}"', text)
                for pin in (
                    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                    "actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d",
                    "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9",
                    "actions/deploy-pages@368f82528645a54fb793d4d04e342629a3f51346",
                ):
                    self.assertIn(pin, text)
                for action in (
                    "actions/configure-pages@",
                    "actions/upload-pages-artifact@",
                    "actions/deploy-pages@",
                ):
                    action_position = text.index(action)
                    preceding = text[max(0, action_position - 220) : action_position]
                    self.assertIn(
                        "steps.reconcile.outputs.publish == 'true'", preceding
                    )

    def test_canonical_and_self_installed_publisher_match(self) -> None:
        self.assertEqual(CANONICAL.read_bytes(), INSTALLED.read_bytes())

    def test_scorecard_artifact_has_trusted_attempt_binding_before_render(self) -> None:
        for path in SOURCE_WORKFLOWS:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("name: Write trusted source binding", text)
                self.assertIn("GITHUB_EVENT_PATH", text)
                self.assertIn('"run_attempt"', text)
                self.assertIn('"pull_request_number"', text)
                self.assertIn('"base_repository"', text)
                self.assertIn('"base_branch"', text)
                self.assertIn('"base_sha"', text)
                self.assertLess(
                    text.index("name: Write trusted source binding"),
                    text.index("name: Render scorecard"),
                )
                self.assertIn(
                    "name: proof-scorecard-${{ github.run_id }}-${{ github.run_attempt }}",
                    text,
                )
                self.assertIn("source.json", text)
                permission_block = text.split("permissions:\n", 1)[1].split(
                    "\njobs:", 1
                )[0]
                self.assertNotIn("write", permission_block)

    def test_workflows_parse_as_yaml(self) -> None:
        ruby = shutil.which("ruby")
        if ruby is None:
            self.skipTest("Ruby stdlib YAML parser is unavailable")
        for path in (*SOURCE_WORKFLOWS, CANONICAL, INSTALLED):
            with self.subTest(path=path):
                completed = subprocess.run(
                    [
                        ruby,
                        "-e",
                        "require 'yaml'; YAML.load_file(ARGV.fetch(0))",
                        str(path),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
