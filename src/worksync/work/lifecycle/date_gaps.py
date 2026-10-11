"""The date-gap classification and transitions (pure, plus the canonical due edit).

Six explicit classes replace the legacy three-bucket + substring model: ``confirmed,
conditional, internal-working, completed-occurred, stale-missed, needs-date``. A
conditional or internal date is never presented as a confirmed external commitment. A
missed date is preserved with the reason it changed and the approved revised date added
— never silently replaced — and every date is ISO-validated. A canonical due-date edit
goes through the action writer's SHA-precondition, backup, and rollback workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from worksync.work.dates import parse_iso_date
from worksync.work.lifecycle.machine import Transition, TransitionError, legal_actions_for, resolve, state_key
from worksync.work.writer import ActionPlan, plan_update_action


class DateError(TransitionError):
    """Raised when a date classification or transition cannot be applied."""


class DateClass(StrEnum):
    """The six date classes a project date is classified into."""

    CONFIRMED = "confirmed"
    CONDITIONAL = "conditional"
    INTERNAL_WORKING = "internal-working"
    COMPLETED_OCCURRED = "completed-occurred"
    STALE_MISSED = "stale-missed"
    NEEDS_DATE = "needs-date"


DATE_CLASSES = frozenset(member.value for member in DateClass)

DATE_TRANSITIONS: dict[tuple[str, str], str] = {
    ("needs-date", "confirm"): "confirmed",
    ("needs-date", "conditional"): "conditional",
    ("needs-date", "internal"): "internal-working",
    ("internal-working", "confirm"): "confirmed",
    ("internal-working", "conditional"): "conditional",
    ("internal-working", "miss"): "stale-missed",
    ("internal-working", "complete"): "completed-occurred",
    ("conditional", "confirm"): "confirmed",
    ("conditional", "miss"): "stale-missed",
    ("conditional", "undate"): "needs-date",
    ("confirmed", "miss"): "stale-missed",
    ("confirmed", "complete"): "completed-occurred",
    ("stale-missed", "revise"): "confirmed",
    ("stale-missed", "undate"): "needs-date",
}

DATE_ACTIONS = tuple(sorted({action for _from, action in DATE_TRANSITIONS}))
DESTRUCTIVE_ACTIONS: tuple[str, ...] = ()


@dataclass(frozen=True)
class DateRecord:
    """A project date and the evidence that classifies it."""

    date_class: str
    value: str = ""
    source: str = ""
    previous: str = ""
    revised: str = ""
    reason: str = ""
    owner: str = ""
    dependency: str = ""
    requested: str = ""
    followup: str = ""


def _require(record: DateRecord, *fields: tuple[str, str]) -> None:
    for name, value in fields:
        if not str(value or "").strip():
            raise DateError(f"missing_{name}", f"A {record.date_class} date requires: {name}")


def _iso(record: DateRecord, *fields: tuple[str, str]) -> None:
    for name, value in fields:
        if value and parse_iso_date(value) is None:
            raise DateError("invalid_date", f"{name} is not an ISO date: {value!r}", affected=(str(value),))


def validate_record(record: DateRecord) -> None:
    """Validate a date record's class, ISO dates, and class-specific required fields."""
    cls = state_key(record.date_class)
    if cls not in DATE_CLASSES:
        raise DateError("unknown_class", f"Unknown date class: {record.date_class!r}")
    _iso(
        record,
        ("value", record.value),
        ("previous", record.previous),
        ("revised", record.revised),
        ("requested", record.requested),
    )
    if cls == "needs-date":
        _require(
            record,
            ("owner", record.owner),
            ("dependency", record.dependency),
            ("requested", record.requested),
            ("followup", record.followup),
        )
    elif cls == "confirmed":
        _require(record, ("value", record.value), ("source", record.source))
    elif cls == "stale-missed":
        _require(record, ("previous", record.previous), ("reason", record.reason))
    elif cls in {"conditional", "internal-working", "completed-occurred"}:
        _require(record, ("value", record.value))


def validate_transition(
    state: object,
    action: object,
    *,
    actor: str,
    reason: str,
    previous: str = "",
    revised: str = "",
    source: str = "",
) -> Transition:
    """Validate one date transition, enforcing the confirm-source and missed-date rules."""
    transition = resolve(
        DATE_CLASSES, DATE_TRANSITIONS, DESTRUCTIVE_ACTIONS, state, action, actor=actor, reason=reason, error=DateError
    )
    if transition.action == "confirm" and not str(source or "").strip():
        raise DateError("missing_source", "A confirmed date requires a source or evidence link.")
    if transition.action == "revise":
        if not str(previous or "").strip():
            raise DateError("missing_previous", "Revising a missed date requires the preserved previous date.")
        if not str(revised or "").strip():
            raise DateError("missing_revised", "Revising a missed date requires the approved revised date.")
        if parse_iso_date(previous) is None or parse_iso_date(revised) is None:
            raise DateError("invalid_date", "A preserved or revised date is not an ISO date.")
    return transition


def apply_transition(
    state: object,
    action: object,
    *,
    actor: str,
    reason: str,
    previous: str = "",
    revised: str = "",
    source: str = "",
) -> str:
    """Return the next date class for a legal transition."""
    return validate_transition(
        state, action, actor=actor, reason=reason, previous=previous, revised=revised, source=source
    ).to_state


def legal_actions(state: object) -> tuple[str, ...]:
    """Return the actions legal from *state*, in stable order."""
    return legal_actions_for(DATE_CLASSES, DATE_TRANSITIONS, state, error=DateError)


def plan_due_change(
    vault: str | Path,
    path: str,
    *,
    due: str,
    reason: str,
    reviewer: str,
    expected: str | None = None,
    today: date | None = None,
) -> ActionPlan:
    """Plan a canonical due-date edit through the action writer (SHA precondition)."""
    return plan_update_action(
        vault, path, fields={"due": due}, reason=reason, reviewer=reviewer, expected=expected, today=today
    )


__all__ = [
    "DATE_ACTIONS",
    "DATE_CLASSES",
    "DATE_TRANSITIONS",
    "DateClass",
    "DateError",
    "DateRecord",
    "Transition",
    "apply_transition",
    "legal_actions",
    "plan_due_change",
    "validate_record",
    "validate_transition",
]
