"""Ticket 06: deterministic candidate eligibility for Command Center ranking.

Every assertion here goes through the public ``eligibility`` function over a real
vault scan, and the fixed ``TODAY`` keeps the derived state reproducible.
"""

from __future__ import annotations

from datetime import date

from worksync.work.models import EntityType
from worksync.work.prioritization import Eligibility, ExclusionReason, eligibility
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 12)
PERSON = "---\ntype: person\nstatus: active\nperson_id: myles-smith\n---\n# Myles Smith\n"


def _seed_person(vault, write_note) -> None:
    write_note(vault, "People/Myles Smith.md", PERSON)


def _seed_project(vault, write_note) -> None:
    _seed_person(vault, write_note)
    project_note = (
        "---\n"
        "type: project\n"
        "status: active\n"
        'owners:\n  - "[[Myles Smith]]"\n'
        "project_id: eleos\n"
        "---\n"
        "# Project - Eleos\n"
    )
    write_note(vault, "Projects/Eleos.md", project_note)


def _action(body: str) -> str:
    return f"---\n{body}---\n# Action note\n"


def _ticket(body: str) -> str:
    return f"---\n{body}---\n# Ticket note\n"


def _reason_for(result: Eligibility, path: str) -> str | None:
    """Return the exclusion reason recorded for one note, or ``None`` when it is kept."""
    return next((item.reason for item in result.exclusions if item.path == path), None)


def test_open_action_with_owner_and_project_is_a_candidate(vault, write_note) -> None:
    _seed_project(vault, write_note)
    candidate_path = "Actions/Renew certificate.md"
    write_note(
        vault,
        candidate_path,
        _action(
            "type: action\n"
            "status: open\n"
            "action_id: renew-certificate\n"
            "priority: P2\n"
            "due: 2026-10-20\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            'project: "[[Project - Eleos]]"\n'
        ),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert isinstance(result, Eligibility)
    assert len(result.candidates) == 1
    assert _reason_for(result, candidate_path) is None
    assert {item.reason for item in result.exclusions} == {ExclusionReason.UNSUPPORTED_TYPE.value}
    candidate = result.candidates[0]
    assert candidate.entity_id == "renew-certificate"
    assert candidate.entity_type == EntityType.ACTION.value
    assert candidate.path == candidate_path
    assert candidate.title == "Action note"
    assert candidate.status == "open"
    assert candidate.priority == "P2"
    assert candidate.owner_ids == ("myles-smith",)
    assert candidate.due == "2026-10-20"
    assert candidate.project_id == "eleos"
    assert candidate.blocked is False
    assert candidate.waiting is False
    assert candidate.manager_attention is False


def test_open_ticket_with_assignee_and_project_is_a_candidate(vault, write_note) -> None:
    _seed_project(vault, write_note)
    candidate_path = "Tickets/Fix export.md"
    write_note(
        vault,
        candidate_path,
        _ticket(
            "type: ticket\n"
            "status: blocked\n"
            "ticket_id: fix-export\n"
            "priority: P1\n"
            'assignee: "[[Myles Smith]]"\n'
            'project: "[[Project - Eleos]]"\n'
            "source_system: jira\n"
            "external_id: ELE-42\n"
            "manager_attention: true\n"
            "last_checked: 2026-10-01\n"
        ),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert _reason_for(result, candidate_path) is None
    assert {item.reason for item in result.exclusions} == {ExclusionReason.UNSUPPORTED_TYPE.value}
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.entity_id == "fix-export"
    assert candidate.entity_type == EntityType.TICKET.value
    assert candidate.status == "blocked"
    assert candidate.priority == "P1"
    assert candidate.owner_ids == ("myles-smith",)
    assert candidate.due is None
    assert candidate.project_id == "eleos"
    assert candidate.blocked is True
    assert candidate.waiting is False
    assert candidate.manager_attention is True
    assert candidate.changed_on == "2026-10-01"


def test_waiting_ticket_records_the_waiting_signal(vault, write_note) -> None:
    _seed_project(vault, write_note)
    write_note(
        vault,
        "Tickets/Awaiting vendor.md",
        _ticket('type: ticket\nstatus: waiting\nassignee: "[[Myles Smith]]"\nproject: "[[Project - Eleos]]"\n'),
    )
    index = WorkIndex.from_vault(vault)

    candidate = eligibility(index, today=TODAY).candidates[0]

    assert candidate.waiting is True
    assert candidate.blocked is False


def test_closed_records_are_excluded_with_closed_status(vault, write_note) -> None:
    _seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Finished.md",
        _action(
            "type: action\n"
            "status: done\n"
            "action_id: finished-action\n"
            "completed: 2026-10-02\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            'project: "[[Project - Eleos]]"\n'
        ),
    )
    write_note(
        vault,
        "Tickets/Shipped.md",
        _ticket(
            "type: ticket\n"
            "status: resolved\n"
            "ticket_id: shipped-ticket\n"
            'assignee: "[[Myles Smith]]"\n'
            'project: "[[Project - Eleos]]"\n'
        ),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert result.candidates == ()
    assert _reason_for(result, "Actions/Finished.md") == ExclusionReason.CLOSED_STATUS.value
    assert _reason_for(result, "Tickets/Shipped.md") == ExclusionReason.CLOSED_STATUS.value
    closed = {
        item.path: item.entity_id for item in result.exclusions if item.reason == ExclusionReason.CLOSED_STATUS.value
    }
    assert closed == {"Actions/Finished.md": "finished-action", "Tickets/Shipped.md": "shipped-ticket"}


def test_a_note_with_an_error_exclusion_beats_a_later_rule(vault, write_note) -> None:
    """First failure wins: a closed note that is also invalid reads as unauthorized."""
    _seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Finished.md",
        _action(
            "type: action\n"
            "status: done\n"
            "action_id: unfinished-action\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            'project: "[[Project - Eleos]]"\n'
        ),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert _reason_for(result, "Actions/Finished.md") == ExclusionReason.UNAUTHORIZED.value


def test_open_action_without_owner_is_excluded_as_unowned(vault, write_note) -> None:
    _seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Orphan.md",
        _action("type: action\nstatus: open\naction_id: orphan-action\nproject: '[[Project - Eleos]]'\n"),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert result.candidates == ()
    assert _reason_for(result, "Actions/Orphan.md") == ExclusionReason.UNOWNED.value
    assert [item.path for item in result.exclusions if item.reason == ExclusionReason.UNOWNED.value] == [
        "Actions/Orphan.md"
    ]


def test_open_ticket_without_project_or_source_is_excluded_as_no_evidence(vault, write_note) -> None:
    _seed_person(vault, write_note)
    write_note(
        vault,
        "Tickets/Floating.md",
        _ticket('type: ticket\nstatus: open\nticket_id: floating-ticket\nassignee: "[[Myles Smith]]"\n'),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert result.candidates == ()
    assert _reason_for(result, "Tickets/Floating.md") == ExclusionReason.NO_EVIDENCE.value
    assert [item.path for item in result.exclusions if item.reason == ExclusionReason.NO_EVIDENCE.value] == [
        "Tickets/Floating.md"
    ]


def test_action_with_related_ticket_has_evidence_without_a_project(vault, write_note) -> None:
    _seed_person(vault, write_note)
    write_note(
        vault,
        "Actions/Chase vendor.md",
        _action(
            "type: action\n"
            "status: open\n"
            "action_id: chase-vendor\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "related_ticket: VENDOR-9\n"
        ),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert _reason_for(result, "Actions/Chase vendor.md") is None
    assert [candidate.entity_id for candidate in result.candidates] == ["chase-vendor"]
    assert result.candidates[0].project_id is None


def test_note_with_a_validation_error_is_excluded_as_unauthorized(vault, write_note) -> None:
    _seed_project(vault, write_note)
    path = "Actions/Bad priority.md"
    write_note(
        vault,
        path,
        _action(
            "type: action\n"
            "status: open\n"
            "action_id: bad-priority\n"
            "priority: P9\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    index = WorkIndex.from_vault(vault)

    assert index.has_errors(path) is True

    result = eligibility(index, today=TODAY)

    assert result.candidates == ()
    assert _reason_for(result, path) == ExclusionReason.UNAUTHORIZED.value
    assert [item.entity_id for item in result.exclusions if item.reason == ExclusionReason.UNAUTHORIZED.value] == [
        "bad-priority"
    ]


def test_project_note_is_excluded_as_unsupported_type(vault, write_note) -> None:
    _seed_project(vault, write_note)
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert result.candidates == ()
    unsupported = {
        item.path: item.entity_type
        for item in result.exclusions
        if item.reason == ExclusionReason.UNSUPPORTED_TYPE.value
    }
    assert unsupported == {
        "People/Myles Smith.md": EntityType.PERSON.value,
        "Projects/Eleos.md": EntityType.PROJECT.value,
    }


def test_changed_on_is_the_latest_present_date_field(vault, write_note) -> None:
    _seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Stale.md",
        _action(
            "type: action\n"
            "status: open\n"
            "action_id: stale-action\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
            "created: 2026-01-05\n"
            "updated: 2026-10-01\n"
            "last_checked: 2026-10-09\n"
            "source_date: 2026-05-05\n"
        ),
    )
    index = WorkIndex.from_vault(vault)

    candidate = eligibility(index, today=TODAY).candidates[0]

    assert candidate.changed_on == "2026-10-09"


def test_changed_on_is_none_when_no_date_field_parses(vault, write_note) -> None:
    _seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Undated.md",
        _action(
            "type: action\n"
            "status: open\n"
            "action_id: undated-action\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
            "updated: not-a-date\n"
        ),
    )
    index = WorkIndex.from_vault(vault)

    candidate = eligibility(index, today=TODAY).candidates[0]

    assert candidate.changed_on is None


def test_eligibility_is_deterministic_and_ordered_for_the_same_index(vault, write_note) -> None:
    _seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Renew certificate.md",
        _action(
            "type: action\n"
            "status: open\n"
            "action_id: renew-certificate\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    write_note(
        vault,
        "Actions/Buy domain.md",
        _action(
            "type: action\n"
            "status: open\n"
            "action_id: buy-domain\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    write_note(
        vault,
        "Tickets/Unassigned.md",
        _ticket("type: ticket\nstatus: open\nticket_id: unassigned-ticket\nsource_system: jira\n"),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert [candidate.path for candidate in result.candidates] == [
        "Actions/Buy domain.md",
        "Actions/Renew certificate.md",
    ]
    assert [(item.reason, item.path) for item in result.exclusions] == sorted(
        (item.reason, item.path) for item in result.exclusions
    )
    assert result == eligibility(index, today=TODAY)
