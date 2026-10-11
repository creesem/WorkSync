"""Ticket 03: entity detection and construction, including legacy ``task``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.inventory.parse import parse_note
from worksync.work.models import Action, EntityType, Person, Project
from worksync.work.schema import detect_type, entity_from_record, normalize_priority, person_id_slug


def _record(vault: Path, write_note: Callable[..., Path], relative: str, text: str):
    return parse_note(write_note(vault, relative, text), vault)


def test_detect_type_selects_the_five_entities() -> None:
    for value in ("project", "person", "ticket", "meeting", "action"):
        assert detect_type(value) == value


def test_detect_type_unknown_and_absent_are_none() -> None:
    assert detect_type("reference") is None
    assert detect_type(None) is None
    assert detect_type(123) is None


def test_legacy_task_maps_to_action() -> None:
    assert detect_type("task") == "action"
    assert detect_type('"task"') == "action"


def test_normalize_priority_maps_legacy_and_canonical() -> None:
    assert normalize_priority(1) == "P1"
    assert normalize_priority("2") == "P2"
    assert normalize_priority(5) == "P4"
    assert normalize_priority("P3") == "P3"
    assert normalize_priority("medium") is None
    assert normalize_priority("") is None
    assert normalize_priority(None) is None


def test_project_entity_reads_plural_owners(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(
        vault,
        write_note,
        "p.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles Creese]]"\npriority: P1\n---\n# Project X\n',
    )
    entity = entity_from_record(record)
    assert isinstance(entity, Project)
    assert entity.entity_type is EntityType.PROJECT
    assert entity.owners == ("[[Myles Creese]]",)
    assert entity.priority == "P1"


def test_legacy_task_entity_normalizes_status_and_priority(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(
        vault,
        write_note,
        "t.md",
        '---\ntype: task\nstatus: todo\npriority: 2\nowners:\n  - "[[Venkat]]"\n---\n# Do thing\n',
    )
    entity = entity_from_record(record)
    assert isinstance(entity, Action)
    assert entity.status == "open"
    assert entity.priority == "P2"
    assert entity.owners == ("[[Venkat]]",)


def test_meeting_attendees_accept_legacy_people(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(
        vault,
        write_note,
        "m.md",
        '---\ntype: meeting\nstatus: held\ndate: 2026-01-01\npeople:\n  - "[[Tracy]]"\n---\n# M\n',
    )
    entity = entity_from_record(record)
    assert entity is not None
    assert entity.attendees == ("[[Tracy]]",)


def test_non_entity_type_is_skipped(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(vault, write_note, "r.md", "---\ntype: reference\n---\n# Ref\n")
    assert entity_from_record(record) is None


def test_person_entity_reads_person_id(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(
        vault,
        write_note,
        "p.md",
        "---\ntype: person\nstatus: active\nperson_id: carlos-barnes\n---\n# Carlos Barnes\n",
    )
    entity = entity_from_record(record)
    assert isinstance(entity, Person)
    assert entity.person_id == "carlos-barnes"


def test_person_without_person_id_has_none(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(vault, write_note, "p.md", "---\ntype: person\nstatus: active\n---\n# Venkat\n")
    entity = entity_from_record(record)
    assert isinstance(entity, Person)
    assert entity.person_id is None


def test_person_id_slug_is_kebab_case() -> None:
    assert person_id_slug("Carlos Barnes") == "carlos-barnes"
    assert person_id_slug("Tracy O'Brien") == "tracy-o-brien"
    assert person_id_slug("  Venkat  ") == "venkat"
