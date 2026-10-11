"""Spec 9 ticket 03: the report/deliverable acceptance state machine (pure)."""

from __future__ import annotations

import pytest

from worksync.work.lifecycle.delivery import (
    DELIVERY_ACTIONS,
    DeliveryState,
    TransitionError,
    apply_transition,
    legal_actions,
    validate_transition,
)

LEGAL = {
    ("untracked", "mark_build_complete"): "build_complete",
    ("build_complete", "ready_for_testing"): "ready_for_testing",
    ("ready_for_testing", "start_testing"): "testing",
    ("testing", "defect_found"): "defect_found",
    ("testing", "accept"): "accepted",
    ("testing", "accept_exception"): "accepted_exception",
    ("defect_found", "fix_reported"): "fix_reported",
    ("fix_reported", "request_retest"): "retest_pending",
    ("retest_pending", "start_retest"): "testing",
    ("retest_pending", "defect_found"): "defect_found",
}


@pytest.mark.parametrize(("state", "action"), sorted(LEGAL))
def test_every_legal_transition(state: str, action: str) -> None:
    result = apply_transition(
        state,
        action,
        actor="Myles",
        reason="Reviewed",
        tester="Tracy",
        business_acceptance="business owner sign-off",
        accepter="Sponsor",
        rationale="Accepted as-is",
    )
    assert result == LEGAL[(state, action)]


@pytest.mark.parametrize(
    ("state", "action"),
    [
        ("fix_reported", "accept"),
        ("build_complete", "accept"),
        ("untracked", "accept"),
        ("ready_for_testing", "accept"),
        ("defect_found", "accept"),
        ("testing", "fix_reported"),
        ("testing", "mark_build_complete"),
        ("untracked", "start_testing"),
        ("accepted", "defect_found"),
        ("accepted_exception", "defect_found"),
    ],
)
def test_every_illegal_transition_fails_closed(state: str, action: str) -> None:
    with pytest.raises(TransitionError) as excinfo:
        apply_transition(state, action, actor="Myles", reason="Reviewed", tester="Tracy", business_acceptance="ok")
    assert excinfo.value.code == "illegal_transition"


def test_fix_reported_cannot_jump_to_accepted() -> None:
    with pytest.raises(TransitionError) as excinfo:
        apply_transition(
            "fix_reported", "accept", actor="Myles", reason="Fixed", tester="Tracy", business_acceptance="ok"
        )
    assert excinfo.value.code == "illegal_transition"


def test_accept_requires_the_named_tester_result() -> None:
    with pytest.raises(TransitionError) as excinfo:
        validate_transition("testing", "accept", actor="Myles", reason="Accept", business_acceptance="sign-off")
    assert excinfo.value.code == "missing_tester"


def test_accept_requires_business_acceptance() -> None:
    with pytest.raises(TransitionError) as excinfo:
        validate_transition("testing", "accept", actor="Myles", reason="Accept", tester="Tracy")
    assert excinfo.value.code == "missing_acceptance"


def test_accept_passes_with_tester_and_acceptance() -> None:
    transition = validate_transition(
        "testing", "accept", actor="Myles", reason="Accept", tester="Tracy", business_acceptance="sign-off"
    )
    assert transition.to_state == "accepted"


def test_accept_exception_requires_accepter_and_rationale() -> None:
    with pytest.raises(TransitionError) as missing_accepter:
        validate_transition(
            "testing", "accept_exception", actor="Myles", reason="Exception", rationale="Accepted as-is"
        )
    assert missing_accepter.value.code == "missing_accepter"

    with pytest.raises(TransitionError) as missing_rationale:
        validate_transition("testing", "accept_exception", actor="Myles", reason="Exception", accepter="Sponsor")
    assert missing_rationale.value.code == "missing_rationale"

    transition = validate_transition(
        "testing", "accept_exception", actor="Myles", reason="Exception", accepter="Sponsor", rationale="Accepted as-is"
    )
    assert transition.to_state == "accepted_exception"


def test_missing_actor_and_reason_fail_closed() -> None:
    with pytest.raises(TransitionError) as actor_exc:
        apply_transition("testing", "defect_found", actor="", reason="Found")
    assert actor_exc.value.code == "missing_actor"

    with pytest.raises(TransitionError) as reason_exc:
        apply_transition("testing", "defect_found", actor="Myles", reason="")
    assert reason_exc.value.code == "missing_reason"


def test_delivery_states_are_distinct_and_actions_exposed() -> None:
    assert set(DELIVERY_ACTIONS) >= {"accept", "accept_exception", "fix_reported", "request_retest"}
    assert DeliveryState.ACCEPTED == "accepted"
    assert set(legal_actions("testing")) == {"accept", "accept_exception", "defect_found"}
