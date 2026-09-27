"""Self-contained seeded check for shell=True; never executes the target."""
import ast
from pathlib import Path
import sys

source = ast.parse(Path("runner.py").read_text())
for node in ast.walk(source):
    if isinstance(node, ast.Call):
        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                sys.exit("SEED-SHELL-TRUE: unsafe shell=True invocation")
print("SEED-SHELL-TRUE: clear (synthetic syntax check only)")
