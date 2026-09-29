#!/usr/bin/env python3
"""Keep shipped workflow templates in step with this repository's installed copies.

Dependabot bumps action pins only under .github/workflows, never in the shipped
templates under workflows/. This repository runs each template it also ships,
so every template with an installed copy must match it byte for byte, and every
action must use one pin across both directories.

  --check  (default) report drift and exit 1 when any is found
  --write  copy pin-only changes from installed copies into the templates and
           align the remaining templates' pins; refuse other differences
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Templates this repository ships but does not run itself. Every other template
# must have an identical copy in .github/workflows/.
NOT_INSTALLED = frozenset({
    "ai-toolkit-setup.yml",  # starter workflow for consuming repositories
    "security-scanning.yml",  # organization-style bundle; this repository runs the per-provider templates
    "soak.yml",  # awaits an environment-evidence producer
})
# Other checked-in installations and the installer workflow maps they must contain.
# The Python demo installs the Core and GitHub profiles.
EXTRA_COPIES = {Path("examples/python-demo/.github/workflows"): ("CORE_WORKFLOWS", "GITHUB_WORKFLOWS")}


def installer_workflows(root: Path, maps: tuple[str, ...]) -> list[str]:
    """Workflow names the installer copies for the given profile maps (tooling/install.py)."""
    if not (root / "tooling" / "install.py").is_file():
        return []
    spec = importlib.util.spec_from_file_location("proof_installer_inventory", root / "tooling" / "install.py")
    if spec is None or spec.loader is None:
        raise ValueError("cannot load tooling/install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return sorted({name for attribute in maps for name in getattr(module, attribute)})
# A reference is pinned only when the whole ref is a full commit SHA.
PINNED = re.compile(r"(?P<action>[^@\s]+)@(?P<ref>[0-9a-f]{40})")
COMMENT = re.compile(r"[ \t]*(#.*)?")


def _yaml():
    try:
        import yaml  # PyYAML ships with yamllint (tooling/requirements-lint.txt).
    except ImportError as error:
        raise SystemExit("PyYAML is required; install tooling/requirements-lint.txt") from error
    return yaml


def uses_nodes(text: str, name: str = "workflow") -> list:
    """The scalar nodes GitHub resolves as actions: jobs.<job>.uses and jobs.<job>.steps[*].uses.

    Nodes carry their exact text span, so every YAML layout (multi-line, flow, quoted) is
    read and rewritten the same way.
    """
    yaml = _yaml()
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as error:
        raise ValueError(f"{name} is not valid YAML: {error}") from error

    def field(node, key):
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
                    return value_node
        return None

    found = []
    jobs = field(root, "jobs")
    if isinstance(jobs, yaml.MappingNode):
        for _, job in jobs.value:
            candidates = [field(job, "uses")]
            steps = field(job, "steps")
            if isinstance(steps, yaml.SequenceNode):
                candidates += [field(step, "uses") for step in steps.value]
            found += [node for node in candidates if node is not None]
    # YAML aliases return the same node (and span) more than once; keep each span once, in order.
    unique = {(node.start_mark.index, node.end_mark.index): node for node in found}
    return [unique[span] for span in sorted(unique)]


def uses_values(path: Path) -> list[str]:
    """Every action reference in a workflow, from the parsed YAML."""
    return [node.value if isinstance(node.value, str) else repr(node.value)
            for node in uses_nodes(path.read_text(encoding="utf-8"), str(path))]


def _trailing_comment(text: str, index: int) -> tuple[int, str] | None:
    """(end of line, comment) when only whitespace or a comment follows `index`; None otherwise."""
    line_end = text.find("\n", index)
    line_end = len(text) if line_end == -1 else line_end
    match = COMMENT.fullmatch(text[index:line_end])
    return (line_end, (match.group(1) or "").strip()) if match else None


def symlinked(root: Path, path: Path) -> bool:
    """True when the file or any directory between it and the repository root is a symlink."""
    current = path
    while current != root and root in current.parents:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def workflow_files(directory: Path) -> list[Path]:
    """GitHub accepts both workflow suffixes."""
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def repository(action: str) -> str:
    """Sub-actions (for example github/codeql-action/init and /analyze) release together, so pin by repository."""
    return "/".join(action.split("/")[:2])


def pins(values: list[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for value in values:
        pinned = PINNED.fullmatch(value)
        if pinned:
            found.setdefault(repository(pinned["action"]), set()).add(pinned["ref"])
    return found


def _placeholders(text: str) -> str:
    """The text with every pinned reference and its version comment replaced, for pin-only comparisons."""
    for node in reversed(uses_nodes(text)):
        pinned = PINNED.fullmatch(node.value) if isinstance(node.value, str) else None
        if pinned:
            trailing = _trailing_comment(text, node.end_mark.index)
            end = trailing[0] if trailing else node.end_mark.index
            text = f"{text[:node.start_mark.index]}{pinned['action']}@PIN{text[end:]}"
    return text


def pin_only_difference(template: str, installed: str) -> bool:
    """True when the files differ only in the pins (and version comments) of the same actions."""
    try:
        return _placeholders(template) == _placeholders(installed)
    except ValueError:
        return False  # invalid YAML is never a pin-only difference


def chosen_pins(texts: list[str]) -> dict[str, tuple[str, str]]:
    """Each action's single installed pin with its version comment; ambiguous actions are left alone."""
    seen: dict[str, set[tuple[str, str]]] = {}
    for text in texts:
        for node in uses_nodes(text):
            pinned = PINNED.fullmatch(node.value) if isinstance(node.value, str) else None
            if pinned:
                trailing = _trailing_comment(text, node.end_mark.index)
                comment = trailing[1] if trailing else ""
                seen.setdefault(repository(pinned["action"]), set()).add((pinned["ref"], comment))
    chosen = {}
    for action, entries in seen.items():
        refs = {ref for ref, _ in entries}
        if len(refs) == 1:
            # Prefer a line that documents its version, for example "# v7.0.1".
            chosen[action] = max(entries, key=lambda entry: len(entry[1]))
    return chosen


def repin(text: str, chosen: dict[str, tuple[str, str]]) -> str:
    """Rewrite each pinned action to the chosen SHA and version comment, at its parsed location."""
    for node in reversed(uses_nodes(text)):
        pinned = PINNED.fullmatch(node.value) if isinstance(node.value, str) else None
        key = repository(pinned["action"]) if pinned else None
        if not pinned or key not in chosen or pinned["ref"] == chosen[key][0]:
            continue
        ref, comment = chosen[key]
        start, end = node.start_mark.index, node.end_mark.index
        # The span may include quotes or a line break; replace only the SHA inside it.
        value = text[start:end].replace(pinned["ref"], ref, 1)
        trailing = _trailing_comment(text, end)
        if trailing:
            # Block style: the version comment travels with the pin.
            text = f"{text[:start]}{value}{' ' + comment if comment else ''}{text[trailing[0]:]}"
        else:
            # Flow style: other mapping content follows on the line, so only the SHA changes.
            text = f"{text[:start]}{value}{text[end:]}"
    return text


def copies(root: Path) -> list[Path]:
    """Every checked-in copy of a template: the expected installed copies plus existing extra copies."""
    templates = workflow_files(root / "workflows")
    found = [root / ".github" / "workflows" / path.name for path in templates if path.name not in NOT_INSTALLED]
    for directory, maps in EXTRA_COPIES.items():
        found += [root / directory / name for name in installer_workflows(root, maps)]
    return found


def drift(root: Path = ROOT) -> list[str]:
    templates = {path.name: path for path in workflow_files(root / "workflows")}
    installed = {path.name: path for path in workflow_files(root / ".github" / "workflows")}
    problems = [f"{name}: listed as not installed but .github/workflows/{name} exists"
                for name in sorted(NOT_INSTALLED & set(installed))]
    every = [*templates.values(), *installed.values(), *(copy for copy in copies(root) if copy.exists() or copy.is_symlink())]
    linked = [path for path in every if symlinked(root, path)]
    if linked:
        # Never read or compare through a link; the files it points at are not the workflows.
        return problems + [f"{path.relative_to(root)}: is or sits under a symlink; replace it with a regular file" for path in linked]
    for copy in copies(root):
        relative = copy.relative_to(root)
        if not copy.is_file():
            problems.append(f"{relative}: expected copy of workflows/{copy.name} is missing")
        elif copy.read_bytes() != templates[copy.name].read_bytes():
            problems.append(f"{relative}: differs from workflows/{copy.name}")
    combined: dict[str, set[str]] = {}
    for path in [*templates.values(), *installed.values()]:
        values = uses_values(path)
        for target in values:
            # Local actions and container images are not pinned by commit; every remote action must be.
            if not PINNED.fullmatch(target) and not target.startswith(("./", "docker://")):
                problems.append(f"{path.relative_to(root)}: {target} is not pinned to a full commit SHA")
        for action, refs in pins(values).items():
            combined.setdefault(action, set()).update(refs)
    problems += [f"{action}: pinned to {len(refs)} different SHAs" for action, refs in sorted(combined.items()) if len(refs) > 1]
    return problems


def write(root: Path = ROOT) -> list[str]:
    """Apply pin-only updates; return the differences that need a human."""
    templates = {path.name: path for path in workflow_files(root / "workflows")}
    installed = {path.name: path for path in workflow_files(root / ".github" / "workflows")}
    every = [*templates.values(), *installed.values(), *(copy for copy in copies(root) if copy.exists() or copy.is_symlink())]
    linked = [path for path in every if symlinked(root, path)]
    if linked:
        return [f"{path.relative_to(root)}: is or sits under a symlink; refusing to write" for path in linked]
    refused = []
    for name in sorted((set(templates) & set(installed)) - NOT_INSTALLED):
        template_text = templates[name].read_text(encoding="utf-8")
        installed_text = installed[name].read_text(encoding="utf-8")
        if template_text == installed_text:
            continue
        if pin_only_difference(template_text, installed_text):
            templates[name].write_text(installed_text, encoding="utf-8")
        else:
            refused.append(f"{name}: differs beyond action pins; reconcile it by hand")
    # Installed copies are what Dependabot keeps current, so their pin wins for every template.
    chosen = chosen_pins([path.read_text(encoding="utf-8") for path in installed.values()])
    for name, path in templates.items():
        text = path.read_text(encoding="utf-8")
        updated = repin(text, chosen)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
    # Extra copies (the demo) follow their template once it is current.
    for directory, maps in EXTRA_COPIES.items():
        for copy in (root / directory / name for name in installer_workflows(root, maps)):
            template = templates.get(copy.name)
            if template and copy.is_file() and copy.read_bytes() != template.read_bytes():
                if pin_only_difference(copy.read_text(encoding="utf-8"), template.read_text(encoding="utf-8")):
                    copy.write_bytes(template.read_bytes())
                else:
                    refused.append(f"{copy.relative_to(root)}: differs beyond action pins; reconcile it by hand")
    return refused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="apply pin-only updates to the templates")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        refused = write(args.root) if args.write else []
        problems = [*refused, *drift(args.root)]
    except ValueError as error:
        problems = [str(error)]
    for problem in dict.fromkeys(problems):
        print(f"DRIFT {problem}", file=sys.stderr)
    if problems:
        return 1
    print("Workflow templates match their installed copies and every action has one pin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
