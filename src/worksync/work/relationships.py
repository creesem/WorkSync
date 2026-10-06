"""Deterministic relationship queries over the work index.

Relationships derive only from explicit wikilink fields; nothing is stored or
invented, and an unresolved link never produces an edge.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from worksync.work.models import EntityBase, EntityType
from worksync.work.repository import WorkIndex


@dataclass(frozen=True)
class Relationships:
    """Entities related to one entity, each tuple sorted deterministically."""

    people: tuple[EntityBase, ...] = ()
    projects: tuple[EntityBase, ...] = ()
    tickets: tuple[EntityBase, ...] = ()
    actions: tuple[EntityBase, ...] = ()
    meetings: tuple[EntityBase, ...] = ()


def related_to(index: WorkIndex, entity: EntityBase) -> Relationships:
    """Return the entities related to *entity* via its explicit wikilink fields."""
    if entity.entity_type is EntityType.PROJECT:
        return _project_relationships(index, entity)
    if entity.entity_type is EntityType.PERSON:
        return _person_relationships(index, entity)
    return Relationships()


def _project_relationships(index: WorkIndex, project: EntityBase) -> Relationships:
    links = (*getattr(project, "owners", ()), *getattr(project, "people", ()))
    people = _resolve_many(index, links)
    tickets = _matching(index, index.list_type("ticket"), "project", project)
    actions = _matching(index, index.list_type("action"), "project", project)
    meetings = _ordered(
        meeting
        for meeting in index.list_type("meeting")
        if _value_matches(index, getattr(meeting, "projects", None), project)
        or _value_matches(index, getattr(meeting, "project", None), project)
    )
    return Relationships(people=people, tickets=tickets, actions=actions, meetings=meetings)


def _person_relationships(index: WorkIndex, person: EntityBase) -> Relationships:
    projects = _ordered(
        project
        for project in index.list_type("project")
        if _value_matches(index, getattr(project, "owners", None), person)
        or _value_matches(index, getattr(project, "people", None), person)
    )
    tickets = _matching(index, index.list_type("ticket"), "assignee", person)
    actions = _matching(index, index.list_type("action"), "owners", person)
    meetings = _ordered(
        meeting
        for meeting in index.list_type("meeting")
        if _value_matches(index, getattr(meeting, "attendees", None), person)
    )
    manager = _resolve_many(index, (getattr(person, "manager", None),))
    return Relationships(people=manager, projects=projects, tickets=tickets, actions=actions, meetings=meetings)


def _matching(
    index: WorkIndex, candidates: Iterable[EntityBase], field_name: str, target: EntityBase
) -> tuple[EntityBase, ...]:
    return _ordered(
        candidate for candidate in candidates if _value_matches(index, getattr(candidate, field_name, None), target)
    )


def _value_matches(index: WorkIndex, value: object, target: EntityBase) -> bool:
    if value is None:
        return False
    values = value if isinstance(value, list | tuple) else (value,)
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        resolved = index.resolve(text)
        if resolved is not None and resolved.path == target.path:
            return True
    return False


def _resolve_many(index: WorkIndex, links: Iterable[object | None]) -> tuple[EntityBase, ...]:
    resolved: dict[str, EntityBase] = {}
    for link in links:
        if not link:
            continue
        entity = index.resolve(str(link))
        if entity is not None:
            resolved.setdefault(entity.path, entity)
    return _ordered(resolved.values())


def _ordered(entities: Iterable[EntityBase]) -> tuple[EntityBase, ...]:
    unique = {entity.path: entity for entity in entities}
    return tuple(sorted(unique.values(), key=lambda entity: (entity.title.casefold(), entity.path)))
