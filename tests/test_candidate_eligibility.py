"""Ticket 06: deterministic candidate eligibility for Command Center ranking.

Every case runs the public ``eligibility`` function over a real vault scan, and
the fixed ``TODAY`` keeps the derived state reproducible. One case then hands
the resulting candidates to ``rank``, to pin that the blocker signal alone moves
no score, reason, or row.
"""

from __future__ import annotations

from prioritization_fakes import TODAY, action_note, seed_person, seed_project, ticket_note
from worksync.work.models import EntityType
from worksync.work.prioritization import Eligibility, ExclusionReason, eligibility, rank
from worksync.work.repository import WorkIndex
from worksync.work.review import AttentionKind, attention_by_path


def _reason_for(result: Eligibility, path: str) -> str | None:
    """Return the exclusion reason recorded for one note, or ``None`` when it is kept."""
    return next((item.reason for item in result.exclusions if item.path == path), None)


def _attention_kinds(index: WorkIndex) -> dict[str, set[str]]:
    """Group the attention kinds the review module reports, by note path."""
    return {path: {item.kind for item in items} for path, items in attention_by_path(index, TODAY).items()}


def test_open_action_with_owner_and_project_is_a_candidate(vault, write_note) -> None:
    seed_project(vault, write_note)
    candidate_path = "Actions/Renew certificate.md"
    write_note(
        vault,
        candidate_path,
        action_note(
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
    seed_project(vault, write_note)
    candidate_path = "Tickets/Fix export.md"
    write_note(
        vault,
        candidate_path,
        ticket_note(
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
    seed_project(vault, write_note)
    write_note(
        vault,
        "Tickets/Awaiting vendor.md",
        ticket_note('type: ticket\nstatus: waiting\nassignee: "[[Myles Smith]]"\nproject: "[[Project - Eleos]]"\n'),
    )
    index = WorkIndex.from_vault(vault)

    candidate = eligibility(index, today=TODAY).candidates[0]

    assert candidate.waiting is True
    assert candidate.blocked is False


def test_a_waiting_action_carries_the_party_and_the_dependency_it_waits_on(vault, write_note) -> None:
    """A dependency target the note states is carried, resolved when the link resolves."""
    seed_project(vault, write_note)
    write_note(
        vault,
        "Tickets/Vendor.md",
        "---\n"
        "type: ticket\n"
        "status: blocked\n"
        "ticket_id: vendor-ticket\n"
        'assignee: "[[Myles Smith]]"\n'
        'project: "[[Project - Eleos]]"\n'
        "---\n"
        "# Ticket - Vendor\n",
    )
    write_note(
        vault,
        "Actions/Awaiting vendor.md",
        action_note(
            "type: action\n"
            "status: waiting\n"
            "action_id: awaiting-vendor\n"
            "waiting_on: vendor\n"
            'related_ticket: "[[Ticket - Vendor]]"\n'
            'owners:\n  - "[[Myles Smith]]"\n'
            'project: "[[Project - Eleos]]"\n'
        ),
    )
    write_note(
        vault,
        "Tickets/Awaiting.md",
        ticket_note(
            "type: ticket\n"
            "status: waiting\n"
            "ticket_id: awaiting-ticket\n"
            'assignee: "[[Myles Smith]]"\n'
            'project: "[[Project - Eleos]]"\n'
        ),
    )
    index = WorkIndex.from_vault(vault)

    by_id = {candidate.entity_id: candidate for candidate in eligibility(index, today=TODAY).candidates}

    named = by_id["awaiting-vendor"]
    assert named.waiting is True
    assert named.waiting_on == "vendor"
    assert named.dependency_id == "vendor-ticket"
    # A ticket waits on a party too, but carries no ``waiting_on`` target to name.
    unnamed = by_id["awaiting-ticket"]
    assert unnamed.waiting is True
    assert unnamed.waiting_on is None
    assert unnamed.dependency_id is None


def test_an_unresolvable_related_ticket_is_no_dependency_id(vault, write_note) -> None:
    _seed_blocker_scenarios(vault, write_note)
    index = WorkIndex.from_vault(vault)

    by_id = {candidate.entity_id: candidate for candidate in eligibility(index, today=TODAY).candidates}

    # The waiting action names a party but links no ticket it can resolve.
    awaiting = by_id["awaiting-action"]
    assert awaiting.waiting_on == "vendor"
    assert awaiting.dependency_id is None
    # Tickets carry neither field: they wait on a party, never on a stated target.
    for candidate in by_id.values():
        if candidate.entity_type == EntityType.TICKET.value:
            assert candidate.waiting_on is None
            assert candidate.dependency_id is None


def test_closed_records_are_excluded_with_closed_status(vault, write_note) -> None:
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Finished.md",
        action_note(
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
        ticket_note(
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
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Finished.md",
        action_note(
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
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Orphan.md",
        action_note("type: action\nstatus: open\naction_id: orphan-action\nproject: '[[Project - Eleos]]'\n"),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert result.candidates == ()
    assert _reason_for(result, "Actions/Orphan.md") == ExclusionReason.UNOWNED.value
    assert [item.path for item in result.exclusions if item.reason == ExclusionReason.UNOWNED.value] == [
        "Actions/Orphan.md"
    ]


def test_open_ticket_without_project_or_source_is_excluded_as_no_evidence(vault, write_note) -> None:
    seed_person(vault, write_note)
    write_note(
        vault,
        "Tickets/Floating.md",
        ticket_note('type: ticket\nstatus: open\nticket_id: floating-ticket\nassignee: "[[Myles Smith]]"\n'),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert result.candidates == ()
    assert _reason_for(result, "Tickets/Floating.md") == ExclusionReason.NO_EVIDENCE.value
    assert [item.path for item in result.exclusions if item.reason == ExclusionReason.NO_EVIDENCE.value] == [
        "Tickets/Floating.md"
    ]


def test_action_with_related_ticket_has_evidence_without_a_project(vault, write_note) -> None:
    seed_person(vault, write_note)
    write_note(
        vault,
        "Actions/Chase vendor.md",
        action_note(
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
    seed_project(vault, write_note)
    path = "Actions/Bad priority.md"
    write_note(
        vault,
        path,
        action_note(
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
    seed_project(vault, write_note)
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
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Stale.md",
        action_note(
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
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Undated.md",
        action_note(
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


def test_changed_on_same_day_tie_keeps_the_first_field_in_order(vault, write_note) -> None:
    """Dates compare at day granularity, so a tie keeps ``CHANGED_ON_FIELDS`` order.

    ``last_checked`` and ``updated`` carry the same day here, and only
    ``last_checked`` comes first in ``CHANGED_ON_FIELDS``, so the later timestamp
    written into ``updated`` must not win.
    """
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Tie.md",
        action_note(
            "type: action\n"
            "status: open\n"
            "action_id: tie-action\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
            "last_checked: 2026-10-05\n"
            'updated: "2026-10-05T09:30:00"\n'
        ),
    )
    index = WorkIndex.from_vault(vault)

    candidate = eligibility(index, today=TODAY).candidates[0]

    assert candidate.changed_on == "2026-10-05"


def test_an_owner_link_that_resolves_to_nobody_falls_back_to_the_link_target(vault, write_note) -> None:
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Ghost owner.md",
        action_note(
            "type: action\n"
            "status: open\n"
            "action_id: ghost-owner-action\n"
            'owners:\n  - "[[Ghost Person]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    assert _reason_for(result, "Actions/Ghost owner.md") is None
    assert [candidate.entity_id for candidate in result.candidates] == ["ghost-owner-action"]
    # The unresolved link survives as its link target: never dropped, never an id.
    assert result.candidates[0].owner_ids == ("ghost person",)


def test_owner_ids_follow_input_order_and_drop_duplicates(vault, write_note) -> None:
    seed_project(vault, write_note)
    write_note(
        vault,
        "People/Ada Lovelace.md",
        "---\ntype: person\nstatus: active\nperson_id: ada-lovelace\n---\n# Ada Lovelace\n",
    )
    write_note(
        vault,
        "Actions/Shared.md",
        action_note(
            "type: action\n"
            "status: open\n"
            "action_id: shared-action\n"
            'owners:\n  - "[[Ada Lovelace]]"\n  - "[[Myles Smith]]"\n  - "[[Ada Lovelace]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)

    # Input order, not path order, and the repeated owner appears once.
    assert result.candidates[0].owner_ids == ("ada-lovelace", "myles-smith")


def test_a_note_whose_only_issue_is_a_warning_is_still_a_candidate(vault, write_note) -> None:
    """``unauthorized`` is error-only: a warning never excludes a note."""
    seed_project(vault, write_note)
    path = "Tickets/Warned.md"
    write_note(
        vault,
        path,
        ticket_note(
            "type: ticket\n"
            "status: open\n"
            "ticket_id: warned-ticket\n"
            'assignee: "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
            "source_system: jira\n"
        ),
    )
    index = WorkIndex.from_vault(vault)

    assert index.has_errors(path) is False
    assert [issue.severity for issue in index.issues_for(path)] == ["warning"]

    result = eligibility(index, today=TODAY)

    assert _reason_for(result, path) is None
    assert [candidate.entity_id for candidate in result.candidates] == ["warned-ticket"]


def _seed_blocker_scenarios(vault, write_note) -> None:
    """Seed every blocker shape: an overdue and a waiting action, and blocked, waiting, and flagged tickets."""
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Overdue.md",
        action_note(
            "type: action\n"
            "status: open\n"
            "action_id: overdue-action\n"
            "priority: P2\n"
            "due: 2026-10-01\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    write_note(
        vault,
        "Actions/Awaiting.md",
        action_note(
            "type: action\n"
            "status: waiting\n"
            "action_id: awaiting-action\n"
            "waiting_on: vendor\n"
            'owners:\n  - "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    write_note(
        vault,
        "Tickets/Stuck.md",
        ticket_note(
            "type: ticket\n"
            "status: blocked\n"
            "ticket_id: stuck-ticket\n"
            'assignee: "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    write_note(
        vault,
        "Tickets/Awaiting.md",
        ticket_note(
            "type: ticket\n"
            "status: waiting\n"
            "ticket_id: awaiting-ticket\n"
            'assignee: "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    write_note(
        vault,
        "Tickets/Flagged.md",
        ticket_note(
            "type: ticket\n"
            "status: open\n"
            "ticket_id: flagged-ticket\n"
            "manager_attention: true\n"
            'assignee: "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )
    write_note(
        vault,
        "Tickets/Flagged and closed.md",
        ticket_note(
            "type: ticket\n"
            "status: resolved\n"
            "ticket_id: flagged-closed-ticket\n"
            "manager_attention: true\n"
            'assignee: "[[Myles Smith]]"\n'
            "project: '[[Project - Eleos]]'\n"
        ),
    )


def test_blocker_signals_are_the_attention_kinds_the_review_module_reports(vault, write_note) -> None:
    """One owner for the blocker signal: eligibility mirrors ``work.review``.

    The plan's global constraint binds this module to that module's attention
    pass, so each candidate's three flags are exactly the kinds it reports for
    the same note, with no second derivation to drift.
    """
    _seed_blocker_scenarios(vault, write_note)
    index = WorkIndex.from_vault(vault)

    result = eligibility(index, today=TODAY)
    kinds = _attention_kinds(index)

    assert [candidate.entity_id for candidate in result.candidates] == [
        "awaiting-action",
        "overdue-action",
        "awaiting-ticket",
        "flagged-ticket",
        "stuck-ticket",
    ]
    # A closed note is excluded before the signal is read, so the review module's
    # not-closed guard on manager attention cannot change a candidate's flags.
    assert _reason_for(result, "Tickets/Flagged and closed.md") == ExclusionReason.CLOSED_STATUS.value

    for candidate in result.candidates:
        reported = kinds[candidate.path]
        assert candidate.blocked is (AttentionKind.BLOCKED.value in reported)
        assert candidate.waiting is (AttentionKind.WAITING.value in reported)
        assert candidate.manager_attention is (AttentionKind.MANAGER_ATTENTION.value in reported)

    # An action can be overdue and waiting, but it is never blocked.
    assert AttentionKind.OVERDUE_ACTION.value in kinds["Actions/Overdue.md"]
    by_id = {candidate.entity_id: candidate for candidate in result.candidates}
    assert by_id["overdue-action"].blocked is False
    assert by_id["awaiting-action"].waiting is True
    assert by_id["stuck-ticket"].blocked is True
    assert by_id["awaiting-ticket"].waiting is True
    assert by_id["flagged-ticket"].manager_attention is True


def test_the_blocker_signals_leave_the_scores_reasons_and_order_alone(vault, write_note) -> None:
    """Moving the blocker signal must not move a score, a reason, or a row."""
    _seed_blocker_scenarios(vault, write_note)
    index = WorkIndex.from_vault(vault)

    ranked = rank(eligibility(index, today=TODAY).candidates, today=TODAY)

    assert [item.candidate.entity_id for item in ranked.items] == [
        "overdue-action",
        "flagged-ticket",
        "stuck-ticket",
        "awaiting-action",
        "awaiting-ticket",
    ]
    by_id = {item.candidate.entity_id: item for item in ranked.items}
    overdue = by_id["overdue-action"]
    assert overdue.score == 91
    assert overdue.band == 0
    assert overdue.policies == ("overdue",)
    assert [reason.code for reason in overdue.reasons] == [
        "overdue",
        "priority",
        "independent",
        "explicit_commitment",
        "ready",
        "unchanged",
    ]
    stuck = by_id["stuck-ticket"]
    assert stuck.score == 7
    assert stuck.band == 1
    assert stuck.policies == ("blocked",)
    assert [reason.code for reason in stuck.reasons] == [
        "no_due_date",
        "no_priority",
        "blocked",
        "no_commitment",
        "not_ready",
        "unchanged",
    ]
    awaiting = by_id["awaiting-action"]
    assert awaiting.score == -3
    assert awaiting.band == 2
    assert [reason.code for reason in awaiting.reasons] == [
        "no_due_date",
        "no_priority",
        "waiting",
        "no_commitment",
        "not_ready",
        "unchanged",
    ]


def test_eligibility_is_deterministic_and_ordered_for_the_same_index(vault, write_note) -> None:
    seed_project(vault, write_note)
    write_note(
        vault,
        "Actions/Renew certificate.md",
        action_note(
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
        action_note(
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
        ticket_note("type: ticket\nstatus: open\nticket_id: unassigned-ticket\nsource_system: jira\n"),
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
