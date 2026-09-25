"""AI Software Toolkit command-line interface.

The CLI is a facade over the existing installer, diagnostics, scanner,
configuration, and skill installer scripts. It adds discovery, the
``toolkit.toml`` / ``toolkit.lock.json`` files, and unified reports. It never
reimplements evaluation, and installed repositories never import it at
evaluation time.
"""

from __future__ import annotations

VERSION = "2.1.0"
