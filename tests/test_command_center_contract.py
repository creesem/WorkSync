from __future__ import annotations

from dataclasses import replace
from datetime import date

from worksync.work.command_center import SectionItem, build_section, section_state, timestamps_for_entity
from worksync.work.models import Action, Project, Ticket, entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.review import attention_items


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
