"""Supertag instances: applied tags, field validation, defaults, references, evolution."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from prioritization_fakes import action_note
from supertag_fakes import field_yaml as _field
from supertag_fakes import write_definition as _definition
from worksync.context import service
from worksync.inventory.parse import scan_vault
from worksync.work.generation import WorkGeneration
from worksync.work.models import entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.supertag_instances import validate_instance
from worksync.work.supertags import build_registry

PERSON = "---\ntype: person\nstatus: active\nperson_id: myles\n---\n# Myles\n"
PROJECT = "---\ntype: project\nstatus: active\nproject_id: portal\n---\n# Portal\n"


def _context(vault: Path):
    records = scan_vault(vault)
    return build_registry(records, vault, WorkGeneration()), WorkIndex.from_records(records, root=vault)


def _action(
    write_note,
    vault: Path,
    name: str,
    *,
    action_id: str = "a-1",
    supertags: tuple[str, ...] = (),
    **fields: object,
) -> None:
    lines = ["type: action", "status: open", f"action_id: {action_id}"]
    if supertags:
        lines.append("supertags:")
        lines.extend(f"  - {tag}" for tag in supertags)
    for key, value in fields.items():
        text = str(value)
        if text.startswith("[[") and text.endswith("]]"):
            text = json.dumps(text)
        lines.append(f"{key}: {text}")
    write_note(vault, f"Actions/{name}.md", action_note("\n".join(lines) + "\n", f"# {name}"))


def _design_definition(write_note, vault: Path, *, fields: str) -> None:
    _definition(write_note, vault, "Design Task", fields=fields)


def test_instance_parses_tags_and_uses_defaults(vault: Path, write_note) -> None:
    write_note(vault, "People/Myles.md", PERSON)
    _design_definition(
        write_note,
        vault,
        fields=(
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
        ),
    )
    _action(write_note, vault, "Design", supertags=("design-task",), design_phase="design", reviewer="[[Myles]]")
    registry, index = _context(vault)
    entity = index.list_type("action")[0]

    validation = validate_instance(registry, entity, index)

    assert entity.supertags == ("design-task",)
    assert validation.tag_ids == ("design-task",)
    assert validation.errors == ()
    assert validation.all_errors == ()
    instance = validation.tag_instance("design-task")
    assert instance is not None
    phase = instance.field("design_phase")
    assert phase is not None
    assert phase.value == "design"
    assert phase.effective == "design"
    review = instance.field("review_date")
    assert review is not None
    assert review.value is None
    assert review.effective is None
    status = instance.field("status")
    assert status is not None
    assert status.field.inherited is True
    assert status.field.source == "task"


def test_missing_required_field_is_reported(vault: Path, write_note) -> None:
    _design_definition(
        write_note,
        vault,
        fields=_field("Design phase", "design_phase", "select", options=("discovery",), required=True),
    )
    _action(write_note, vault, "Design", supertags=("design-task",))
    registry, index = _context(vault)
    entity = index.list_type("action")[0]

    validation = validate_instance(registry, entity, index)
    instance = validation.tag_instance("design-task")

    assert any("missing required field: design_phase" in error for error in instance.all_errors)
    assert validation.errors == ()


def test_field_types_and_references_are_validated(vault: Path, write_note) -> None:
    _design_definition(
        write_note,
        vault,
        fields=(
            _field("Phase", "phase", "select", options=("a", "b"))
            + _field("Review date", "review_date", "date")
            + _field("Flag", "flag", "checkbox")
            + _field("Count", "count", "number")
            + _field("Reviewer", "reviewer", "reference", target="person")
        ),
    )
    _action(
        write_note,
        vault,
        "Design",
        supertags=("design-task",),
        phase="c",
        review_date="not-a-date",
        flag='"yes"',
        count="many",
        reviewer="[[Nobody]]",
    )
    registry, index = _context(vault)
    entity = index.list_type("action")[0]

    validation = validate_instance(registry, entity, index)
    instance = validation.tag_instance("design-task")

    errors = "\n".join(instance.all_errors)
    warnings = "\n".join(instance.all_warnings)
    assert "phase must be one of a, b" in errors
    assert "review_date must be an ISO date" in errors
    assert "flag must be a boolean" in errors
    assert "count must be a number" in errors
    assert "unresolved reference" in warnings


def test_wrong_reference_type_is_an_error(vault: Path, write_note) -> None:
    write_note(vault, "Projects/Portal.md", PROJECT)
    _design_definition(
        write_note,
        vault,
        fields=_field("Reviewer", "reviewer", "reference", target="person"),
    )
    _action(write_note, vault, "Design", supertags=("design-task",), reviewer="[[Portal]]")
    registry, index = _context(vault)
    entity = index.list_type("action")[0]

    validation = validate_instance(registry, entity, index)
    instance = validation.tag_instance("design-task")

    assert any("expected person, found project" in error for error in instance.all_errors)


def test_unknown_and_base_mismatch_tags_are_reported(vault: Path, write_note) -> None:
    _definition(write_note, vault, "Ticket Tag", tag_id="ticket-tag", name="Ticket Tag", base="ticket", extends=None)
    _action(write_note, vault, "Design", supertags=("ticket-tag", "nope"))
    registry, index = _context(vault)
    entity = index.list_type("action")[0]

    validation = validate_instance(registry, entity, index)

    errors = "\n".join(validation.errors)
    assert "unknown supertag: nope" in errors
    assert "#ticket-tag has base ticket, not action" in errors


def test_malformed_supertags_are_reported(vault: Path, write_note) -> None:
    write_note(
        vault,
        "Actions/Bad.md",
        action_note("type: action\nstatus: open\naction_id: a-bad\nsupertags:\n  nested: value\n", "# Bad"),
    )
    registry, index = _context(vault)
    entity = index.list_type("action")[0]

    validation = validate_instance(registry, entity, index)

    assert validation.errors == ("supertags must be a list of ids",)


def test_multiple_tags_share_the_base_and_keep_their_fields(vault: Path, write_note) -> None:
    _design_definition(
        write_note, vault, fields=_field("Design phase", "design_phase", "select", options=("discovery",))
    )
    _definition(
        write_note,
        vault,
        "Vendor Followup",
        tag_id="vendor-followup",
        name="Vendor Followup",
        fields=_field("Vendor", "vendor", "text"),
    )
    _action(
        write_note,
        vault,
        "Design",
        supertags=("design-task", "vendor-followup"),
        design_phase="discovery",
        vendor="Eleos",
    )
    registry, index = _context(vault)
    entity = index.list_type("action")[0]

    validation = validate_instance(registry, entity, index)

    assert validation.tag_ids == ("design-task", "vendor-followup")
    assert validation.errors == ()
    assert validation.all_errors == ()
    design = validation.tag_instance("design-task")
    vendor = validation.tag_instance("vendor-followup")
    assert design.field("design_phase").value == "discovery"
    assert vendor.field("vendor").value == "Eleos"
    assert design.field("status").field.source == "task"
    assert vendor.field("status").field.source == "task"


def test_definition_evolution_revalidates_without_rewriting(vault: Path, write_note) -> None:
    _design_definition(
        write_note,
        vault,
        fields=_field("Design phase", "design_phase", "select", options=("discovery", "design")),
    )
    _action(write_note, vault, "Design", supertags=("design-task",), design_phase="design")
    action_path = vault / "Actions/Design.md"
    before = action_path.read_bytes()

    registry, index = _context(vault)
    entity = index.list_type("action")[0]
    assert validate_instance(registry, entity, index).all_errors == ()

    _design_definition(
        write_note,
        vault,
        fields=(
            _field("Design phase", "design_phase", "select", options=("build",), required=True)
            + _field("Review date", "review_date", "date", required=True)
        ),
    )
    registry, index = _context(vault)
    entity = index.list_type("action")[0]
    validation = validate_instance(registry, entity, index)
    instance = validation.tag_instance("design-task")

    errors = "\n".join(instance.all_errors)
    assert "design_phase must be one of build" in errors
    assert "missing required field: review_date" in errors
    assert action_path.read_bytes() == before


def test_entity_contract_exposes_tags_and_errors(vault: Path, write_note) -> None:
    _design_definition(
        write_note, vault, fields=_field("Design phase", "design_phase", "select", options=("discovery",))
    )
    _action(write_note, vault, "Design", supertags=("design-task",), design_phase="discovery")
    records = scan_vault(vault)
    index = WorkIndex.from_records(records, root=vault)
    entity = index.list_type("action")[0]
    runtime = vault.parent / "runtime"

    contract = service.entity_contract(vault, entity_id_of(entity), date(2026, 10, 25), runtime_root=runtime)

    assert contract is not None
    assert contract["supertags"] == ["design-task"]
    assert contract["supertag_errors"] == []
    assert contract["supertag_warnings"] == []
