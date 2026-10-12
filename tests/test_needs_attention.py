from __future__ import annotations

from datetime import date

from worksync.work.command_center import build_section, needs_attention, section_state
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 12)
GENERATED_AT = "2026-10-12T12:00:00Z"


def test_needs_attention_maps_and_filters_attention_items_in_source_order(vault, write_note) -> None:
    write_note(
        vault,
        "Tickets/blocked.md",
        "---\ntype: ticket\nstatus: blocked\nticket_id: blocked-1\n---\n# Blocked\n",
    )
    write_note(
        vault,
        "Tickets/manager.md",
        "---\ntype: ticket\nstatus: in_progress\nticket_id: manager-1\nmanager_attention: true\n"
        "assignee: '[[Myles]]'\npriority: P2\nlast_checked: 2026-10-11\n---\n# Manager\n",
    )
    write_note(
        vault,
        "Actions/overdue.md",
        "---\ntype: action\nstatus: open\naction_id: action-1\ndue: 2026-10-11\npriority: P1\n---\n# Overdue action\n",
    )
    write_note(
        vault,
        "Tickets/normal.md",
        "---\ntype: ticket\nstatus: open\nticket_id: normal-1\nassignee: '[[Myles]]'\n"
        "last_checked: 2026-10-11\n---\n# Normal\n",
    )
    index = WorkIndex.from_vault(vault)

    result = needs_attention(index, TODAY, generated_at=GENERATED_AT)

    assert result.section_id == "needs_attention"
    assert result.generated_at == GENERATED_AT
    assert result.effective_filters == {"kinds": ["overdue_action", "blocked", "manager_attention"]}
    assert [
        (
            item.entity_id,
            item.entity_type,
            item.status,
            item.label,
            item.path,
            item.reason,
            item.priority,
            item.attention,
        )
        for item in result.items
    ] == [
        (
            "action-1",
            "action",
            "open",
            "Overdue action",
            "Actions/overdue.md",
            "Overdue since 2026-10-11",
            "P1",
            ("overdue_action",),
        ),
        (
            "blocked-1",
            "ticket",
            "blocked",
            "Blocked",
            "Tickets/blocked.md",
            "Ticket is blocked",
            None,
            ("blocked",),
        ),
        (
            "manager-1",
            "ticket",
            "in_progress",
            "Manager",
            "Tickets/manager.md",
            "Flagged for manager attention",
            "P2",
            ("manager_attention",),
        ),
    ]
    assert result.total_count == 3


def test_needs_attention_aggregates_signals_to_one_row_per_entity(vault, write_note) -> None:
    write_note(
        vault,
        "Tickets/blocked-flagged.md",
        "---\ntype: ticket\nstatus: blocked\nticket_id: blocked-flagged-1\nmanager_attention: true\n"
        "priority: P1\nlast_checked: 2026-10-10\n---\n# Blocked and flagged\n",
    )
    index = WorkIndex.from_vault(vault)

    result = needs_attention(index, TODAY, generated_at=GENERATED_AT)

    assert result.total_count == 1
    assert len(result.items) == 1
    (item,) = result.items
    assert item.entity_id == "blocked-flagged-1"
    assert item.entity_type == "ticket"
    assert item.status == "blocked"
    assert item.label == "Blocked and flagged"
    assert item.path == "Tickets/blocked-flagged.md"
    assert item.reason == "Ticket is blocked"
    assert item.priority == "P1"
    assert item.attention == ("blocked", "manager_attention")
    assert result.effective_filters == {"kinds": ["blocked", "manager_attention"]}


def test_needs_attention_items_carry_entity_timestamps(vault, write_note) -> None:
    write_note(
        vault,
        "Tickets/blocked.md",
        "---\ntype: ticket\nstatus: blocked\nticket_id: blocked-1\nlast_checked: 2026-10-10\n---\n# Blocked\n",
    )
    write_note(
        vault,
        "Actions/overdue.md",
        "---\ntype: action\nstatus: open\naction_id: action-1\ndue: 2026-10-01\n---\n# Overdue action\n",
    )
    index = WorkIndex.from_vault(vault)

    result = needs_attention(index, TODAY, generated_at=GENERATED_AT)

    assert {item.path: item.timestamps for item in result.items} == {
        "Tickets/blocked.md": (("last_checked", "2026-10-10"),),
        "Actions/overdue.md": (("due", "2026-10-01"),),
    }


def test_needs_attention_empty_vault_has_empty_section_state(vault) -> None:
    result = needs_attention(WorkIndex.from_vault(vault), TODAY, generated_at=GENERATED_AT)

    assert section_state(result) == "empty"
    assert result.items == ()


def test_unavailable_section_state_uses_build_section(vault) -> None:
    result = build_section(
        "needs_attention",
        (),
        generated_at=GENERATED_AT,
        availability="unavailable",
        error_state="source_unavailable",
    )

    assert section_state(result) == "unavailable"
