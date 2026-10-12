"""Deterministic candidate eligibility for Command Center ranking.

Read-only derived state: a pure function of the index, with no writes, no model,
and no clock read. Every note is either a candidate or an exclusion carrying
exactly one reason code, decided by the first failing rule in the documented
order, so a caller never has to guess why a row is absent. Deadlines and blockers
are recorded on the candidate; they never exclude one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from worksync.work.config import DEFAULT_CONFIG, WorkConfig
from worksync.work.dates import parse_iso_date
from worksync.work.models import EntityBase, EntityType, entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.review import (
    CLOSED_TICKET_STATUSES,
    OPEN_ACTION_STATUSES,
    OPEN_TICKET_STATUSES,
)
from worksync.work.schema import link_target

CANDIDATE_TYPES: tuple[EntityType, ...] = (EntityType.ACTION, EntityType.TICKET)
CHANGED_ON_FIELDS: tuple[str, ...] = ("last_checked", "updated", "created", "source_date")


class ExclusionReason(StrEnum):
    """The single reason a note is not a rankable candidate."""

    UNSUPPORTED_TYPE = "unsupported_type"
    UNAUTHORIZED = "unauthorized"
    CLOSED_STATUS = "closed_status"
    UNOWNED = "unowned"
    NO_EVIDENCE = "no_evidence"


@dataclass(frozen=True)
class Candidate:
    """One rankable record with the fields ranking reads."""

    entity_id: str
    entity_type: str
    path: str
    title: str
    status: str
    priority: str | None
    owner_ids: tuple[str, ...]
    due: str | None
    project_id: str | None
    blocked: bool
    waiting: bool
    manager_attention: bool
    changed_on: str | None


@dataclass(frozen=True)
class Exclusion:
    """One excluded note with the reason it was excluded."""

    path: str
    entity_id: str
    entity_type: str
    reason: str


@dataclass(frozen=True)
class Eligibility:
    """The candidates and the exclusions for one index."""

    candidates: tuple[Candidate, ...]
    exclusions: tuple[Exclusion, ...]


def eligibility(index: WorkIndex, *, today: date, config: WorkConfig = DEFAULT_CONFIG) -> Eligibility:
    """Return every rankable candidate and one reason per excluded note.

    ``today`` and ``config`` are accepted so a caller passes the same context it
    passes the ranker; eligibility itself reads neither.
    """
    visible_paths = {
        entity.path for entity_type in CANDIDATE_TYPES for entity in index.view_entities(entity_type.value)
    }
    candidates: list[Candidate] = []
    exclusions: list[Exclusion] = []
    for entity in index.entities:
        reason = _exclusion_reason(index, entity, visible_paths)
        if reason is None:
            candidates.append(_candidate(index, entity))
        else:
            exclusions.append(
                Exclusion(
                    path=entity.path,
                    entity_id=entity_id_of(entity),
                    entity_type=entity.entity_type.value,
                    reason=reason.value,
                )
            )
    return Eligibility(
        candidates=tuple(sorted(candidates, key=lambda candidate: candidate.path)),
        exclusions=tuple(sorted(exclusions, key=lambda exclusion: (exclusion.reason, exclusion.path))),
    )


def _exclusion_reason(index: WorkIndex, entity: EntityBase, visible_paths: set[str]) -> ExclusionReason | None:
    """Return the first failing rule for *entity*, or ``None`` when it is eligible."""
    if entity.entity_type not in CANDIDATE_TYPES:
        return ExclusionReason.UNSUPPORTED_TYPE
    if entity.path not in visible_paths:
        return ExclusionReason.UNAUTHORIZED
    if not _status_is_open(entity):
        return ExclusionReason.CLOSED_STATUS
    if not entity.owners:
        return ExclusionReason.UNOWNED
    if not _has_evidence(entity, _project_id(index, entity)):
        return ExclusionReason.NO_EVIDENCE
    return None


def _status_is_open(entity: EntityBase) -> bool:
    """Return True when the entity's status leaves it in play."""
    if entity.entity_type is EntityType.ACTION:
        return entity.status in OPEN_ACTION_STATUSES
    return entity.status in OPEN_TICKET_STATUSES and entity.status not in CLOSED_TICKET_STATUSES


def _has_evidence(entity: EntityBase, project_id: str | None) -> bool:
    """Return True when the note points at its source of truth.

    A resolvable project link is evidence, and so is a source or related reference;
    a note with neither cannot be ranked without guessing where it came from.
    """
    if project_id is not None:
        return True
    if entity.entity_type is EntityType.ACTION:
        return _is_set(getattr(entity, "related_ticket", None))
    return _is_set(getattr(entity, "source_system", None)) or _is_set(getattr(entity, "external_id", None))


def _is_set(value: object | None) -> bool:
    """Return True when a field carries something other than blank text."""
    return value is not None and bool(str(value).strip())


def _candidate(index: WorkIndex, entity: EntityBase) -> Candidate:
    """Project one eligible entity onto the fields ranking reads."""
    return Candidate(
        entity_id=entity_id_of(entity),
        entity_type=entity.entity_type.value,
        path=entity.path,
        title=entity.title,
        status=entity.status,
        priority=getattr(entity, "priority", None),
        owner_ids=_owner_ids(index, entity),
        due=getattr(entity, "due", None) if entity.entity_type is EntityType.ACTION else None,
        project_id=_project_id(index, entity),
        blocked=entity.status == "blocked",
        waiting=entity.status == "waiting",
        manager_attention=bool(getattr(entity, "manager_attention", False)),
        changed_on=_changed_on(entity),
    )


def _owner_ids(index: WorkIndex, entity: EntityBase) -> tuple[str, ...]:
    """Return the owners' canonical ids, or their link targets when unresolved."""
    owner_ids: list[str] = []
    for owner in entity.owners:
        resolved = index.resolve(owner)
        owner_id = entity_id_of(resolved) if resolved is not None else link_target(owner)
        if owner_id not in owner_ids:
            owner_ids.append(owner_id)
    return tuple(owner_ids)


def _project_id(index: WorkIndex, entity: EntityBase) -> str | None:
    """Return the linked project's canonical id, or ``None`` when it does not resolve."""
    project = index.resolve(getattr(entity, "project", None) or "")
    return entity_id_of(project) if project is not None and project.entity_type is EntityType.PROJECT else None


def _changed_on(entity: EntityBase) -> str | None:
    """Return the original string of the latest date field that parses, or ``None``.

    Dates are compared at day granularity, so two fields written on the same day
    tie and the earlier field in ``CHANGED_ON_FIELDS`` wins.
    """
    latest: tuple[date, str] | None = None
    for field_name in CHANGED_ON_FIELDS:
        value = entity.raw.get(field_name)
        parsed = parse_iso_date(value)
        if parsed is None:
            continue
        if latest is None or parsed.date() > latest[0]:
            latest = (parsed.date(), str(value))
    return None if latest is None else latest[1]
