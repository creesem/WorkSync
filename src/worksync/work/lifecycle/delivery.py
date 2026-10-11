"""The report/deliverable acceptance state machine (pure).

States: ``untracked, build_complete, ready_for_testing, testing, defect_found,
fix_reported, retest_pending, accepted, accepted_exception``. Acceptance is never taken
on a builder's or fixer's word: ``accepted`` requires the named tester's result plus
business acceptance, ``accepted_exception`` requires a named accepter and a rationale,
and ``fix_reported`` cannot jump to ``accepted`` — a retest is required.
"""

from __future__ import annotations

from enum import StrEnum

from worksync.work.lifecycle.machine import Transition, TransitionError, legal_actions_for, resolve


class DeliveryState(StrEnum):
    """The states a report or deliverable moves through."""

    UNTRACKED = "untracked"
    BUILD_COMPLETE = "build_complete"
    READY_FOR_TESTING = "ready_for_testing"
    TESTING = "testing"
    DEFECT_FOUND = "defect_found"
    FIX_REPORTED = "fix_reported"
    RETEST_PENDING = "retest_pending"
    ACCEPTED = "accepted"
    ACCEPTED_EXCEPTION = "accepted_exception"


DELIVERY_STATES = frozenset(member.value for member in DeliveryState)

DELIVERY_TRANSITIONS: dict[tuple[str, str], str] = {
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

DELIVERY_ACTIONS = tuple(sorted({action for _from, action in DELIVERY_TRANSITIONS}))
DESTRUCTIVE_ACTIONS = ("accept", "accept_exception")


def validate_transition(
    state: object,
    action: object,
    *,
    actor: str,
    reason: str,
    tester: str = "",
    business_acceptance: str = "",
    accepter: str = "",
    rationale: str = "",
) -> Transition:
    """Validate one delivery transition, enforcing the acceptance gates."""
    transition = resolve(
        DELIVERY_STATES, DELIVERY_TRANSITIONS, DESTRUCTIVE_ACTIONS, state, action, actor=actor, reason=reason
    )
    if transition.action == "accept":
        if not str(tester or "").strip():
            raise TransitionError("missing_tester", "Acceptance requires the named tester's result.")
        if not str(business_acceptance or "").strip():
            raise TransitionError("missing_acceptance", "Acceptance requires business acceptance.")
    if transition.action == "accept_exception":
        if not str(accepter or "").strip():
            raise TransitionError("missing_accepter", "An accepted exception requires a named accepter.")
        if not str(rationale or "").strip():
            raise TransitionError("missing_rationale", "An accepted exception requires a rationale.")
    return transition


def apply_transition(
    state: object,
    action: object,
    *,
    actor: str,
    reason: str,
    tester: str = "",
    business_acceptance: str = "",
    accepter: str = "",
    rationale: str = "",
) -> str:
    """Return the next delivery state for a legal transition."""
    return validate_transition(
        state,
        action,
        actor=actor,
        reason=reason,
        tester=tester,
        business_acceptance=business_acceptance,
        accepter=accepter,
        rationale=rationale,
    ).to_state


def legal_actions(state: object) -> tuple[str, ...]:
    """Return the actions legal from *state*, in stable order."""
    return legal_actions_for(DELIVERY_STATES, DELIVERY_TRANSITIONS, state)


__all__ = [
    "DELIVERY_ACTIONS",
    "DELIVERY_STATES",
    "DELIVERY_TRANSITIONS",
    "DESTRUCTIVE_ACTIONS",
    "DeliveryState",
    "Transition",
    "TransitionError",
    "apply_transition",
    "legal_actions",
    "validate_transition",
]
