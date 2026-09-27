# Architecture

This demo is a single-process Python application.

- `app.py` contains the application functions and has no network or database
  boundary.
- `test_app.py` contains the unit tests for `app.py`.
- `tools/` contains repository automation and evidence producers; it is not
  application runtime code.
- `.proof/` contains the installed shared Proof runtime.

Changes should preserve this small boundary unless the change explicitly
introduces a new component.
