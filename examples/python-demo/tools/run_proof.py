#!/usr/bin/env python3
"""Run the demo's configured Core providers and write a v2 scorecard."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
def main() -> int:
    environment = os.environ.copy()
    environment.setdefault(
        "PROOF_BUILD_COMMAND",
        "python3 -m compileall -q app.py test_app.py tools .proof",
    )
    environment.setdefault(
        "PROOF_UNIT_TEST_COMMAND",
        "python3 -m unittest discover -s . -p 'test_*.py'",
    )
    environment.setdefault("PROOF_WORKING_DIRECTORY", ".")
    completed = subprocess.run(
        ["python3", ".proof/scan.py"],
        cwd=ROOT,
        env=environment,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
