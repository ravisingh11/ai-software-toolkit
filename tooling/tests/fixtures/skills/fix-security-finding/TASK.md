# Seeded task for `fix-security-finding`

Semgrep reports `python.lang.security.audit.subprocess-shell-true` at `runner.py:6`: user-controlled `name` reaches `subprocess.run(..., shell=True)`. Confirm reachability, remediate without `shell=True`, and add a regression test that fails on the old code.

Expected outcome report fields are defined in `skills/fix-security-finding/SKILL.md`.
