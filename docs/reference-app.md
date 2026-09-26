# Reference app

`examples/python-demo/` is the toolkit's executable consumer: a standard-library
Python application with the Guardrails runtime installed under its own
`.guardrails/` and the Core and GitHub profile workflows under
`.github/workflows/`. It is the place where every toolkit change is proven
against a real installation before it is documented as working.

## What it demonstrates today

| Capability | Where | Status |
| --- | --- | --- |
| Install and refresh | `tooling/install.py --target examples/python-demo --refresh-existing`; the repository's own tests (`tooling/tests/test_consumer_lifecycle.py`, `test_python_demo.py`) exercise install, refresh, and validation | Shipped and tested on every change |
| Local scan and scorecard | `tools/run_guardrails.py` supplies real build and test commands and runs `.guardrails/scan.py` | Shipped |
| CI workflows | The installed Core and GitHub profile workflows run on this repository's pull requests; the example's own workflow copies are refreshed from `workflows/` | Shipped; every capability advisory |
| Ground truth | `.guardrails/ground-truth-ai.yaml` maps the demo's architecture, testing, security, and deployment documents | Shipped |
| Optional scorecard badge | `tools/` and the badge workflow described in the demo README | Shipped, opt-in |
| `ai-toolkit` CLI | `ai-toolkit init` on a copy of the demo adopts the existing installation and records `toolkit.toml` / `toolkit.lock.json`; `check` and `doctor` run against it | Shipped; the committed demo does not yet carry the two files (see below) |
| Provider adapters | `.guardrails/adapter.py` is installed; the Snyk and FOSSA templates are not copied into the demo because it has no vendor accounts | Adapter shipped; live runs unverified (see the [ledger](providers/verification.md)) |
| Functional QA | Not generated for the demo | Planned |
| Repair via an action skill | Not demonstrated | Planned (needs a recorded run per client, see each skill's `VERIFICATION.md`) |
| Node reference app | None | Planned |

## Why `toolkit.toml` and the lock are not committed yet

`toolkit.lock.json` records a hash of every installed file. The demo's
`.guardrails/` copies are refreshed from source on many toolkit changes, so a
committed lock would need `ai-toolkit update` on each refresh or it would
report the installer's own refresh as drift. That workflow is decided
separately; until then, adopt the demo with `ai-toolkit init` in a scratch copy
when you want to exercise the CLI end to end.

## How to use it

```sh
cd examples/python-demo
python3 -m unittest discover -s . -p 'test_*.py'
python3 tools/validate_demo.py --documentation
python3 tools/run_guardrails.py
```

To try the CLI without touching the committed example:

```sh
cp -r examples/python-demo /tmp/demo && cd /tmp/demo && git init -q && git add -A && git commit -qm demo
python3 <toolkit>/tooling/ai_toolkit init --target . --yes --clients codex
python3 <toolkit>/tooling/ai_toolkit doctor --target .
```

The demo's own [README](../examples/python-demo/README.md) covers the
scorecard output, the GitHub profile, and badges.
