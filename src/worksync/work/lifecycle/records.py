"""Lifecycle record mapping: which canonical entity holds each workflow record.

ADR-0019 reuses the five entities. A reported issue and a report/deliverable are
``ticket`` notes, a date gap and a waiting-on item are ``action`` notes, and a
decision is a ``meeting`` ``## Decisions`` entry. Transition history and review
ledgers are derived runtime state, never a new entity type, and no state is ever
inferred by substring matching.
"""

from __future__ import annotations

from enum import StrEnum

from worksync.work.models import EntityType


class RegistryError(ValueError):
    """Raised when a lifecycle registry cannot be read, joined, or written."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


class RecordKind(StrEnum):
    """The lifecycle workflows that map onto the five canonical entities."""

    ISSUE = "issue"
    DELIVERY = "delivery"
    DATE_GAP = "date_gap"
    WAITING_ON = "waiting_on"
    DECISION = "decision"


RECORD_ENTITY_TYPE: dict[str, str] = {
    RecordKind.ISSUE.value: EntityType.TICKET.value,
    RecordKind.DELIVERY.value: EntityType.TICKET.value,
    RecordKind.DATE_GAP.value: EntityType.ACTION.value,
    RecordKind.WAITING_ON.value: EntityType.ACTION.value,
    RecordKind.DECISION.value: EntityType.MEETING.value,
}

# New canonical frontmatter fields the mapped entities need. A date gap and a
# waiting-on item live on the action/ticket they qualify; the transition history
# stays derived runtime state.
ISSUE_FIELDS = ("issue_kind", "issue_source", "issue_impact")
DATE_FIELDS = (
    "date_class",
    "date_source",
    "date_previous",
    "date_revised",
    "date_reason",
    "date_owner",
    "date_dependency",
    "date_requested",
    "date_followup",
)
WAITING_FIELDS = (
    "waiting_on_lane",
    "waiting_on_owner",
    "waiting_on_dependency",
    "waiting_on_review",
    "waiting_on_status",
    "waiting_on_evidence",
)

FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    RecordKind.ISSUE.value: ISSUE_FIELDS,
    RecordKind.DELIVERY.value: ISSUE_FIELDS,
    RecordKind.DATE_GAP.value: DATE_FIELDS,
    RecordKind.WAITING_ON.value: WAITING_FIELDS,
    RecordKind.DECISION.value: (),
}


def record_entity_type(kind: object) -> str:
    """Return the canonical entity type for a lifecycle record kind."""
    key = str(kind).strip().casefold()
    if key not in RECORD_ENTITY_TYPE:
        raise RegistryError("unknown_record_kind", f"Unknown lifecycle record kind: {kind!r}")
    return RECORD_ENTITY_TYPE[key]


def is_record_kind(value: object) -> bool:
    """Return True when *value* names a known lifecycle record kind."""
    return str(value).strip().casefold() in RECORD_ENTITY_TYPE


def fields_for_kind(kind: object) -> tuple[str, ...]:
    """Return the canonical frontmatter fields a record kind reads and writes."""
    return FIELDS_BY_KIND.get(str(kind).strip().casefold(), ())
