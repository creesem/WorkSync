from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from datetime import date
from pathlib import Path

from worksync.context import service
from worksync.work.command_center import (
    SectionItem,
    build_section,
    section_item_to_dict,
    section_result_to_dict,
    section_state,
    timestamps_for_entity,
)
from worksync.work.models import Action, Project, Ticket, entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.review import attention_items

GENERATED_AT = "2026-02-01T09:00:00+00:00"


def _item() -> SectionItem:
    return SectionItem(
        entity_id="ticket-1",
        entity_type="ticket",
        status="blocked",
        label="Blocked ticket",
        path="Tickets/blocked.md",
        reason="Ticket is blocked",
        priority="P1",
        attention=("blocked",),
    )


def test_available_section_without_items_is_empty() -> None:
    result = build_section("needs_attention", (), generated_at="2026-10-11T12:00:00Z")

    assert section_state(result) == "empty"
    assert result.total_count == 0


def test_unavailable_section_is_unavailable_even_with_items() -> None:
    result = build_section(
        "needs_attention",
        (_item(),),
        generated_at="2026-10-11T12:00:00Z",
        availability="unavailable",
        error_state="source_unavailable",
    )

    assert section_state(result) == "unavailable"
    assert result.total_count == 1


def test_stale_section_with_items_is_stale() -> None:
    result = build_section(
        "needs_attention",
        (_item(),),
        generated_at="2026-10-11T12:00:00Z",
        source_freshness="stale",
    )

    assert section_state(result) == "stale"


def test_fresh_section_with_items_has_items_state() -> None:
    result = build_section(
        "needs_attention",
        (_item(),),
        generated_at="2026-10-11T12:00:00Z",
        source_freshness="fresh",
    )

    assert section_state(result) == "items"
    assert result.total_count == len(result.items) == 1


def test_entity_id_uses_canonical_ticket_id_and_path_fallback() -> None:
    ticket = Ticket(path="Tickets/ticket.md", title="Ticket", status="open", ticket_id="ticket-1")
    note = Ticket(path="Notes/note.md", title="Note", status="open")

    assert entity_id_of(ticket) == "ticket-1"
    assert entity_id_of(note) == "Notes/note.md"


def test_attention_items_carry_blocked_ticket_canonical_id(vault, write_note) -> None:
    write_note(
        vault,
        "Tickets/blocked.md",
        "---\ntype: ticket\nstatus: blocked\nticket_id: blocked-ticket\n---\n# Blocked ticket\n",
    )
    index = WorkIndex.from_vault(vault)

    blocked = next(item for item in attention_items(index, today=date(2026, 10, 11)) if item.kind == "blocked")

    assert blocked.entity_id == "blocked-ticket"


def test_section_items_carry_set_entity_timestamps_through_build_section() -> None:
    entities = (
        Project(path="Projects/p.md", title="Project", status="active", last_reviewed="2026-10-01"),
        Ticket(path="Tickets/t.md", title="Ticket", status="open", last_checked="2026-10-02"),
        Action(path="Actions/a.md", title="Action", status="open", due="2026-10-03"),
        Ticket(path="Tickets/unchecked.md", title="Unchecked", status="open"),
    )
    expected = (
        (("last_reviewed", "2026-10-01"),),
        (("last_checked", "2026-10-02"),),
        (("due", "2026-10-03"),),
        (),
    )
    items = tuple(replace(_item(), timestamps=timestamps_for_entity(entity)) for entity in entities)
    result = build_section("timestamps", items, generated_at="2026-10-11T12:00:00Z")

    assert tuple(item.timestamps for item in result.items) == expected


def test_section_item_timestamps_default_to_empty() -> None:
    assert _item().timestamps == ()


def test_section_item_to_dict_serializes_every_field_with_list_sequences() -> None:
    item = _item()

    data = section_item_to_dict(item)

    assert set(data) == {field.name for field in fields(item)}
    assert data == {
        "entity_id": "ticket-1",
        "entity_type": "ticket",
        "status": "blocked",
        "label": "Blocked ticket",
        "path": "Tickets/blocked.md",
        "reason": "Ticket is blocked",
        "priority": "P1",
        "attention": ["blocked"],
        "timestamps": [],
    }


def test_section_item_to_dict_turns_timestamps_into_lists() -> None:
    item = replace(_item(), timestamps=(("due", "2026-10-03"),))

    assert section_item_to_dict(item)["timestamps"] == [["due", "2026-10-03"]]


def test_section_result_to_dict_carries_every_field_plus_the_derived_state() -> None:
    result = build_section(
        "needs_attention",
        (_item(),),
        generated_at=GENERATED_AT,
        effective_filters={"kinds": ["blocked"]},
        source_freshness="fresh",
    )

    data = section_result_to_dict(result)

    assert set(data) == {field.name for field in fields(result)} | {"state"}
    assert data["section_id"] == "needs_attention"
    assert data["query_version"] == 1
    assert data["generated_at"] == GENERATED_AT
    assert data["effective_filters"] == {"kinds": ["blocked"]}
    assert data["total_count"] == 1
    assert data["source_freshness"] == "fresh"
    assert data["availability"] == "available"
    assert data["error_state"] is None
    assert data["state"] == section_state(result) == "items"
    assert data["items"] == [section_item_to_dict(result.items[0])]


def test_section_result_to_dict_carries_the_unavailable_state() -> None:
    result = build_section(
        "my_priorities",
        (),
        generated_at=GENERATED_AT,
        availability="unavailable",
        error_state="source_unavailable",
    )

    data = section_result_to_dict(result)

    assert data["state"] == "unavailable"
    assert data["availability"] == "unavailable"
    assert data["error_state"] == "source_unavailable"


def test_command_center_service_orders_and_serializes_the_three_sections(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    write_note(vault, "Tickets/blocked.md", "---\ntype: ticket\nstatus: blocked\n---\n# Blocked ticket\n")

    payload = service.command_center(vault, tmp_path / "var", date(2026, 2, 1), generated_at=GENERATED_AT)

    assert payload["generated_at"] == GENERATED_AT
    assert [section["section_id"] for section in payload["sections"]] == [
        "needs_attention",
        "my_priorities",
        "since_last_check",
    ]
    needs_attention, my_priorities, since_last_check = payload["sections"]
    assert needs_attention["state"] == "items"
    assert needs_attention["items"][0]["label"] == "Blocked ticket"
    assert my_priorities["state"] == "unavailable"
    assert since_last_check["state"] == "unavailable"
    assert since_last_check["error_state"] == "no_checkpoint"


def test_command_center_service_is_deterministic_for_one_injected_generated_at(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    write_note(vault, "Tickets/blocked.md", "---\ntype: ticket\nstatus: blocked\n---\n# Blocked ticket\n")

    first = service.command_center(vault, tmp_path / "var", date(2026, 2, 1), generated_at=GENERATED_AT)
    second = service.command_center(vault, tmp_path / "var", date(2026, 2, 1), generated_at=GENERATED_AT)

    assert first == second


def test_command_center_service_passes_owner_id_through_to_my_priorities(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    write_note(vault, "People/Dana.md", "---\ntype: person\nstatus: active\nperson_id: dana\n---\n# Dana\n")
    write_note(
        vault,
        "Actions/for-dana.md",
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Dana]]"\n---\n# Open action\n',
    )

    payload = service.command_center(
        vault, tmp_path / "var", date(2026, 2, 1), owner_id="dana", generated_at=GENERATED_AT
    )
    my_priorities = payload["sections"][1]

    assert my_priorities["availability"] == "available"
    assert my_priorities["effective_filters"] == {"owner_id": "dana"}
    assert my_priorities["total_count"] == 1
    assert my_priorities["items"][0]["label"] == "Open action"
