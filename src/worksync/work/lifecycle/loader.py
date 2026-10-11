"""Join canonical records with the derived registry, failing closed at every gap.

A lifecycle record is a canonical entity (ticket/action/meeting) that the registry
tracks. The loader resolves the project by ``project_id``, gathers the records
explicitly linked to it, and joins each registry entry to its canonical entity. A
missing project, a registry entry with no canonical record, or a record that is not
linked to the project fails closed rather than inventing an edge.
"""

from __future__ import annotations

from dataclasses import dataclass

from worksync.work.lifecycle.records import RegistryError, is_record_kind
from worksync.work.lifecycle.registry import LifecycleEntry, LifecycleRegistry, Transition
from worksync.work.models import EntityBase, EntityType
from worksync.work.relationships import related_to
from worksync.work.repository import WorkIndex


@dataclass(frozen=True)
class LifecycleRecord:
    """One canonical record joined with its derived lifecycle state and history."""

    record_id: str
    kind: str
    state: str
    entity: EntityBase
    transitions: tuple[Transition, ...] = ()
    provenance: tuple[str, ...] = ()


def load_project_records(index: WorkIndex, registry: LifecycleRegistry) -> tuple[LifecycleRecord, ...]:
    """Join the registry's entries to the project's canonical records, deterministically."""
    project = _find_project(index, registry.project_id)
    if project is None:
        raise RegistryError(
            "unknown_project", f"No canonical project with id: {registry.project_id}", affected=(registry.project_id,)
        )
    related = related_to(index, project)
    by_path = {entity.path: entity for entity in (*related.tickets, *related.actions, *related.meetings)}

    records: list[LifecycleRecord] = []
    for entry in registry.records:
        entity = by_path.get(entry.record_id)
        if entity is None:
            raise RegistryError(
                "unknown_record",
                f"Registry entry does not match a canonical record linked to the project: {entry.record_id}",
                affected=(entry.record_id,),
            )
        records.append(_record_from(entry, entity))
    records.sort(key=_record_sort)
    return tuple(records)


def _record_from(entry: LifecycleEntry, entity: EntityBase) -> LifecycleRecord:
    if not is_record_kind(entry.record_kind):
        raise RegistryError(
            "unknown_record_kind", f"Unknown lifecycle record kind: {entry.record_kind!r}", affected=(entry.record_id,)
        )
    return LifecycleRecord(
        record_id=entry.record_id,
        kind=entry.record_kind,
        state=entry.lifecycle_state,
        entity=entity,
        transitions=entry.transitions,
        provenance=entry.provenance,
    )


def _find_project(index: WorkIndex, project_id: str) -> EntityBase | None:
    for entity in index.list_type(EntityType.PROJECT.value):
        if getattr(entity, "project_id", None) == project_id:
            return entity
    return None


def _record_sort(record: LifecycleRecord) -> tuple[str, str, str]:
    return (record.kind, record.entity.title.casefold(), record.record_id)
