"""Ticket 07: the deterministic baseline ranker with reason codes.

``Candidate`` objects are built directly so the ranker is tested in isolation,
and one scenario runs the real vault scan through ``eligibility`` first. The
fixed ``TODAY`` keeps every score and order reproducible offline.
"""

from __future__ import annotations

from datetime import date

from worksync.work.models import EntityType
from worksync.work.prioritization import (
    Candidate,
    RankedItem,
    RankFactor,
    Ranking,
    RankReason,
    SafetyPolicy,
    eligibility,
    rank,
)
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 12)
FACTOR_ORDER = ["urgency", "impact", "dependency", "commitment", "readiness", "recent_change"]

# The brief's weights, restated so a test can assert score == sum of the deltas.
URGENCY_DELTAS = {
    "overdue": 45,
    "due_today": 40,
    "due_soon": 30,
    "due_scheduled": 0,
    "no_due_date": -8,
}
IMPACT_DELTAS = {"P1": 32, "P2": 24, "P3": 16, "P4": 8}
FACTOR_DELTAS = {
    "no_priority": 0,
    "manager_attention": 20,
    "blocked": 25,
    "waiting": 15,
    "independent": 0,
    "explicit_commitment": 10,
    "no_commitment": 0,
    "ready": 12,
    "not_ready": -10,
    "recent_change": 10,
    "unchanged": 0,
}


def _candidate(
    *,
    entity_id: str = "alpha-action",
    entity_type: str = EntityType.ACTION.value,
    title: str = "Alpha",
    status: str = "open",
    priority: str | None = None,
    owner_ids: tuple[str, ...] = ("myles-smith",),
    due: str | None = None,
    project_id: str | None = "eleos",
    blocked: bool = False,
    waiting: bool = False,
    manager_attention: bool = False,
    changed_on: str | None = None,
) -> Candidate:
    """Build one candidate, overriding only the fields a case is about."""
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        path=f"Notes/{entity_id}.md",
        title=title,
        status=status,
        priority=priority,
        owner_ids=owner_ids,
        due=due,
        project_id=project_id,
        blocked=blocked,
        waiting=waiting,
        manager_attention=manager_attention,
        changed_on=changed_on,
    )


def _delta_sum(reasons: tuple[RankReason, ...], priority: str | None) -> int:
    """Return the score the brief's weights imply for one reason list."""
    total = 0
    for reason in reasons:
        if reason.code == "priority":
            total += IMPACT_DELTAS[priority]
        elif reason.code in URGENCY_DELTAS:
            total += URGENCY_DELTAS[reason.code]
        else:
            total += FACTOR_DELTAS[reason.code]
    return total


def _codes(item: RankedItem, factor: str) -> list[str]:
    return [reason.code for reason in item.reasons if reason.factor == factor]


def _detail(item: RankedItem, factor: str) -> str:
    return next(reason.detail for reason in item.reasons if reason.factor == factor)


def _detail_for(item: RankedItem, code: str) -> str:
    return next(reason.detail for reason in item.reasons if reason.code == code)


def test_every_factor_has_a_reason_and_the_score_is_the_sum_of_the_deltas() -> None:
    candidates = (
        _candidate(entity_id="alpha", title="Alpha", priority="P1", due="2026-10-05", changed_on="2026-10-10"),
        _candidate(entity_id="bravo", title="Bravo", priority=None, due=None, blocked=True, owner_ids=()),
        _candidate(
            entity_id="charlie",
            title="Charlie",
            priority="P3",
            due=TODAY.isoformat(),
            manager_attention=True,
            changed_on="2026-09-01",
        ),
        _candidate(
            entity_id="delta",
            title="Delta",
            priority="P4",
            due="2026-11-30",
            status="waiting",
            waiting=True,
        ),
    )

    result = rank(candidates, today=TODAY)

    assert isinstance(result, Ranking)
    assert len(result.items) == 4
    for item in result.items:
        expected = list(FACTOR_ORDER)
        if item.candidate.manager_attention:
            expected.insert(2, "impact")
        assert [reason.factor for reason in item.reasons] == expected
        assert item.score == _delta_sum(item.reasons, item.candidate.priority)
        assert all(reason.code and reason.detail for reason in item.reasons)
    delta = next(item for item in result.items if item.candidate.entity_id == "delta")
    assert _codes(delta, "dependency") == ["waiting"]
    assert _codes(delta, "readiness") == ["not_ready"]


def test_urgency_orders_overdue_due_today_due_soon_and_no_due_date() -> None:
    candidates = (
        _candidate(entity_id="none", title="No due", priority="P2"),
        _candidate(entity_id="soon", title="Due soon", priority="P2", due="2026-10-18"),
        _candidate(entity_id="today", title="Due today", priority="P2", due=TODAY.isoformat()),
        _candidate(entity_id="late", title="Overdue", priority="P2", due="2026-10-05"),
    )

    result = rank(candidates, today=TODAY)

    assert [item.candidate.entity_id for item in result.items] == ["late", "today", "soon", "none"]


def test_priority_orders_p1_before_p2_before_unset_at_equal_deadline() -> None:
    candidates = (
        _candidate(entity_id="p4", title="Bravo", priority="P4", due="2026-10-20"),
        _candidate(entity_id="none", title="Charlie", priority=None, due="2026-10-20"),
        _candidate(entity_id="p1", title="Alpha", priority="P1", due="2026-10-20"),
        _candidate(entity_id="p2", title="Delta", priority="P2", due="2026-10-20"),
    )

    result = rank(candidates, today=TODAY)

    assert [item.candidate.entity_id for item in result.items] == ["p1", "p2", "p4", "none"]


def test_safety_policies_assign_floors_and_never_drop_a_row() -> None:
    blocked = _candidate(entity_id="stuck", title="Stuck", status="blocked", priority="P3", blocked=True)
    late = _candidate(entity_id="late", title="Late", priority="P3", due="2026-10-01")
    plain = _candidate(entity_id="plain", title="Plain", priority="P3", due="2026-12-01")

    result = rank((blocked, late, plain), today=TODAY)

    by_id = {item.candidate.entity_id: item for item in result.items}
    assert by_id["late"].policies == (SafetyPolicy.OVERDUE.value,)
    assert by_id["late"].band == 0
    assert by_id["stuck"].policies == (SafetyPolicy.BLOCKED.value,)
    assert by_id["stuck"].band == 1
    assert by_id["plain"].policies == ()
    assert by_id["plain"].band == 2
    assert by_id["late"].band < by_id["stuck"].band
    assert [item.candidate.entity_id for item in result.items] == ["late", "stuck", "plain"]


def test_policies_are_sorted_by_band_then_name() -> None:
    flagged = _candidate(
        entity_id="flagged",
        title="Flagged",
        priority="P3",
        due="2026-10-01",
        manager_attention=True,
    )

    result = rank((flagged,), today=TODAY)

    assert result.items[0].policies == ("manager_attention", "overdue")
    assert result.items[0].band == 0


def test_conflicting_deadlines_put_the_overdue_action_first() -> None:
    overdue_action = _candidate(entity_id="overdue", title="Overdue", priority="P2", due="2026-10-05")
    soon_action = _candidate(entity_id="soon", title="Due soon", priority="P2", due="2026-10-15")

    result = rank((overdue_action, soon_action), today=TODAY)

    assert [item.candidate.entity_id for item in result.items] == ["overdue", "soon"]
    first = result.items[0]
    assert _codes(first, "urgency") == ["overdue"]
    assert _detail(first, "urgency") == "Overdue since 2026-10-05"


def test_a_blocker_is_ranked_by_band_before_score() -> None:
    blocked_ticket = _candidate(
        entity_id="blocked",
        title="Blocked",
        entity_type=EntityType.TICKET.value,
        status="blocked",
        priority="P4",
        blocked=True,
    )
    ordinary_ticket = _candidate(
        entity_id="ordinary",
        title="Ordinary",
        entity_type=EntityType.TICKET.value,
        priority="P1",
        due=TODAY.isoformat(),
    )

    result = rank((blocked_ticket, ordinary_ticket), today=TODAY)

    assert [item.candidate.entity_id for item in result.items] == ["blocked", "ordinary"]
    assert result.items[0].score < result.items[1].score


def test_urgency_reason_codes_and_details() -> None:
    cases = {
        "2026-10-05": ("overdue", "Overdue since 2026-10-05", 45),
        TODAY.isoformat(): ("due_today", "Due today", 40),
        "2026-10-18": ("due_soon", "Due 2026-10-18", 30),
        None: ("no_due_date", "No due date", -8),
        "2026-11-30": ("due_scheduled", "Due 2026-11-30", 0),
    }

    for due, (code, detail, delta) in cases.items():
        item = rank((_candidate(entity_id=f"case-{due}", due=due),), today=TODAY).items[0]
        assert _codes(item, "urgency") == [code]
        assert _detail(item, "urgency") == detail
        assert item.score - _other_deltas(item) == delta


def _other_deltas(item: RankedItem) -> int:
    """The score contributed by every factor except urgency."""
    return _delta_sum(tuple(reason for reason in item.reasons if reason.factor != "urgency"), item.candidate.priority)


def test_non_urgency_reason_codes_and_details() -> None:
    flagged = _candidate(
        entity_id="flagged",
        title="Flagged",
        priority="P2",
        due=TODAY.isoformat(),
        manager_attention=True,
        changed_on="2026-10-01",
    )
    plain = _candidate(entity_id="plain", title="Plain", priority=None, due=None, changed_on="2026-08-01")
    waiting = _candidate(
        entity_id="waiting",
        title="Waiting",
        priority="P3",
        due="2026-12-01",
        status="waiting",
        waiting=True,
        changed_on="2026-09-27",
    )

    result = rank((flagged, plain, waiting), today=TODAY)
    by_id = {item.candidate.entity_id: item for item in result.items}

    assert _codes(by_id["flagged"], "impact") == ["priority", "manager_attention"]
    assert _detail_for(by_id["flagged"], "priority") == "P2"
    assert _detail_for(by_id["flagged"], "manager_attention") == "Flagged for manager attention"
    assert _codes(by_id["flagged"], "dependency") == ["independent"]
    assert _codes(by_id["flagged"], "commitment") == ["explicit_commitment"]
    assert _codes(by_id["flagged"], "readiness") == ["ready"]
    assert _codes(by_id["flagged"], "recent_change") == ["recent_change"]
    assert _detail(by_id["flagged"], "recent_change") == "Changed 2026-10-01"

    assert _codes(by_id["plain"], "impact") == ["no_priority"]
    assert _detail(by_id["plain"], "impact") == "No priority"
    assert _codes(by_id["plain"], "commitment") == ["no_commitment"]
    assert _codes(by_id["plain"], "recent_change") == ["unchanged"]

    assert _codes(by_id["waiting"], "dependency") == ["waiting"]
    assert _codes(by_id["waiting"], "readiness") == ["not_ready"]
    assert _codes(by_id["waiting"], "recent_change") == ["unchanged"]


def test_recent_change_window_boundary() -> None:
    inside = _candidate(entity_id="inside", title="Inside", changed_on="2026-09-28")
    outside = _candidate(entity_id="outside", title="Outside", changed_on="2026-09-27")
    unparseable = _candidate(entity_id="unparseable", title="Unparseable", changed_on="not-a-date")

    result = rank((inside, outside, unparseable), today=TODAY)

    by_id = {item.candidate.entity_id: item for item in result.items}
    assert _codes(by_id["inside"], "recent_change") == ["recent_change"]
    assert _detail(by_id["inside"], "recent_change") == "Changed 2026-09-28"
    assert _codes(by_id["outside"], "recent_change") == ["unchanged"]
    assert _codes(by_id["unparseable"], "recent_change") == ["unchanged"]


def test_ranking_is_deterministic_for_the_same_candidates() -> None:
    candidates = (
        _candidate(entity_id="alpha", title="Alpha", priority="P1", due="2026-10-05"),
        _candidate(entity_id="bravo", title="Bravo", priority="P3", status="blocked", blocked=True),
        _candidate(entity_id="charlie", title="Charlie", priority="P2", due=TODAY.isoformat()),
    )

    assert rank(candidates, today=TODAY) == rank(candidates, today=TODAY)


PERSON = "---\ntype: person\nstatus: active\nperson_id: myles-smith\n---\n# Myles Smith\n"
PROJECT = (
    '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles Smith]]"\nproject_id: eleos\n---\n# Project - Eleos\n'
)


def test_end_to_end_ranks_the_candidates_eligibility_returns(vault, write_note) -> None:
    write_note(vault, "People/Myles Smith.md", PERSON)
    write_note(vault, "Projects/Eleos.md", PROJECT)
    write_note(
        vault,
        "Actions/Buy milk.md",
        "---\ntype: action\nstatus: open\naction_id: buy-milk\npriority: P1\ndue: 2026-10-12\n"
        'owners:\n  - "[[Myles Smith]]"\nproject: "[[Project - Eleos]]"\n---\n# Buy milk\n',
    )
    write_note(
        vault,
        "Tickets/Fix export.md",
        "---\ntype: ticket\nstatus: blocked\nticket_id: fix-export\npriority: P3\n"
        'assignee: "[[Myles Smith]]"\nproject: "[[Project - Eleos]]"\n'
        "source_system: jira\nexternal_id: ELE-42\nmanager_attention: true\n---\n# Fix export\n",
    )
    write_note(
        vault,
        "Actions/Already done.md",
        "---\ntype: action\nstatus: done\naction_id: already-done\n"
        'owners:\n  - "[[Myles Smith]]"\nproject: "[[Project - Eleos]]"\n---\n# Already done\n',
    )
    index = WorkIndex.from_vault(vault)

    result = rank(eligibility(index, today=TODAY).candidates, today=TODAY)

    assert [item.candidate.entity_id for item in result.items] == ["fix-export", "buy-milk"]
    assert result.conflicts == ()
    assert all(item.band in (0, 1, 2) for item in result.items)


def test_rank_factor_and_safety_policy_enum_values() -> None:
    assert [factor.value for factor in RankFactor] == FACTOR_ORDER
    assert [policy.value for policy in SafetyPolicy] == ["manager_attention", "overdue", "blocked"]
