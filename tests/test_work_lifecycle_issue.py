"""Spec 9 ticket 02: the reported-issue lifecycle state machine (pure)."""

from __future__ import annotations

import pytest

from worksync.work.lifecycle.issue import (
    DESTRUCTIVE_ACTIONS,
    ISSUE_ACTIONS,
    IssueState,
    TransitionError,
    apply_transition,
    legal_actions,
    validate_transition,
)

LEGAL = {
    ("reported", "confirm"): "confirmed",
    ("reported", "reject"): "rejected",
    ("reported", "defer"): "deferred",
    ("confirmed", "start_fix"): "fixing",
    ("confirmed", "reject"): "rejected",
    ("confirmed", "defer"): "deferred",
    ("fixing", "fix_reported"): "fixed",
    ("fixing", "defer"): "deferred",
    ("fixed", "start_retest"): "retesting",
    ("fixed", "defer"): "deferred",
    ("retesting", "verify"): "verified",
    ("retesting", "fail_retest"): "fixing",
    ("retesting", "defer"): "deferred",
    ("verified", "reopen"): "reported",
    ("rejected", "reopen"): "reported",
    ("deferred", "reopen"): "reported",
}


@pytest.mark.parametrize(("state", "action"), sorted(LEGAL))
def test_every_legal_transition(state: str, action: str) -> None:
    result = apply_transition(state, action, actor="Myles", reason="Reviewed")
    assert result == LEGAL[(state, action)]


@pytest.mark.parametrize(
    ("state", "action"),
    [
        ("reported", "verify"),
        ("reported", "start_fix"),
        ("confirmed", "fix_reported"),
        ("fixing", "verify"),
        ("fixed", "verify"),
        ("retesting", "confirm"),
        ("verified", "confirm"),
        ("rejected", "confirm"),
        ("deferred", "confirm"),
        ("reported", "fail_retest"),
    ],
)
def test_every_illegal_transition_fails_closed(state: str, action: str) -> None:
    with pytest.raises(TransitionError) as excinfo:
        apply_transition(state, action, actor="Myles", reason="Reviewed")
    assert excinfo.value.code == "illegal_transition"


def test_fixed_cannot_jump_to_verified() -> None:
    with pytest.raises(TransitionError) as excinfo:
        apply_transition("fixed", "verify", actor="Myles", reason="Looks done")
    assert excinfo.value.code == "illegal_transition"


def test_missing_actor_fails_closed() -> None:
    with pytest.raises(TransitionError) as excinfo:
        apply_transition("reported", "confirm", actor="  ", reason="Reproduced")
    assert excinfo.value.code == "missing_actor"


def test_missing_reason_fails_closed() -> None:
    with pytest.raises(TransitionError) as excinfo:
        apply_transition("reported", "confirm", actor="Myles", reason="")
    assert excinfo.value.code == "missing_reason"


def test_unknown_state_and_action_fail_closed() -> None:
    with pytest.raises(TransitionError) as state_exc:
        apply_transition("saga", "confirm", actor="Myles", reason="Reviewed")
    assert state_exc.value.code == "unknown_state"

    with pytest.raises(TransitionError) as action_exc:
        apply_transition("reported", "launch", actor="Myles", reason="Reviewed")
    assert action_exc.value.code == "unknown_action"


def test_reject_defer_and_reopen_are_destructive() -> None:
    assert {"reject", "defer", "reopen"} <= set(DESTRUCTIVE_ACTIONS)
    assert set(ISSUE_ACTIONS) >= set(DESTRUCTIVE_ACTIONS)


def test_validate_transition_carries_from_and_to_and_destructive_flag() -> None:
    transition = validate_transition("reported", "reject", actor="Myles", reason="Not a defect")
    assert transition.from_state == "reported"
    assert transition.to_state == "rejected"
    assert transition.destructive is True
    assert validate_transition("reported", "confirm", actor="Myles", reason="Reproduced").destructive is False


def test_legal_actions_are_reported_per_state() -> None:
    assert set(legal_actions("reported")) == {"confirm", "reject", "defer"}
    assert legal_actions("verified") == ("reopen",)
    assert set(legal_actions(IssueState.RETESTING)) == {"verify", "fail_retest", "defer"}
