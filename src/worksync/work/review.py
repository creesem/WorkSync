"""Read-only attention detection and management rollups.

Everything here is derived state: computed from the index on each call and never
written back to a note. ``today`` is injected so results are deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from worksync.work.config import DEFAULT_CONFIG, WorkConfig
from worksync.work.dates import parse_iso_date
from worksync.work.models import EntityBase, EntityType
from worksync.work.relationships import related_to
from worksync.work.repository import WorkIndex


class AttentionKind(StrEnum):
    BLOCKED = "blocked"
    OVERDUE_ACTION = "overdue_action"
    MANAGER_ATTENTION = "manager_attention"
    WAITING = "waiting"
    REVIEW_DUE = "review_due"
    STALE_REVIEW = "stale_review"
    STALE_TICKET = "stale_ticket"
    UNASSIGNED_TICKET = "unassigned_ticket"


ACTIVE_PROJECT_STATUSES = {"active", "paused", "blocked"}
OPEN_TICKET_STATUSES = {"open", "in_progress", "waiting", "blocked", "escalated"}
OPEN_ACTION_STATUSES = {"open", "in_progress", "waiting"}
CLOSED_TICKET_STATUSES = {"resolved", "closed"}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class AttentionItem:
    """One derived attention signal for an entity."""

    kind: str
    severity: str
    entity_type: str
    title: str
    path: str
    reason: str


@dataclass(frozen=True)
class ProjectReview:
    """A read-only management rollup for one project."""

    project: EntityBase
    people: tuple[EntityBase, ...]
    tickets: tuple[EntityBase, ...]
    actions: tuple[EntityBase, ...]
    meetings: tuple[EntityBase, ...]
    attention: tuple[AttentionItem, ...]
    blockers: tuple[AttentionItem, ...]


@dataclass(frozen=True)
class PersonWorkload:
    """A read-only workload rollup for one person."""

    person: EntityBase
    projects: tuple[EntityBase, ...]
    tickets: tuple[EntityBase, ...]
    actions: tuple[EntityBase, ...]
    meetings: tuple[EntityBase, ...]
    attention: tuple[AttentionItem, ...]
    overdue: tuple[AttentionItem, ...]


def attention_items(index: WorkIndex, today: date, config: WorkConfig = DEFAULT_CONFIG) -> tuple[AttentionItem, ...]:
    """Return all attention items for the vault, in stable severity order."""
    items: list[AttentionItem] = []
    for entity in index.entities:
        entity_type = entity.entity_type
        if entity_type is EntityType.PROJECT:
            items.extend(_project_attention(entity, today, config))
        elif entity_type is EntityType.TICKET:
            items.extend(_ticket_attention(entity, today, config))
        elif entity_type is EntityType.ACTION:
            items.extend(_action_attention(entity, today))
    return _sort_items(items)


def build_project_review(
    index: WorkIndex, project: EntityBase, today: date, config: WorkConfig = DEFAULT_CONFIG
) -> ProjectReview:
    """Build the management rollup for one project."""
    relationships = related_to(index, project)
    related_paths = {
        project.path,
        *(entity.path for entity in relationships.tickets),
        *(entity.path for entity in relationships.actions),
        *(entity.path for entity in relationships.meetings),
    }
    attention = tuple(item for item in attention_items(index, today, config) if item.path in related_paths)
    blockers = tuple(
        item
        for item in attention
        if item.kind in {AttentionKind.BLOCKED.value, AttentionKind.OVERDUE_ACTION.value} or item.severity == "high"
    )
    return ProjectReview(
        project=project,
        people=relationships.people,
        tickets=relationships.tickets,
        actions=relationships.actions,
        meetings=relationships.meetings,
        attention=attention,
        blockers=blockers,
    )


def build_person_workload(
    index: WorkIndex, person: EntityBase, today: date, config: WorkConfig = DEFAULT_CONFIG
) -> PersonWorkload:
    """Build the workload rollup for one person."""
    relationships = related_to(index, person)
    related_paths = {
        person.path,
        *(entity.path for entity in relationships.tickets),
        *(entity.path for entity in relationships.actions),
    }
    attention = tuple(item for item in attention_items(index, today, config) if item.path in related_paths)
    overdue = tuple(item for item in attention if item.kind == AttentionKind.OVERDUE_ACTION.value)
    return PersonWorkload(
        person=person,
        projects=relationships.projects,
        tickets=relationships.tickets,
        actions=relationships.actions,
        meetings=relationships.meetings,
        attention=attention,
        overdue=overdue,
    )


def active_projects(index: WorkIndex) -> tuple[EntityBase, ...]:
    """Return projects that are not done or archived."""
    return tuple(
        project for project in index.list_type(EntityType.PROJECT.value) if project.status in ACTIVE_PROJECT_STATUSES
    )


def active_people(index: WorkIndex) -> tuple[EntityBase, ...]:
    """Return people whose status is active."""
    return tuple(person for person in index.list_type(EntityType.PERSON.value) if person.status == "active")


def project_reviews(index: WorkIndex, today: date, config: WorkConfig = DEFAULT_CONFIG) -> tuple[ProjectReview, ...]:
    """Build the management rollup for every active project in one pass."""
    return tuple(build_project_review(index, project, today, config) for project in active_projects(index))


def person_workloads(index: WorkIndex, today: date, config: WorkConfig = DEFAULT_CONFIG) -> tuple[PersonWorkload, ...]:
    """Build the workload rollup for every active person in one pass."""
    return tuple(build_person_workload(index, person, today, config) for person in active_people(index))


def _project_attention(project: EntityBase, today: date, config: WorkConfig) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    if project.status == "blocked":
        items.append(_item(AttentionKind.BLOCKED, "high", project, "Project is blocked"))
    if project.status in ACTIVE_PROJECT_STATUSES:
        next_review = parse_iso_date(getattr(project, "next_review", None))
        if next_review is not None and next_review.date() <= today:
            items.append(
                _item(AttentionKind.REVIEW_DUE, "medium", project, f"Review due {next_review.date().isoformat()}")
            )
        last_reviewed = parse_iso_date(getattr(project, "last_reviewed", None))
        if last_reviewed is None:
            items.append(_item(AttentionKind.STALE_REVIEW, "medium", project, "Never reviewed"))
        elif (today - last_reviewed.date()).days > config.stale_review_days:
            items.append(
                _item(
                    AttentionKind.STALE_REVIEW, "medium", project, f"Last reviewed {last_reviewed.date().isoformat()}"
                )
            )
    return items


def _ticket_attention(ticket: EntityBase, today: date, config: WorkConfig) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    status = ticket.status
    if status == "blocked":
        items.append(_item(AttentionKind.BLOCKED, "high", ticket, "Ticket is blocked"))
    if getattr(ticket, "manager_attention", False) and status not in CLOSED_TICKET_STATUSES:
        items.append(_item(AttentionKind.MANAGER_ATTENTION, "high", ticket, "Flagged for manager attention"))
    if status == "waiting":
        items.append(_item(AttentionKind.WAITING, "medium", ticket, "Waiting on another party"))
    if status in OPEN_TICKET_STATUSES:
        if not getattr(ticket, "assignee", None) and status in {"open", "in_progress"}:
            items.append(_item(AttentionKind.UNASSIGNED_TICKET, "low", ticket, "No assignee"))
        last_checked = parse_iso_date(getattr(ticket, "last_checked", None))
        if last_checked is None:
            items.append(_item(AttentionKind.STALE_TICKET, "medium", ticket, "Never checked"))
        elif (today - last_checked.date()).days > config.stale_ticket_days:
            items.append(
                _item(AttentionKind.STALE_TICKET, "medium", ticket, f"Last checked {last_checked.date().isoformat()}")
            )
    return items


def _action_attention(action: EntityBase, today: date) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    status = action.status
    if status in OPEN_ACTION_STATUSES:
        due = parse_iso_date(getattr(action, "due", None))
        if due is not None and due.date() < today:
            items.append(_item(AttentionKind.OVERDUE_ACTION, "high", action, f"Overdue since {due.date().isoformat()}"))
    if status == "waiting":
        items.append(_item(AttentionKind.WAITING, "medium", action, "Waiting on another party"))
    return items


def _item(kind: AttentionKind, severity: str, entity: EntityBase, reason: str) -> AttentionItem:
    return AttentionItem(
        kind=kind.value,
        severity=severity,
        entity_type=entity.entity_type.value,
        title=entity.title,
        path=entity.path,
        reason=reason,
    )


def _sort_items(items: list[AttentionItem]) -> tuple[AttentionItem, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 3),
                item.entity_type,
                item.title.casefold(),
                item.path,
                item.kind,
            ),
        )
    )
