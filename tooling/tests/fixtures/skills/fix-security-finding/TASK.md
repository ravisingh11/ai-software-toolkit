# Seeded task for `fix-security-finding`

The synthetic check `python3 scan.py` reports `SEED-SHELL-TRUE` at `runner.py:6`: user-controlled `name` reaches `subprocess.run(..., shell=True)`. Confirm reachability, remediate without `shell=True`, and add a regression test that fails on the old code.

Expected outcome report fields are defined in `skills/fix-security-finding/SKILL.md`.

Run the syntax-only scanner before and after the fix. It requires only Python
and never executes runner.py. Mock subprocess.run for any attacker input in
the regression test; do not execute an injection payload against a real shell.
