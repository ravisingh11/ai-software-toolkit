# Engineering Standards Spec Kit Preset

This preset layers engineering-standards guidance onto upstream Spec Kit without
forking or vendoring Spec Kit core templates. It is intended for feature work
that benefits from durable specifications, technical plans, task breakdowns,
and release evidence.

## Install For Development

From a Spec Kit initialized repository:

```bash
specify preset add --dev /path/to/ai-software-toolkit/tooling/speckit/engineering-standards --priority 5
specify preset list
specify preset resolve spec-template
```

## Package

From the engineering standards repository:

```bash
tooling/package-speckit-preset.sh
```

The package is written to:

```text
dist/spec-kit-preset-engineering-standards-v1.0.0.zip
```

## Install From Package

```bash
specify preset add --from https://github.com/ravisingh11/ai-software-toolkit/releases/download/v2.2.1/spec-kit-preset-engineering-standards-v1.0.0.zip --priority 5
```

`--from` requires an HTTPS URL. Use `--dev` for local development installs.

## What This Preset Adds

- Issue linkage and acceptance evidence expectations.
- Cross-client parity and contract drift checks.
- Security, privacy, error-handling, and observability prompts.
- Release gate and release evidence requirements.
- CI-neutral validation language that follows each repository's chosen release
  process.

## License

MIT License. This preset integrates with GitHub Spec Kit but does not copy Spec
Kit source code or templates.
