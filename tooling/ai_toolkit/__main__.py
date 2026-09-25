"""Run ``python3 -m ai_toolkit`` or ``python3 tooling/ai_toolkit`` from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    # Invoked as a path (python3 tooling/ai_toolkit); make the package importable.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ai_toolkit.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
