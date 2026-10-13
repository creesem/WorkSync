"""Ticket 08: where a user override takes precedence over the ranking.

Overrides arrive as function input only — persistence is CC-04 — so every case
builds ``Candidate`` objects directly and pins the precedence, drop, and
conflict rules against the fixed ``TODAY``.
"""

from __future__ import annotations

import dataclasses

import pytest

from prioritization_fakes import TODAY
from prioritization_fakes import candidate as _candidate
from worksync.work.models import EntityType
from worksync.work.prioritization import (
    Override,
    OverrideConflict,
    OverrideKind,
    RankedItem,
    Ranking,
    SafetyPolicy,
    rank,
)

KINDS = [
    OverrideKind.PIN,
    OverrideKind.FOCUS_TODAY,
    OverrideKind.DEFER,
    OverrideKind.NOT_RELEVANT,
    OverrideKind.ALWAYS_PRIORITIZE,
]


def _override(override_id: str, target_id: str, kind: str, reason: str = "") -> Override:
    return Override(override_id=override_id, target_id=target_id, kind=kind, reason=reason)


def _ids(result: Ranking) -> list[str]:
    return [item.candidate.entity_id for item in result.items]


def _item(result: Ranking, entity_id: str) -> RankedItem:
    return next(item for item in result.items if item.candidate.entity_id == entity_id)


# Task 2's own output for the candidates below, pinned as a literal order so the
# empty-override case cannot silently drift into a different baseline.
TASK_2_ORDER = ("alpha", "bravo", "charlie")


def test_empty_override_set_matches_ticket_07_output() -> None:
    candidates = (
        _candidate(entity_id="alpha", title="Alpha", priority="P1", due="2026-10-05"),
        _candidate(entity_id="bravo", title="Bravo", priority="P3", status="blocked", blocked=True),
        _candidate(entity_id="charlie", title="Charlie", priority="P2", due=TODAY.isoformat()),
    )

    expected = rank(candidates, today=TODAY)
    result = rank(candidates, today=TODAY, overrides=())

    assert result == expected
    assert tuple(_ids(result)) == TASK_2_ORDER
    assert tuple(_ids(expected)) == TASK_2_ORDER
    assert result.conflicts == ()


def test_pin_elevates_a_low_ranked_candidate_above_the_safety_floors() -> None:
    plain = _candidate(entity_id="plain", title="Plain", priority="P4", due="2026-12-01")
    overdue = _candidate(entity_id="overdue", title="Overdue", priority="P1", due="2026-10-05")

    result = rank((plain, overdue), today=TODAY, overrides=(_override("ov-1", "plain", OverrideKind.PIN),))

    assert _ids(result) == ["plain", "overdue"]
    assert _item(result, "plain").band == -1
    assert _item(result, "plain").band < _item(result, "overdue").band
    assert result.conflicts == ()


@pytest.mark.parametrize("kind", [OverrideKind.PIN, OverrideKind.FOCUS_TODAY, OverrideKind.ALWAYS_PRIORITIZE])
def test_elevating_kinds_all_reach_the_top_band(kind: str) -> None:
    plain = _candidate(entity_id="plain", title="Plain", priority="P4", due="2026-12-01")

    result = rank((plain,), today=TODAY, overrides=(_override("ov-1", "plain", kind),))

    assert result.items[0].band == -1
    assert result.items[0].policies == ()
    assert result.conflicts == ()


def test_pin_changes_only_the_band() -> None:
    plain = _candidate(entity_id="plain", title="Plain", priority="P2", due="2026-12-15", changed_on="2026-10-01")
    expected = rank((plain,), today=TODAY).items[0]

    result = rank((plain,), today=TODAY, overrides=(_override("ov-1", "plain", OverrideKind.PIN, "worth doing now"),))

    pinned = result.items[0]
    assert pinned.band == -1
    assert pinned.score == expected.score
    assert pinned.reasons == expected.reasons
    assert pinned.candidate == expected.candidate
    assert pinned.policies == expected.policies


def test_defer_pushes_an_unprivileged_candidate_to_the_bottom_band() -> None:
    plain = _candidate(entity_id="plain", title="Plain", priority="P2", due="2026-12-01")
    flagged = _candidate(entity_id="flagged", title="Flagged", priority="P3", manager_attention=True)

    result = rank((plain, flagged), today=TODAY, overrides=(_override("ov-1", "plain", OverrideKind.DEFER),))

    assert _ids(result) == ["flagged", "plain"]
    assert _item(result, "plain").band == 3
    assert result.conflicts == ()


def test_not_relevant_drops_an_unprivileged_candidate() -> None:
    kept = _candidate(entity_id="kept", title="Kept", priority="P4", due="2026-12-01")
    dropped = _candidate(entity_id="dropped", title="Dropped", priority="P1", due=TODAY.isoformat())

    result = rank((kept, dropped), today=TODAY, overrides=(_override("ov-1", "dropped", OverrideKind.NOT_RELEVANT),))

    assert _ids(result) == ["kept"]
    assert result.conflicts == ()


def test_defer_on_an_overdue_candidate_is_a_conflict_not_an_override() -> None:
    late = _candidate(entity_id="late", title="Late", priority="P3", due="2026-10-01")
    plain = _candidate(entity_id="plain", title="Plain", priority="P1", due="2026-12-01")
    expected = rank((late, plain), today=TODAY)

    result = rank((late, plain), today=TODAY, overrides=(_override("ov-1", "late", OverrideKind.DEFER, "not now"),))

    assert _ids(result) == _ids(expected)
    assert _item(result, "late").band == _item(expected, "late").band == 0
    assert _item(result, "late").score == _item(expected, "late").score
    assert result.conflicts == (
        OverrideConflict(
            override_id="ov-1",
            entity_id="late",
            kind=OverrideKind.DEFER.value,
            evidence=SafetyPolicy.OVERDUE.value,
            detail="Cannot defer late: overdue",
        ),
    )


def test_not_relevant_on_a_manager_attention_candidate_is_a_conflict() -> None:
    flagged = _candidate(entity_id="flagged", title="Flagged", priority="P3", manager_attention=True)
    expected = rank((flagged,), today=TODAY)

    result = rank((flagged,), today=TODAY, overrides=(_override("ov-1", "flagged", OverrideKind.NOT_RELEVANT),))

    assert _ids(result) == ["flagged"]
    assert _item(result, "flagged").band == _item(expected, "flagged").band == 0
    assert _item(result, "flagged").score == _item(expected, "flagged").score
    assert [(conflict.evidence, conflict.kind) for conflict in result.conflicts] == [
        (SafetyPolicy.MANAGER_ATTENTION.value, OverrideKind.NOT_RELEVANT.value)
    ]
    assert result.conflicts[0].detail == "Cannot not_relevant flagged: manager_attention"


def test_defer_on_a_blocked_candidate_is_a_conflict() -> None:
    stuck = _candidate(
        entity_id="stuck",
        title="Stuck",
        entity_type=EntityType.TICKET.value,
        status="blocked",
        priority="P3",
        blocked=True,
    )
    expected = rank((stuck,), today=TODAY)

    result = rank((stuck,), today=TODAY, overrides=(_override("ov-1", "stuck", OverrideKind.DEFER),))

    assert _item(result, "stuck").band == _item(expected, "stuck").band == 1
    assert [conflict.evidence for conflict in result.conflicts] == [SafetyPolicy.BLOCKED.value]
    assert result.conflicts[0].detail == "Cannot defer stuck: blocked"


def test_pin_on_a_privileged_candidate_applies_without_a_conflict() -> None:
    late = _candidate(entity_id="late", title="Late", priority="P3", due="2026-10-01")

    result = rank((late,), today=TODAY, overrides=(_override("ov-1", "late", OverrideKind.PIN),))

    assert _item(result, "late").band == -1
    assert _item(result, "late").policies == ("overdue",)
    assert result.conflicts == ()


def test_the_conflict_evidence_is_the_first_policy_name() -> None:
    flagged_and_late = _candidate(
        entity_id="flagged-and-late",
        title="Flagged and late",
        priority="P3",
        due="2026-10-01",
        manager_attention=True,
    )

    result = rank(
        (flagged_and_late,),
        today=TODAY,
        overrides=(_override("ov-1", "flagged-and-late", OverrideKind.DEFER),),
    )

    assert _item(result, "flagged-and-late").policies == (
        SafetyPolicy.MANAGER_ATTENTION.value,
        SafetyPolicy.OVERDUE.value,
    )
    assert result.conflicts[0].evidence == SafetyPolicy.MANAGER_ATTENTION.value


def test_an_override_for_an_unknown_target_is_ignored() -> None:
    candidates = (
        _candidate(entity_id="alpha", title="Alpha", priority="P1", due="2026-10-05"),
        _candidate(entity_id="bravo", title="Bravo", priority="P3", status="blocked", blocked=True),
    )
    expected = rank(candidates, today=TODAY)

    result = rank(
        candidates,
        today=TODAY,
        overrides=(
            _override("ov-1", "ghost", OverrideKind.NOT_RELEVANT),
            _override("ov-2", "ghost", OverrideKind.DEFER),
            _override("ov-3", "ghost", OverrideKind.PIN),
        ),
    )

    assert result == expected
    assert result.conflicts == ()


def test_the_later_override_for_one_target_wins() -> None:
    plain = _candidate(entity_id="plain", title="Plain", priority="P2", due="2026-12-01")

    dropped_then_pinned = rank(
        (plain,),
        today=TODAY,
        overrides=(
            _override("ov-1", "plain", OverrideKind.NOT_RELEVANT),
            _override("ov-2", "plain", OverrideKind.PIN),
        ),
    )
    pinned_then_dropped = rank(
        (plain,),
        today=TODAY,
        overrides=(
            _override("ov-2", "plain", OverrideKind.PIN),
            _override("ov-1", "plain", OverrideKind.NOT_RELEVANT),
        ),
    )

    assert _ids(dropped_then_pinned) == ["plain"]
    assert dropped_then_pinned.items[0].band == -1
    assert _ids(pinned_then_dropped) == []


def test_a_pin_and_an_always_prioritize_on_one_target_are_deterministic() -> None:
    plain = _candidate(entity_id="plain", title="Plain", priority="P2", due="2026-12-01")
    flagged = _candidate(entity_id="flagged", title="Flagged", priority="P3", manager_attention=True)
    pin = _override("ov-1", "plain", OverrideKind.PIN)
    always = _override("ov-2", "plain", OverrideKind.ALWAYS_PRIORITIZE)

    forward = rank((plain, flagged), today=TODAY, overrides=(pin, always))
    backward = rank((plain, flagged), today=TODAY, overrides=(always, pin))

    assert forward == backward
    assert _ids(forward) == ["plain", "flagged"]
    assert _item(forward, "plain").band == -1
    assert forward.conflicts == ()


def test_conflicts_are_sorted_by_entity_then_kind_then_override_id() -> None:
    candidates = (
        _candidate(entity_id="bravo-late", title="Bravo late", priority="P3", due="2026-10-01"),
        _candidate(entity_id="alpha-flagged", title="Alpha flagged", priority="P3", manager_attention=True),
        _candidate(entity_id="charlie-stuck", title="Charlie stuck", priority="P3", status="blocked", blocked=True),
    )
    overrides = (
        _override("ov-3", "charlie-stuck", OverrideKind.NOT_RELEVANT),
        _override("ov-2", "bravo-late", OverrideKind.DEFER),
        _override("ov-1", "alpha-flagged", OverrideKind.DEFER),
    )

    result = rank(candidates, today=TODAY, overrides=overrides)

    # Every lowering override is refused, so each row keeps its own safety band
    # and the baseline order still holds.
    assert _ids(result) == ["bravo-late", "alpha-flagged", "charlie-stuck"]
    assert [item.band for item in result.items] == [0, 0, 1]
    assert [(conflict.entity_id, conflict.override_id) for conflict in result.conflicts] == [
        ("alpha-flagged", "ov-1"),
        ("bravo-late", "ov-2"),
        ("charlie-stuck", "ov-3"),
    ]
    assert [conflict.evidence for conflict in result.conflicts] == [
        SafetyPolicy.MANAGER_ATTENTION.value,
        SafetyPolicy.OVERDUE.value,
        SafetyPolicy.BLOCKED.value,
    ]


def test_ranking_with_overrides_is_deterministic() -> None:
    candidates = (
        _candidate(entity_id="alpha", title="Alpha", priority="P1", due="2026-10-05"),
        _candidate(entity_id="bravo", title="Bravo", priority="P3", status="blocked", blocked=True),
        _candidate(entity_id="charlie", title="Charlie", priority="P2", due="2026-12-01"),
    )
    overrides = (
        _override("ov-1", "charlie", OverrideKind.PIN),
        _override("ov-2", "alpha", OverrideKind.NOT_RELEVANT),
    )

    assert rank(candidates, today=TODAY, overrides=overrides) == rank(candidates, today=TODAY, overrides=overrides)


def test_an_unknown_override_kind_is_ignored() -> None:
    """A kind the ranker cannot honour is a bad record: skipped, never an abort."""
    plain = _candidate(entity_id="plain", title="Plain", priority="P2", due="2026-12-01")
    expected = rank((plain,), today=TODAY)

    result = rank((plain,), today=TODAY, overrides=(_override("ov-1", "plain", "snooze"),))

    assert result == expected
    assert result.conflicts == ()


def test_an_unknown_override_kind_for_an_unknown_target_is_ignored() -> None:
    candidates = (
        _candidate(entity_id="alpha", title="Alpha", priority="P1", due="2026-10-05"),
        _candidate(entity_id="bravo", title="Bravo", priority="P3", status="blocked", blocked=True),
    )
    expected = rank(candidates, today=TODAY)

    result = rank(candidates, today=TODAY, overrides=(_override("ov-1", "ghost", "snooze"),))

    assert result == expected
    assert result.conflicts == ()


def test_an_unknown_kind_never_shadows_a_later_known_override() -> None:
    plain = _candidate(entity_id="plain", title="Plain", priority="P2", due="2026-12-01")

    result = rank(
        (plain,),
        today=TODAY,
        overrides=(
            _override("ov-1", "plain", "snooze"),
            _override("ov-2", "plain", OverrideKind.PIN),
        ),
    )

    assert _item(result, "plain").band == -1
    assert result.conflicts == ()


def test_override_kind_values_and_frozen_records() -> None:
    assert [kind.value for kind in OverrideKind] == [
        OverrideKind.PIN.value,
        OverrideKind.FOCUS_TODAY.value,
        OverrideKind.DEFER.value,
        OverrideKind.NOT_RELEVANT.value,
        OverrideKind.ALWAYS_PRIORITIZE.value,
    ]
    assert [kind for kind in KINDS] == list(OverrideKind)

    override = _override("ov-1", "plain", OverrideKind.PIN)
    conflict = OverrideConflict(
        override_id="ov-1",
        entity_id="plain",
        kind=OverrideKind.DEFER.value,
        evidence="overdue",
        detail="Cannot defer plain: overdue",
    )
    assert override.reason == ""
    assert conflict.override_id == "ov-1"
    with pytest.raises(dataclasses.FrozenInstanceError):
        override.target_id = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        conflict.evidence = "blocked"  # type: ignore[misc]
