# Reference applications

The separate [Fieldnotes reference application](https://github.com/ravisingh11/ai-software-toolkit-reference-app)
is the Node/TypeScript consumer, with its own deployment and verification history.
Its [application](https://ai-software-toolkit-reference-app.navivision-account.workers.dev/)
and [scorecard](https://ravisingh11.github.io/ai-software-toolkit-reference-app/)
are published separately. Consult that repository for current deployment and CI
evidence; the local Python fixture below does not verify the deployed app.

## In-repository Python fixture

`examples/python-demo/` is the toolkit's executable consumer: a standard-library
Python application with the Guardrails runtime installed under its own
`.guardrails/` and the Core and GitHub profile workflows under
`.github/workflows/`. It exercises installation and the local runtime. Optional providers, functional
QA, and action skills require their own verification evidence.

## What it demonstrates today

| Capability | Where | Status |
| --- | --- | --- |
| Install and refresh | `tooling/install.py --target examples/python-demo --refresh-existing`; the repository's own tests (`tooling/tests/test_consumer_lifecycle.py`, `test_python_demo.py`) exercise install, refresh, and validation | Shipped and tested on every change |
| Local scan and scorecard | `tools/run_guardrails.py` supplies real build and test commands and runs `.guardrails/scan.py` | Shipped |
| CI workflows | The example's workflow copies are refreshed from `workflows/` and checked for parity; GitHub does not execute nested workflow files in this repository | Templates shipped; advisory configuration not live-verified by these copies |
| Ground truth | `.guardrails/ground-truth-ai.yaml` maps the demo's architecture, testing, security, and deployment documents | Shipped |
| Optional scorecard badge | `tools/` and the badge workflow described in the demo README | Shipped, opt-in |
| `ai-toolkit` CLI | `ai-toolkit init` on a copy of the demo adopts the existing installation and records `toolkit.toml` / `toolkit.lock.json`; `check` and `doctor` run against it | Shipped; the committed demo does not yet carry the two files (see below) |
| Provider adapters | `.guardrails/adapter.py` is installed; the Snyk and FOSSA templates are not copied into the demo because it has no vendor accounts | Adapter shipped; live runs unverified (see the [ledger](providers/verification.md)) |
| Functional QA | Not generated for the demo | Planned |
| Repair via an action skill | Not demonstrated | Planned (needs a recorded run per client, see each skill's `VERIFICATION.md`) |
| Node reference app | Separate Fieldnotes repository linked above | Independently maintained; not verified by this fixture |

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
toolkit_root="$PWD" # Run from the toolkit repository root.
demo_root="$(mktemp -d)"
cp -R examples/python-demo/. "$demo_root/"
cd "$demo_root"
git init -q
git add -A
git -c user.name="Toolkit Demo" -c user.email="demo@example.invalid" commit -qm demo
python3 "$toolkit_root/tooling/ai_toolkit" init --target . --yes --clients codex
python3 "$toolkit_root/tooling/ai_toolkit" doctor --target .
```

The demo's own [README](../examples/python-demo/README.md) covers the
scorecard output, the GitHub profile, and badges.
