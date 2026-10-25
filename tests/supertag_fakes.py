"""Shared builders for supertag tests.

Kept in one place because the registry, instance, API, and e2e suites all need the same
definition-note shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from prioritization_fakes import action_note

FOLDER = "6. Templates/Supertags"


def field_yaml(
    name: str,
    key: str,
    type_: str,
    *,
    options: tuple[str, ...] = (),
    default: object | None = None,
    required: bool | None = None,
    optional: bool | None = None,
    target: str | None = None,
) -> str:
    """Render one field entry for a supertag definition's YAML frontmatter."""
    lines = [f"  - name: {name}", f"    key: {key}", f"    type: {type_}"]
    if options:
        lines.append("    options: [" + ", ".join(options) + "]")
    if default is not None:
        lines.append(f"    default: {json.dumps(default) if isinstance(default, str) else default}")
    if required is not None:
        lines.append(f"    required: {str(required).lower()}")
    if optional is not None:
        lines.append(f"    optional: {str(optional).lower()}")
    if target is not None:
        lines.append(f"    target: {target}")
    return "\n".join(lines) + "\n"


def write_definition(
    write_note,
    vault: Path,
    filename: str,
    *,
    tag_id: str = "design-task",
    name: str = "Design Task",
    base: str = "task",
    extends: str | None = "task",
    color: str = "blue",
    fields: str = "",
) -> None:
    """Write one supertag definition note into the conventional folder."""
    lines = ["---", "type: supertag"]
    if tag_id:
        lines.append(f"supertag_id: {tag_id}")
    lines.append(f"name: {name}")
    lines.append(f"base: {base}")
    if extends:
        lines.append(f"extends: {extends}")
    lines.append(f"color: {color}")
    if fields:
        lines.append("fields:")
        lines.append(fields.rstrip("\n"))
    else:
        lines.append("fields: []")
    lines.append("---")
    lines.append(f"# {name}")
    write_note(vault, f"{FOLDER}/{filename}.md", "\n".join(lines) + "\n")


def write_action(
    write_note,
    vault: Path,
    name: str,
    *,
    action_id: str = "a-1",
    status: str = "open",
    supertags: tuple[str, ...] = (),
    **fields: object,
) -> None:
    """Write one action note with optional supertags and quoted wikilink references."""
    lines = ["type: action", f"status: {status}", f"action_id: {action_id}"]
    if supertags:
        lines.append("supertags:")
        lines.extend(f"  - {tag}" for tag in supertags)
    for key, value in fields.items():
        text = str(value)
        if text.startswith("[[") and text.endswith("]]"):
            text = json.dumps(text)
        lines.append(f"{key}: {text}")
    write_note(vault, f"Actions/{name}.md", action_note("\n".join(lines) + "\n", f"# {name}"))
