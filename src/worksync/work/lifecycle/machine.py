"""Shared primitives for the pure lifecycle state machines.

Every machine is an explicit ``(state, action) -> state`` map with a destructive-action
set. Resolution requires a named actor and a human-readable reason, and fails closed on
an unknown state, an unknown action, or an illegal transition. No state is ever inferred
by substring matching and no machine performs IO.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class TransitionError(ValueError):
    """Raised when a lifecycle transition cannot be applied."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class Transition:
    """A validated, legal transition ready to be recorded."""

    from_state: str
    to_state: str
    action: str
    destructive: bool = False


def state_key(state: object) -> str:
    """Normalize a state or action value to its canonical lowercase key."""
    return str(state).strip().casefold()


def resolve(
    states: frozenset[str],
    transitions: Mapping[tuple[str, str], str],
    destructive: tuple[str, ...],
    state: object,
    action: object,
    *,
    actor: str,
    reason: str,
    error: type[TransitionError] = TransitionError,
) -> Transition:
    """Resolve one transition request, failing closed on any gap."""
    key = state_key(state)
    verb = state_key(action)
    if key not in states:
        raise error("unknown_state", f"Unknown lifecycle state: {state!r}", affected=(key,))
    actions = {name for _from, name in transitions}
    if verb not in actions:
        raise error("unknown_action", f"Unknown lifecycle action: {action!r}", affected=(verb,))
    if not str(actor or "").strip():
        raise error("missing_actor", "A transition requires a named actor.")
    if not str(reason or "").strip():
        raise error("missing_reason", "A transition requires a human-readable reason.")
    target = transitions.get((key, verb))
    if target is None:
        raise error("illegal_transition", f"Illegal transition: {key} cannot {verb}", affected=(key, verb))
    return Transition(from_state=key, to_state=target, action=verb, destructive=verb in destructive)


def legal_actions_for(
    states: frozenset[str],
    transitions: Mapping[tuple[str, str], str],
    state: object,
    *,
    error: type[TransitionError] = TransitionError,
) -> tuple[str, ...]:
    """Return the actions legal from *state*, in stable order."""
    key = state_key(state)
    if key not in states:
        raise error("unknown_state", f"Unknown lifecycle state: {state!r}", affected=(key,))
    return tuple(sorted(action for from_state, action in transitions if from_state == key))
