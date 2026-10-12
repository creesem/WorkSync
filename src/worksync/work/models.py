"""Typed work entities and closed enums.

Five entities: project, person, ticket, meeting, action. The legacy ``task`` type
is retired and maps to ``action`` on read. Conventions follow
``docs/operational-note-schemas.md`` and ADR-0005; derived state is never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, ClassVar


class EntityType(StrEnum):
    """The five work types selected by the ``type`` frontmatter value."""

    PROJECT = "project"
    PERSON = "person"
    TICKET = "ticket"
    MEETING = "meeting"
    ACTION = "action"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    DONE = "done"
    ARCHIVED = "archived"


class PersonStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class MeetingStatus(StrEnum):
    SCHEDULED = "scheduled"
    HELD = "held"
    CANCELLED = "cancelled"


class ActionStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    WATCH = "watch"
    PARKED = "parked"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Health(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class Effort(StrEnum):
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class SyncMode(StrEnum):
    REFERENCE = "reference"
    SNAPSHOT = "snapshot"
    MANAGED_LOCALLY = "managed-locally"
    GENERATED = "generated"


STATUS_ENUM_BY_TYPE: dict[str, type[Enum]] = {
    EntityType.PROJECT.value: ProjectStatus,
    EntityType.PERSON.value: PersonStatus,
    EntityType.TICKET.value: TicketStatus,
    EntityType.MEETING.value: MeetingStatus,
    EntityType.ACTION.value: ActionStatus,
}

ENUM_FIELDS: dict[str, type[Enum]] = {
    "priority": Priority,
    "health": Health,
    "effort": Effort,
    "sync_mode": SyncMode,
}

# Wikilink-valued fields per type, used for relationship resolution and link warnings.
LINK_FIELDS_BY_TYPE: dict[str, tuple[str, ...]] = {
    EntityType.PROJECT.value: ("owners", "people"),
    EntityType.PERSON.value: ("manager",),
    EntityType.TICKET.value: ("assignee", "project"),
    EntityType.MEETING.value: ("attendees", "projects", "project"),
    EntityType.ACTION.value: ("owners", "project", "related_ticket"),
}


@dataclass(frozen=True)
class EntityBase:
    """Fields shared by every work entity."""

    path: str
    title: str
    status: str
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def entity_type(self) -> EntityType:
        """Return the entity's type. Overridden by each subclass."""
        raise NotImplementedError

    @property
    def owners(self) -> tuple[str, ...]:
        """Return the entity's accountable people, whichever field names them."""
        return ()


@dataclass(frozen=True)
class Project(EntityBase):
    entity_type: ClassVar[EntityType] = EntityType.PROJECT

    owners: tuple[str, ...] = ()
    people: tuple[str, ...] = ()
    priority: str | None = None
    health: str | None = None
    effort: str | None = None
    portfolio: str | None = None
    systems: tuple[str, ...] = ()
    next_action: str | None = None
    last_reviewed: str | None = None
    next_review: str | None = None
    project_id: str | None = None
    search_terms: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Person(EntityBase):
    entity_type: ClassVar[EntityType] = EntityType.PERSON

    role: str | None = None
    team: str | None = None
    manager: str | None = None
    email: str | None = None
    person_id: str | None = None


@dataclass(frozen=True)
class Ticket(EntityBase):
    entity_type: ClassVar[EntityType] = EntityType.TICKET

    assignee: str | None = None
    priority: str | None = None
    application: str | None = None
    project: str | None = None
    source_system: str | None = None
    external_id: str | None = None
    sync_mode: str | None = None
    next_action: str | None = None
    manager_attention: bool = False
    ticket_id: str | None = None
    last_checked: str | None = None

    @property
    def owners(self) -> tuple[str, ...]:
        return (self.assignee,) if self.assignee else ()


@dataclass(frozen=True)
class Meeting(EntityBase):
    entity_type: ClassVar[EntityType] = EntityType.MEETING

    date: str | None = None
    attendees: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    project: str | None = None
    meeting_type: str | None = None
    source_system: str | None = None
    external_id: str | None = None
    sync_mode: str | None = None
    meeting_id: str | None = None

    @property
    def owners(self) -> tuple[str, ...]:
        return self.attendees


@dataclass(frozen=True)
class Action(EntityBase):
    entity_type: ClassVar[EntityType] = EntityType.ACTION

    owners: tuple[str, ...] = ()
    priority: str | None = None
    due: str | None = None
    project: str | None = None
    related_ticket: str | None = None
    waiting_on: str | None = None
    completed: str | None = None
    next_action: str | None = None
    action_id: str | None = None


WorkEntity = Project | Person | Ticket | Meeting | Action


def entity_id_of(entity: EntityBase) -> str:
    """Return an entity's canonical id, falling back to its vault path."""
    id_field = {
        EntityType.PROJECT: "project_id",
        EntityType.PERSON: "person_id",
        EntityType.TICKET: "ticket_id",
        EntityType.MEETING: "meeting_id",
        EntityType.ACTION: "action_id",
    }[entity.entity_type]
    return getattr(entity, id_field) or entity.path


ENTITY_CLASS_BY_TYPE: dict[str, type[EntityBase]] = {
    EntityType.PROJECT.value: Project,
    EntityType.PERSON.value: Person,
    EntityType.TICKET.value: Ticket,
    EntityType.MEETING.value: Meeting,
    EntityType.ACTION.value: Action,
}
