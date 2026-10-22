from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, date, datetime
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
from worksync.work.override import overrides_path
from worksync.work.override_store import save_override
from worksync.work.prioritization import OverrideConflict
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
        "override_kind": None,
        "band": None,
        "owner": None,
        "owner_id": None,
        "due": None,
        "severity": None,
    }


def test_section_item_to_dict_turns_timestamps_into_lists() -> None:
    item = replace(_item(), timestamps=(("due", "2026-10-03"),))

    assert section_item_to_dict(item)["timestamps"] == [["due", "2026-10-03"]]


def test_section_item_to_dict_emits_the_override_kind_and_band() -> None:
    item = replace(_item(), override_kind="pin", band=-1)

    data = section_item_to_dict(item)

    assert data["override_kind"] == "pin"
    assert data["band"] == -1


def test_section_item_override_and_band_default_to_none() -> None:
    assert _item().override_kind is None
    assert _item().band is None


def test_section_result_to_dict_emits_conflicts_as_records() -> None:
    result = build_section(
        "my_priorities",
        (_item(),),
        generated_at=GENERATED_AT,
        conflicts=(
            OverrideConflict(
                override_id="ticket-1",
                entity_id="ticket-1",
                kind="defer",
                evidence="blocked",
                detail="Cannot defer ticket-1: blocked",
            ),
        ),
    )

    data = section_result_to_dict(result)

    assert data["conflicts"] == [
        {
            "override_id": "ticket-1",
            "entity_id": "ticket-1",
            "kind": "defer",
            "evidence": "blocked",
            "detail": "Cannot defer ticket-1: blocked",
        }
    ]


def test_section_result_conflicts_default_to_empty() -> None:
    assert build_section("needs_attention", (), generated_at=GENERATED_AT).conflicts == ()


def test_section_result_to_dict_carries_every_field_plus_the_derived_state() -> None:
    result = build_section(
        "needs_attention",
        (_item(),),
        generated_at=GENERATED_AT,
        effective_filters={"kinds": ["blocked"]},
        source_freshness="fresh",
    )

    data = section_result_to_dict(result)

    assert set(data) == {field.name for field in fields(result)} | {"state", "title", "subtitle"}
    assert data["section_id"] == "needs_attention"
    assert data["title"] == "Needs Attention"
    assert data["subtitle"] == "Blocked, overdue, and manager-flagged work"
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


def _seed_owner_work(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    write_note(vault, "People/Dana.md", "---\ntype: person\nstatus: active\nperson_id: dana\n---\n# Dana\n")
    write_note(
        vault,
        "Actions/Overdue.md",
        (
            "---\n"
            "type: action\n"
            "status: open\n"
            "action_id: overdue-action\n"
            "priority: P1\n"
            "due: 2026-01-25\n"
            'owners:\n  - "[[Dana]]"\n'
            "---\n"
            "# Overdue action\n"
        ),
    )
    write_note(
        vault,
        "Actions/Quiet.md",
        '---\ntype: action\nstatus: open\naction_id: quiet-action\nowners:\n  - "[[Dana]]"\n---\n# Quiet action\n',
    )


def test_command_center_service_threads_a_saved_pin_into_my_priorities(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    _seed_owner_work(vault, write_note)
    runtime = tmp_path / "var"
    save_override(vault, runtime, "quiet-action", "pin", reason="the exec asked", now=datetime(2026, 2, 1, tzinfo=UTC))

    payload = service.command_center(vault, runtime, date(2026, 2, 1), owner_id="dana", generated_at=GENERATED_AT)
    my_priorities = payload["sections"][1]

    assert [item["label"] for item in my_priorities["items"]] == ["Quiet action", "Overdue action"]
    assert my_priorities["items"][0]["override_kind"] == "pin"
    assert my_priorities["items"][0]["band"] == -1
    assert my_priorities["items"][1]["override_kind"] is None
    assert my_priorities["conflicts"] == []


def test_command_center_service_degrades_to_no_overrides_when_the_file_is_malformed(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    _seed_owner_work(vault, write_note)
    runtime = tmp_path / "var"
    target = overrides_path(runtime)
    target.parent.mkdir(parents=True)
    target.write_text("{not valid json", encoding="utf-8")

    payload = service.command_center(vault, runtime, date(2026, 2, 1), owner_id="dana", generated_at=GENERATED_AT)
    my_priorities = payload["sections"][1]

    assert my_priorities["availability"] == "available"
    assert [item["label"] for item in my_priorities["items"]] == ["Overdue action", "Quiet action"]
    assert all(item["override_kind"] is None for item in my_priorities["items"])
    assert my_priorities["conflicts"] == []
    assert payload["overrides"] == []
    assert target.read_text(encoding="utf-8") == "{not valid json"


def test_command_center_service_reports_overrides_whose_row_left_every_section(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    """F1: not_relevant drops the row, so the payload must still name it to make it clearable."""
    _seed_owner_work(vault, write_note)
    runtime = tmp_path / "var"
    now = datetime(2026, 2, 1, tzinfo=UTC)
    save_override(vault, runtime, "quiet-action", "not_relevant", reason="noise", now=now)
    save_override(vault, runtime, "ghost-action", "pin", now=now)

    payload = service.command_center(vault, runtime, date(2026, 2, 1), owner_id="dana", generated_at=GENERATED_AT)
    my_priorities = payload["sections"][1]

    assert [item["label"] for item in my_priorities["items"]] == ["Overdue action"]
    assert payload["overrides"] == [
        {
            "target_id": "quiet-action",
            "kind": "not_relevant",
            "reason": "noise",
            "label": "Quiet action",
            "path": "Actions/Quiet.md",
        },
        # A target that is no longer in the vault stays listed and clearable by its id.
        {
            "target_id": "ghost-action",
            "kind": "pin",
            "reason": "",
            "label": "ghost-action",
            "path": "",
        },
    ]
