"""Spec 9 ticket 05: the waiting-on taxonomy and records."""

from __future__ import annotations

import pytest

from worksync.work.lifecycle.waiting import (
    WAITING_LANES,
    WaitingError,
    WaitingLane,
    WaitingRecord,
    resolve_waiting,
    suggest_lane,
    validate_waiting,
)


def _open(**overrides: object) -> WaitingRecord:
    base: dict[str, object] = {
        "lane": "vendor",
        "owner": "Myles",
        "project": "Project - Eleos",
        "dependency": "Vendor quote",
        "next_review": "2026-11-01",
    }
    base.update(overrides)
    return WaitingRecord(**base)  # type: ignore[arg-type]


def test_six_waiting_lanes_are_first_class() -> None:
    assert {
        "teammate",
        "vendor",
        "tester",
        "business-acceptance",
        "user-decision",
        "external-dependency",
    } == WAITING_LANES
    assert WaitingLane.BUSINESS_ACCEPTANCE == "business-acceptance"


@pytest.mark.parametrize("lane", sorted(WAITING_LANES))
def test_each_lane_is_accepted(lane: str) -> None:
    validate_waiting(_open(lane=lane))


def test_unknown_lane_fails_closed() -> None:
    with pytest.raises(WaitingError) as excinfo:
        validate_waiting(_open(lane="whoever"))
    assert excinfo.value.code == "unknown_lane"


def test_open_item_missing_required_fields_fails_closed() -> None:
    for field_name, code in (
        ("project", "missing_project"),
        ("owner", "missing_owner"),
        ("dependency", "missing_dependency"),
        ("next_review", "missing_next_review"),
    ):
        with pytest.raises(WaitingError) as excinfo:
            validate_waiting(_open(**{field_name: ""}))
        assert excinfo.value.code == code


def test_invalid_next_review_fails_closed() -> None:
    with pytest.raises(WaitingError) as excinfo:
        validate_waiting(_open(next_review="soon"))
    assert excinfo.value.code == "invalid_next_review"


def test_resolution_requires_reason_and_closes_the_item() -> None:
    with pytest.raises(WaitingError) as excinfo:
        resolve_waiting(_open(), actor="Myles", reason="")
    assert excinfo.value.code == "missing_reason"

    resolved = resolve_waiting(_open(), actor="Myles", reason="Vendor replied")
    assert resolved.status == "resolved"

    with pytest.raises(WaitingError) as already:
        resolve_waiting(resolved, actor="Myles", reason="Again")
    assert already.value.code == "already_resolved"


def test_source_type_default_is_a_suggestion_and_overridable() -> None:
    assert suggest_lane("vendor") == "vendor"
    assert suggest_lane("servicedesk-plus") == "external-dependency"
    assert suggest_lane("unknown-source") is None

    # The suggestion is never auto-assigned: an explicit, different lane is honored.
    validate_waiting(_open(lane="teammate"))
