"""The review module's two shared primitives.

``is_open_status`` and ``attention_by_path`` are the single owners of the
open-status test and the attention grouping, so the Command Center sections and
the ranker both call these instead of deriving either a second time. These tests
pin them to the review module's own status sets and to its own attention pass.
"""

from __future__ import annotations

from datetime import date

import pytest

from worksync.work.models import Action, Project, Ticket
from worksync.work.repository import WorkIndex
from worksync.work.review import (
    CLOSED_TICKET_STATUSES,
    OPEN_ACTION_STATUSES,
    OPEN_TICKET_STATUSES,
    attention_by_path,
    attention_items,
    is_open_status,
)

TODAY = date(2026, 10, 12)


def _action(status: str) -> Action:
    return Action(path=f"Actions/{status}.md", title=f"Action {status}", status=status)


def _ticket(status: str) -> Ticket:
    return Ticket(path=f"Tickets/{status}.md", title=f"Ticket {status}", status=status)


@pytest.mark.parametrize("status", sorted(OPEN_ACTION_STATUSES))
def test_an_open_action_status_leaves_the_action_in_play(status: str) -> None:
    assert is_open_status(_action(status)) is True


@pytest.mark.parametrize("status", sorted(OPEN_TICKET_STATUSES))
def test_an_open_ticket_status_leaves_the_ticket_in_play(status: str) -> None:
    assert is_open_status(_ticket(status)) is True


def test_the_status_sets_are_the_ones_the_primitive_reads() -> None:
    """The sets are asserted, not remembered: they are the whole contract."""
    assert {"in_progress", "open", "waiting"} == OPEN_ACTION_STATUSES
    assert {"blocked", "escalated", "in_progress", "open", "waiting"} == OPEN_TICKET_STATUSES


def test_a_done_action_is_not_in_play() -> None:
    assert is_open_status(_action("done")) is False


def test_a_resolved_ticket_is_not_in_play() -> None:
    assert is_open_status(_ticket("resolved")) is False


def test_a_waiting_ticket_is_in_play() -> None:
    """Waiting keeps a ticket open: it is one of ``OPEN_TICKET_STATUSES``."""
    assert "waiting" in OPEN_TICKET_STATUSES
    assert is_open_status(_ticket("waiting")) is True


def test_open_and_closed_ticket_statuses_are_disjoint() -> None:
    """No status is both, so the shared status test needs no second closed guard."""
    assert OPEN_TICKET_STATUSES.isdisjoint(CLOSED_TICKET_STATUSES)


def test_only_actions_and_tickets_can_be_in_play() -> None:
    """A type with no open statuses is out of play, even when it carries one."""
    assert is_open_status(Project(path="Projects/p.md", title="Project", status="active")) is False


def test_a_non_ticket_that_carries_an_open_ticket_status_is_not_in_play() -> None:
    """The type check is armed: ``blocked`` is an open ticket status, not a project one.

    A project whose status happens to read ``blocked`` must stay out of play, so
    a mutation that reads the status set without checking the type fails here.
    """
    assert "blocked" in OPEN_TICKET_STATUSES

    assert is_open_status(Project(path="Projects/Blocked.md", title="Blocked", status="blocked")) is False


def test_attention_by_path_groups_the_pass_by_note_path_in_the_pass_order(vault, write_note) -> None:
    write_note(
        vault,
        "Actions/Overdue.md",
        "---\ntype: action\nstatus: open\naction_id: overdue-action\ndue: 2026-10-01\n---\n# Overdue action\n",
    )
    write_note(
        vault,
        "Tickets/Blocked.md",
        "---\ntype: ticket\nstatus: blocked\nticket_id: blocked-ticket\n---\n# Blocked ticket\n",
    )
    index = WorkIndex.from_vault(vault)

    grouped = attention_by_path(index, TODAY)

    assert set(grouped) == {"Actions/Overdue.md", "Tickets/Blocked.md"}
    for path, group in grouped.items():
        assert isinstance(group, tuple)
        # One pass, regrouped: each group is the pass's own order for that path.
        assert group == tuple(item for item in attention_items(index, TODAY) if item.path == path)
    assert [item.kind for item in grouped["Tickets/Blocked.md"]] == ["blocked", "stale_ticket"]
