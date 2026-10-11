"""The reported-issue lifecycle state machine (pure).

States: ``reported, confirmed, fixing, fixed, retesting, verified, rejected,
deferred``. A reported issue and a confirmed defect are never collapsed: an issue is
``reported`` until a named reviewer confirms it. ``fixed`` cannot jump to ``verified``
— a passing retest is required. ``reject``, ``defer``, and ``reopen`` are destructive.
"""

from __future__ import annotations

from enum import StrEnum

from worksync.work.lifecycle.machine import Transition, TransitionError, legal_actions_for, resolve


class IssueState(StrEnum):
    """The states a reported issue moves through."""

    REPORTED = "reported"
    CONFIRMED = "confirmed"
    FIXING = "fixing"
    FIXED = "fixed"
    RETESTING = "retesting"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DEFERRED = "deferred"


ISSUE_STATES = frozenset(member.value for member in IssueState)

ISSUE_TRANSITIONS: dict[tuple[str, str], str] = {
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

ISSUE_ACTIONS = tuple(sorted({action for _from, action in ISSUE_TRANSITIONS}))
DESTRUCTIVE_ACTIONS = ("reject", "defer", "reopen")


def validate_transition(state: object, action: object, *, actor: str, reason: str) -> Transition:
    """Validate one issue transition request, failing closed on any gap."""
    return resolve(ISSUE_STATES, ISSUE_TRANSITIONS, DESTRUCTIVE_ACTIONS, state, action, actor=actor, reason=reason)


def apply_transition(state: object, action: object, *, actor: str, reason: str) -> str:
    """Return the next issue state for a legal transition."""
    return validate_transition(state, action, actor=actor, reason=reason).to_state


def legal_actions(state: object) -> tuple[str, ...]:
    """Return the actions legal from *state*, in stable order."""
    return legal_actions_for(ISSUE_STATES, ISSUE_TRANSITIONS, state)


__all__ = [
    "DESTRUCTIVE_ACTIONS",
    "ISSUE_ACTIONS",
    "ISSUE_STATES",
    "ISSUE_TRANSITIONS",
    "IssueState",
    "Transition",
    "TransitionError",
    "apply_transition",
    "legal_actions",
    "validate_transition",
]
