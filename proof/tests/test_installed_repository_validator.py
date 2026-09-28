from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("installed_repository_validator", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise AssertionError(f"cannot load module spec: {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def passing() -> None:
    return None


def failing() -> None:
    raise ValueError("broken contract")


class InstalledRepositoryValidatorTests(unittest.TestCase):
    def run_main(self, contracts: tuple, output: Path) -> int:
        with mock.patch.object(MODULE, "CONTRACTS", contracts), \
                mock.patch.dict(os.environ, {"PROOF_MEASUREMENTS_FILE": str(output)}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return MODULE.main()

    def test_passing_run_counts_every_contract_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            self.assertEqual(self.run_main((passing, passing, passing), output), 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {
                "version": 1, "source": "pull-request-workflow",
                "contracts": {"total": 3, "passed": 3, "failed": 0, "not_run": 0},
            })

    def test_first_failure_leaves_later_groups_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "measurements.json"
            self.assertEqual(self.run_main((passing, failing, passing, passing), output), 1)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["contracts"],
                             {"total": 4, "passed": 1, "failed": 1, "not_run": 2})

    def test_measurements_are_optional(self) -> None:
        with mock.patch.object(MODULE, "CONTRACTS", (passing,)), \
                mock.patch.dict(os.environ, {}, clear=False), \
                contextlib.redirect_stdout(io.StringIO()):
            os.environ.pop("PROOF_MEASUREMENTS_FILE", None)
            self.assertEqual(MODULE.main(), 0)


if __name__ == "__main__":
    unittest.main()
