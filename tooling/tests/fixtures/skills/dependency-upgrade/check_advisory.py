"""Synthetic manifest-only GHSA-SEED-0001 check, not a real provider scan."""
from pathlib import Path
import re
import sys

match = re.search(r"^requests==(\d+)\.(\d+)\.(\d+)$", Path("requirements.txt").read_text(), re.MULTILINE)
if not match:
    sys.exit("BLOCKED: expected an exact requests pin")
if tuple(map(int, match.groups())) < (2, 32, 0):
    sys.exit("GHSA-SEED-0001: synthetic vulnerable requests pin")
print("GHSA-SEED-0001: synthetic check clear")
