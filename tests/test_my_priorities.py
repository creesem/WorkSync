from __future__ import annotations

from datetime import date

from worksync.work.command_center import my_priorities, section_state
from worksync.work.prioritization import Override
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 11)
GENERATED_AT = "2026-10-11T12:00:00Z"


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
    assert result.error_state == "source_unavailable"
    assert result.items == ()
    assert section_state(result) == "unavailable"


def test_owner_with_duplicate_person_id_returns_unavailable(vault, write_note) -> None:
    write_note(vault, "People/Carlos.md", "---\ntype: person\nstatus: active\nperson_id: carlos\n---\n# Carlos\n")
    write_note(vault, "People/Carlos B.md", "---\ntype: person\nstatus: active\nperson_id: carlos\n---\n# Carlos B\n")
    index = WorkIndex.from_vault(vault)

    result = my_priorities(index, "carlos", date(2026, 10, 11), generated_at="2026-10-11T12:00:00Z")

    assert result.availability == "unavailable"
    assert result.error_state == "source_unavailable"
    assert result.items == ()
    assert section_state(result) == "unavailable"


def _seed_ranked_work(vault, write_note) -> None:
    """Seed one owner with an overdue row, a due-soon row, and a quiet row."""
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
        "Tickets/Soon.md",
        (
            "---\n"
            "type: ticket\n"
            "status: open\n"
            "ticket_id: soon-ticket\n"
            "priority: P2\n"
            "due: 2026-10-20\n"
            'assignee: "[[Carlos]]"\n'
            "---\n"
            "# Soon ticket\n"
        ),
    )
    write_note(
        vault,
        "Actions/Quiet.md",
        ('---\ntype: action\nstatus: open\naction_id: quiet-action\nowners:\n  - "[[Carlos]]"\n---\n# Quiet action\n'),
    )


def _override(target_id: str, kind: str) -> Override:
    return Override(override_id=target_id, target_id=target_id, kind=kind)


def _priorities(index: WorkIndex, overrides: tuple[Override, ...] = ()):
    return my_priorities(
        index,
        "carlos",
        TODAY,
        generated_at=GENERATED_AT,
        overrides=overrides,
    )


def test_without_overrides_my_priorities_returns_the_baseline_ranking(vault, write_note) -> None:
    _seed_ranked_work(vault, write_note)
    index = WorkIndex.from_vault(vault)

    result = _priorities(index)

    assert [item.label for item in result.items] == ["Overdue action", "Soon ticket", "Quiet action"]
    assert [item.band for item in result.items] == [0, 2, 2]
    assert all(item.override_kind is None for item in result.items)
    assert result.conflicts == ()
    assert result == _priorities(index, ())


def test_pin_override_moves_the_row_to_the_front_at_the_elevated_band(vault, write_note) -> None:
    _seed_ranked_work(vault, write_note)
    index = WorkIndex.from_vault(vault)

    result = _priorities(index, (_override("quiet-action", "pin"),))

    assert [item.label for item in result.items] == ["Quiet action", "Overdue action", "Soon ticket"]
    assert result.items[0].override_kind == "pin"
    assert result.items[0].band == -1
    assert [item.override_kind for item in result.items[1:]] == [None, None]
    assert [item.band for item in result.items[1:]] == [0, 2]
    assert result.conflicts == ()
    assert result.total_count == 3


def test_defer_override_sinks_the_row_to_the_deferred_band(vault, write_note) -> None:
    _seed_ranked_work(vault, write_note)
    index = WorkIndex.from_vault(vault)

    result = _priorities(index, (_override("soon-ticket", "defer"),))

    assert [item.label for item in result.items] == ["Overdue action", "Quiet action", "Soon ticket"]
    assert result.items[-1].override_kind == "defer"
    assert result.items[-1].band == 3
    assert result.conflicts == ()


def test_not_relevant_override_drops_the_row(vault, write_note) -> None:
    _seed_ranked_work(vault, write_note)
    index = WorkIndex.from_vault(vault)

    result = _priorities(index, (_override("soon-ticket", "not_relevant"),))

    assert [item.label for item in result.items] == ["Overdue action", "Quiet action"]
    assert result.total_count == 2
    assert result.conflicts == ()


def test_defer_on_an_overdue_row_is_reported_and_left_at_its_safety_band(vault, write_note) -> None:
    _seed_ranked_work(vault, write_note)
    index = WorkIndex.from_vault(vault)

    result = _priorities(index, (_override("overdue-action", "defer"),))

    assert [item.label for item in result.items] == ["Overdue action", "Soon ticket", "Quiet action"]
    assert result.items[0].band == 0
    assert result.items[0].override_kind == "defer"
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.override_id == "overdue-action"
    assert conflict.entity_id == "overdue-action"
    assert conflict.kind == "defer"
    assert conflict.evidence == "overdue"
    assert conflict.detail == "Cannot defer overdue-action: overdue"
    assert result.total_count == 3
