"""The waiting-on taxonomy and records (pure).

Six explicit lanes — ``teammate, vendor, tester, business-acceptance, user-decision,
external-dependency`` — classify what a project is waiting on, so capacity and escalation
follow the real blocker. A source-type default is only a reviewer-overridable suggestion;
it is never auto-assigned. An open waiting-on item requires a canonical project, a current
owner, an explicit dependency, and a valid next review date, and fails closed otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from worksync.work.dates import parse_iso_date
from worksync.work.lifecycle.machine import TransitionError, state_key


class WaitingError(TransitionError):
    """Raised when a waiting-on record or resolution cannot be applied."""


class WaitingLane(StrEnum):
    """The six dependency kinds a waiting-on item is classified by."""

    TEAMMATE = "teammate"
    VENDOR = "vendor"
    TESTER = "tester"
    BUSINESS_ACCEPTANCE = "business-acceptance"
    USER_DECISION = "user-decision"
    EXTERNAL_DEPENDENCY = "external-dependency"


WAITING_LANES = frozenset(member.value for member in WaitingLane)
WAITING_STATUSES = frozenset({"open", "resolved"})

# A source-type default is only a suggestion the reviewer may override.
SOURCE_LANE_DEFAULTS: dict[str, str] = {
    "teammate": "teammate",
    "vendor": "vendor",
    "tester": "tester",
    "business": "business-acceptance",
    "business-acceptance": "business-acceptance",
    "user": "user-decision",
    "user-decision": "user-decision",
    "external": "external-dependency",
    "external-dependency": "external-dependency",
    "servicedesk-plus": "external-dependency",
    "meeting": "teammate",
}


@dataclass(frozen=True)
class WaitingRecord:
    """A waiting-on item: its lane, owner, dependency, review cadence, and status."""

    lane: str
    owner: str = ""
    project: str = ""
    dependency: str = ""
    next_review: str = ""
    evidence: str = ""
    status: str = "open"


def validate_waiting(record: WaitingRecord) -> None:
    """Validate a waiting-on record's lane, status, and open-item required fields."""
    lane = state_key(record.lane)
    if lane not in WAITING_LANES:
        raise WaitingError("unknown_lane", f"Unknown waiting-on lane: {record.lane!r}")
    status = state_key(record.status or "open")
    if status not in WAITING_STATUSES:
        raise WaitingError("unknown_status", f"Unknown waiting-on status: {record.status!r}")
    if status != "open":
        return
    for name, value in (
        ("project", record.project),
        ("owner", record.owner),
        ("dependency", record.dependency),
        ("next_review", record.next_review),
    ):
        if not str(value or "").strip():
            raise WaitingError(f"missing_{name}", f"An open waiting-on item requires: {name}")
    if parse_iso_date(record.next_review) is None:
        raise WaitingError("invalid_next_review", f"Next review is not an ISO date: {record.next_review!r}")


def resolve_waiting(record: WaitingRecord, *, actor: str, reason: str) -> WaitingRecord:
    """Close an open waiting-on item, requiring a named actor and a reason."""
    if not str(actor or "").strip():
        raise WaitingError("missing_actor", "Resolving a waiting-on item requires a named actor.")
    if not str(reason or "").strip():
        raise WaitingError("missing_reason", "Resolving a waiting-on item requires a human-readable reason.")
    if state_key(record.status or "open") == "resolved":
        raise WaitingError("already_resolved", "The waiting-on item is already resolved.")
    validate_waiting(record)
    return replace(record, status="resolved")


def suggest_lane(source_type: object) -> str | None:
    """Return a reviewer-overridable lane suggestion for a source type, or ``None``."""
    return SOURCE_LANE_DEFAULTS.get(state_key(source_type))


__all__ = [
    "SOURCE_LANE_DEFAULTS",
    "WAITING_LANES",
    "WAITING_STATUSES",
    "TransitionError",
    "WaitingError",
    "WaitingLane",
    "WaitingRecord",
    "resolve_waiting",
    "suggest_lane",
    "validate_waiting",
]
