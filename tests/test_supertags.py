"""Supertag registry: definitions, inheritance, validation, and live/legacy counts."""

from __future__ import annotations

import json
from pathlib import Path

from prioritization_fakes import action_note, ticket_note
from worksync.inventory.parse import scan_vault
from worksync.work.generation import WorkGeneration
from worksync.work.supertags import build_registry

FOLDER = "6. Templates/Supertags"


def _field(
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


def _definition(
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


def _registry(vault: Path, generation: WorkGeneration | None = None):
    return build_registry(scan_vault(vault), vault, generation or WorkGeneration())


def test_builtins_are_synthesized() -> None:
    registry = build_registry((), Path("."), WorkGeneration())

    assert [tag.id for tag in registry.supertags] == ["task", "ticket", "project", "meeting", "person"]
    task = registry.get("task")
    assert task is not None
    assert task.builtin is True
    assert task.entity_type == "action"
    assert task.errors == ()
    status = task.field("status")
    assert status is not None
    assert status.required is True
    assert status.inherited is False
    assert status.source == "task"
    assert "open" in status.options
    assert registry.selectable("action") == ()


def test_custom_definition_inherits_base_fields(vault: Path, write_note) -> None:
    fields = (
        _field(
            "Design phase",
            "design_phase",
            "select",
            options=("discovery", "design"),
            default="discovery",
            required=True,
        )
        + _field("Review date", "review_date", "date")
        + _field("Reviewer", "reviewer", "reference", target="person")
    )
    _definition(write_note, vault, "Design Task", fields=fields)

    registry = _registry(vault)

    tag = registry.get("design-task")
    assert tag is not None
    assert tag.errors == ()
    assert tag.base == "task"
    assert tag.entity_type == "action"
    status = tag.field("status")
    assert status is not None
    assert status.inherited is True
    assert status.source == "task"
    phase = tag.field("design_phase")
    assert phase is not None
    assert phase.inherited is False
    assert phase.source == "design-task"
    assert phase.default == "discovery"
    assert phase.required is True
    assert registry.selectable("action") == (tag,)


def test_inheritance_chain_and_default_override(vault: Path, write_note) -> None:
    _definition(
        write_note,
        vault,
        "Design",
        fields=_field(
            "Design phase",
            "design_phase",
            "select",
            options=("discovery", "design"),
            default="discovery",
            required=True,
        ),
    )
    _definition(
        write_note,
        vault,
        "UX",
        tag_id="ux-task",
        name="UX Task",
        extends="design-task",
        fields=_field("Design phase", "design_phase", "select", options=("discovery", "design"), default="design"),
    )

    tag = _registry(vault).get("ux-task")

    assert tag is not None
    assert tag.errors == ()
    phase = tag.field("design_phase")
    assert phase is not None
    assert phase.inherited is True
    assert phase.source == "design-task"
    assert phase.default == "design"
    assert phase.required is True


def test_child_cannot_change_inherited_field(vault: Path, write_note) -> None:
    _definition(
        write_note,
        vault,
        "Bad",
        tag_id="bad-task",
        name="Bad Task",
        fields=_field("Status", "status", "text"),
    )

    tag = _registry(vault).get("bad-task")

    assert tag is not None
    assert any("cannot change" in error for error in tag.errors)


def test_cycle_is_reported(vault: Path, write_note) -> None:
    _definition(write_note, vault, "A", tag_id="a-task", name="A Task", extends="b-task")
    _definition(write_note, vault, "B", tag_id="b-task", name="B Task", extends="a-task")

    registry = _registry(vault)

    for tag_id in ("a-task", "b-task"):
        tag = registry.get(tag_id)
        assert tag is not None
        assert any("cycle" in error for error in tag.errors)
    assert registry.get("task") is not None
    assert registry.get("task").errors == ()


def test_duplicate_id_is_isolated(vault: Path, write_note) -> None:
    _definition(write_note, vault, "A", tag_id="design-task", name="Design A")
    _definition(write_note, vault, "B", tag_id="design-task", name="Design B")

    registry = _registry(vault)
    tags = [tag for tag in registry.supertags if tag.id.startswith("design-task")]

    assert len(tags) == 2
    valid = next(tag for tag in tags if tag.id == "design-task")
    duplicate = next(tag for tag in tags if tag.id != "design-task")
    assert valid.errors == ()
    assert any("duplicate supertag_id" in error for error in duplicate.errors)
    assert registry.get("task").errors == ()


def test_invalid_definition_does_not_break_others(vault: Path, write_note) -> None:
    _definition(write_note, vault, "Bad", tag_id="bad", name="Bad", base="nope", fields=_field("Thing", "thing", "wat"))
    _definition(write_note, vault, "Good", tag_id="good", name="Good")

    registry = _registry(vault)

    assert registry.get("bad").errors
    assert registry.get("good").errors == ()
    assert registry.get("task").errors == ()


def test_missing_id_is_surfaced_with_a_synthetic_key(vault: Path, write_note) -> None:
    _definition(write_note, vault, "No Id", tag_id="", name="No Id")

    registry = _registry(vault)
    invalid = next(tag for tag in registry.supertags if tag.id.startswith("invalid-"))

    assert any("missing supertag_id" in error for error in invalid.errors)


def test_invalid_fields_are_reported(vault: Path, write_note) -> None:
    fields = (
        _field("Bad Key", "Bad Key", "text")
        + _field("Reserved", "type", "text")
        + _field("No options", "phase", "select")
        + _field("Bad default", "when", "date", default="not-a-date")
        + _field("Both", "both", "text", required=True, optional=True)
        + _field("Bad target", "who", "reference", target="planet")
        + _field("Good", "good", "text")
    )
    _definition(write_note, vault, "Broken", fields=fields)

    tag = _registry(vault).get("design-task")

    assert tag is not None
    errors = "\n".join(tag.errors)
    assert "invalid key" in errors
    assert "reserved key" in errors
    assert "select needs" in errors
    assert "default must be an ISO date" in errors
    assert "required and optional" in errors
    assert "invalid reference target" in errors
    assert tag.field("good") is not None


def test_name_defaults_to_the_note_title(vault: Path, write_note) -> None:
    write_note(
        vault,
        f"{FOLDER}/Design Task.md",
        "---\ntype: supertag\nsupertag_id: design-task\nbase: task\nextends: task\nfields: []\n---\n# Design Task\n",
    )

    tag = _registry(vault).get("design-task")

    assert tag is not None
    assert tag.name == "Design Task"


def test_unknown_extends_and_base_mismatch(vault: Path, write_note) -> None:
    _definition(write_note, vault, "Missing", tag_id="missing-parent", name="Missing Parent", extends="nope")
    _definition(write_note, vault, "Mismatch", tag_id="mismatch", name="Mismatch", base="ticket", extends="task")

    registry = _registry(vault)

    assert any("unknown extends" in error for error in registry.get("missing-parent").errors)
    assert any("base mismatch" in error for error in registry.get("mismatch").errors)


def test_same_key_across_tags_conflicts_or_shares(vault: Path, write_note) -> None:
    _definition(
        write_note,
        vault,
        "Vendor A",
        tag_id="vendor-a",
        name="Vendor A",
        fields=_field("Vendor", "vendor", "text"),
    )
    _definition(
        write_note,
        vault,
        "Vendor B",
        tag_id="vendor-b",
        name="Vendor B",
        fields=_field("Vendor name", "vendor", "text"),
    )
    _definition(
        write_note,
        vault,
        "Vendor C",
        tag_id="vendor-c",
        name="Vendor C",
        fields=_field("Vendor", "vendor", "text"),
    )

    registry = _registry(vault)

    assert any("field_conflict" in error for error in registry.get("vendor-a").errors)
    assert any("field_conflict" in error for error in registry.get("vendor-b").errors)
    assert registry.get("vendor-c").errors == ()


def test_counts_are_live_and_legacy_aware(vault: Path, write_note) -> None:
    _definition(write_note, vault, "Design Task", tag_id="design-task")
    write_note(
        vault,
        "Actions/Old.md",
        action_note("type: action\nstatus: open\naction_id: a-old\nsupertags:\n  - design-task\n", "# Old"),
    )
    write_note(
        vault,
        "Actions/Live.md",
        action_note("type: action\nstatus: open\naction_id: a-live\nsupertags:\n  - design-task\n", "# Live"),
    )
    write_note(vault, "Tickets/T.md", ticket_note("type: ticket\nstatus: open\nticket_id: t-1\n", "# Ticket"))
    generation = WorkGeneration(
        generation=2,
        legacy_action_ids=("a-old",),
        legacy_action_paths=("Actions/Old.md",),
        legacy_ticket_ids=(),
        legacy_ticket_paths=(),
    )

    registry = _registry(vault, generation)

    assert (registry.get("task").instance_count, registry.get("task").legacy_count) == (1, 1)
    assert (registry.get("design-task").instance_count, registry.get("design-task").legacy_count) == (1, 1)
    assert (registry.get("ticket").instance_count, registry.get("ticket").legacy_count) == (1, 0)


def test_registry_is_read_only(vault: Path, write_note) -> None:
    _definition(write_note, vault, "Design Task")
    before = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*") if path.is_file()}

    _registry(vault)

    after = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    assert after == before
