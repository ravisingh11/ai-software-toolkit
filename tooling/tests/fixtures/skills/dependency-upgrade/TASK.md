# Seeded task for `dependency-upgrade`

Advisory `GHSA-SEED-0001` affects `requests<2.32.0`. Upgrade `requests` in `requirements.txt` to a version that resolves the advisory using pip's own resolution, keep other pins unchanged, run the tests, and write the rollback note.

Expected outcome report fields are defined in `skills/dependency-upgrade/SKILL.md`.
