# Seeded task for `dependency-upgrade`

Advisory `GHSA-SEED-0001` affects `requests<2.32.0`. Upgrade `requests` in `requirements.txt` to a version that resolves the advisory using pip's own resolution, keep other pins unchanged, run the tests, and write the rollback note.

Expected outcome report fields are defined in `skills/dependency-upgrade/SKILL.md`.

This is a manifest-only synthetic task, with no lockfile. In a disposable
virtual environment, verify installation with `python3 -m pip install -r requirements.txt`.
Run `python3 check_advisory.py` before (fails) and after (passes). This
self-contained check only validates the seeded advisory, not real Snyk or
Dependabot findings. Report lockfile verification as not applicable.
