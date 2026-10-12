from __future__ import annotations

from datetime import date

from worksync.work.command_center import my_priorities, section_state
from worksync.work.repository import WorkIndex


def _owner_notes(vault, write_note) -> None:
    write_note(vault, "People/Carlos.md", "---\ntype: person\nstatus: active\nperson_id: carlos\n---\n# Carlos\n")


def test_my_priorities_lists_open_owned_work_in_priority_order(vault, write_note) -> None:
    _owner_notes(vault, write_note)
    write_note(
        vault,
        "Actions/Overdue.md",
        (
            "---\n"
            "type: action\n"
            "status: open\n"
            "action_id: overdue-action\n"
            "priority: P1\n"
            "due: 2026-10-10\n"
            'owners:\n  - "[[Carlos]]"\n'
            "---\n"
            "# Overdue action\n"
        ),
    )
    write_note(
        vault,
        "Tickets/Blocked.md",
        (
            "---\n"
            "type: ticket\n"
            "status: blocked\n"
            "ticket_id: blocked-ticket\n"
            "priority: P2\n"
            'assignee: "[[Carlos]]"\n'
            "manager_attention: true\n"
            "last_checked: 2026-10-10\n"
            "---\n"
            "# Blocked ticket\n"
        ),
    )
    write_note(
        vault,
        "Actions/Unset.md",
        (
            "---\n"
            "type: action\n"
            "status: in_progress\n"
            "action_id: unset-action\n"
            'owners:\n  - "[[Carlos]]"\n'
            "---\n"
            "# Unset action\n"
        ),
    )
    write_note(
        vault,
        "Actions/Done.md",
        (
            "---\n"
            "type: action\n"
            "status: done\n"
            "action_id: done-action\n"
            "priority: P1\n"
            'owners:\n  - "[[Carlos]]"\n'
            "---\n"
            "# Done action\n"
        ),
    )
    write_note(
        vault,
        "Tickets/Resolved.md",
        (
            "---\n"
            "type: ticket\n"
            "status: resolved\n"
            "ticket_id: resolved-ticket\n"
            "priority: P1\n"
            'assignee: "[[Carlos]]"\n'
            "---\n"
            "# Resolved ticket\n"
        ),
    )
    index = WorkIndex.from_vault(vault)
    before = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*.md")}

    result = my_priorities(index, "carlos", date(2026, 10, 11), generated_at="2026-10-11T12:00:00Z")

    assert result.section_id == "my_priorities"
    assert result.effective_filters == {"owner_id": "carlos"}
    assert [item.label for item in result.items] == ["Overdue action", "Blocked ticket", "Unset action"]
    assert [item.priority for item in result.items] == ["P1", "P2", None]
    assert result.items[0].reason == "Overdue since 2026-10-10"
    assert result.items[0].attention == ("overdue_action",)
    assert result.items[0].timestamps == (("due", "2026-10-10"),)
    assert result.items[1].reason == "Ticket is blocked"
    assert result.items[1].attention == ("blocked", "manager_attention")
    assert result.items[1].timestamps == (("last_checked", "2026-10-10"),)
    assert result.items[2].reason == "in_progress"
    assert result.items[2].attention == ()
    assert result.items[2].timestamps == ()
    assert result.total_count == len(result.items) == 3
    assert section_state(result) == "items"
    assert before == {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*.md")}


def test_unknown_owner_returns_unavailable_not_empty(vault, write_note) -> None:
    _owner_notes(vault, write_note)

    result = my_priorities(
        WorkIndex.from_vault(vault), "unknown", date(2026, 10, 11), generated_at="2026-10-11T12:00:00Z"
    )

    assert result.availability == "unavailable"
    assert result.error_state == "source_unavailable"
    assert result.items == ()
    assert section_state(result) == "unavailable"


def test_known_owner_without_open_work_returns_empty(vault, write_note) -> None:
    _owner_notes(vault, write_note)
    write_note(
        vault,
        "Actions/Done.md",
        '---\ntype: action\nstatus: done\nowners:\n  - "[[Carlos]]"\n---\n# Done action\n',
    )

    result = my_priorities(
        WorkIndex.from_vault(vault), "carlos", date(2026, 10, 11), generated_at="2026-10-11T12:00:00Z"
    )

    assert result.availability == "available"
    assert result.items == ()
    assert section_state(result) == "empty"


def test_empty_owner_id_returns_unavailable(vault) -> None:
    result = my_priorities(WorkIndex.from_vault(vault), "", date(2026, 10, 11), generated_at="2026-10-11T12:00:00Z")

    assert result.availability == "unavailable"
    assert result.items == ()
    assert section_state(result) == "unavailable"
