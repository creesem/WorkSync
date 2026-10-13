"""Shared read-only result contract for Command Center sections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from worksync.work.config import DEFAULT_CONFIG, WorkConfig
from worksync.work.models import EntityBase, EntityType, entity_id_of
from worksync.work.relationships import related_to
from worksync.work.repository import WorkIndex
from worksync.work.review import (
    AttentionItem,
    attention_by_path,
    attention_items,
    is_open_status,
)
from worksync.work.schema import priority_rank

QUERY_VERSION = 1


@dataclass(frozen=True)
class SectionItem:
    """One entity displayed in a Command Center section."""

    entity_id: str
    entity_type: str
    status: str
    label: str
    path: str
    reason: str
    priority: str | None
    attention: tuple[str, ...]
    timestamps: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SectionResult:
    """A section's items together with its source and availability state."""

    section_id: str
    query_version: int
    generated_at: str
    effective_filters: dict
    items: tuple[SectionItem, ...]
    total_count: int
    source_freshness: Literal["fresh", "stale", "unknown"]
    availability: Literal["available", "unavailable"]
    error_state: Literal["source_unavailable"] | None


def build_section(
    section_id: str,
    items: tuple[SectionItem, ...],
    *,
    generated_at: str,
    effective_filters: dict | None = None,
    source_freshness: Literal["fresh", "stale", "unknown"] = "unknown",
    availability: Literal["available", "unavailable"] = "available",
    error_state: Literal["source_unavailable"] | None = None,
) -> SectionResult:
    """Build a consistent section result and derive its item count."""
    item_tuple = tuple(items)
    return SectionResult(
        section_id=section_id,
        query_version=QUERY_VERSION,
        generated_at=generated_at,
        effective_filters=dict(effective_filters) if effective_filters is not None else {},
        items=item_tuple,
        total_count=len(item_tuple),
        source_freshness=source_freshness,
        availability=availability,
        error_state=error_state,
    )


def timestamps_for_entity(entity: EntityBase) -> tuple[tuple[str, str], ...]:
    """Return the relevant set timestamp fields for an entity as immutable pairs."""
    fields_by_type = {
        EntityType.TICKET: ("last_checked",),
        EntityType.ACTION: ("due",),
        EntityType.PROJECT: ("last_reviewed",),
    }
    timestamps = []
    for field in fields_by_type.get(entity.entity_type, ()):
        value = getattr(entity, field, None)
        if value:
            timestamps.append((field, value))
    return tuple(timestamps)


def _aggregate_section_item(entity: EntityBase, kept: tuple[AttentionItem, ...]) -> SectionItem:
    """Fold one entity's kept attention signals into a single section row."""
    return SectionItem(
        entity_id=entity_id_of(entity),
        entity_type=entity.entity_type.value,
        status=entity.status,
        label=entity.title,
        path=entity.path,
        reason=kept[0].reason,
        priority=getattr(entity, "priority", None),
        attention=tuple(item.kind for item in kept),
        timestamps=timestamps_for_entity(entity),
    )


def needs_attention(
    index: WorkIndex,
    today: date,
    *,
    generated_at: str,
    config: WorkConfig = DEFAULT_CONFIG,
) -> SectionResult:
    """Build the Needs Attention section from the work review signals."""
    selected = tuple(
        item
        for item in attention_items(index, today, config)
        if item.kind in {"blocked", "manager_attention", "overdue_action"} or item.severity == "high"
    )
    entities_by_path = {entity.path: entity for entity in index.entities}
    kept_by_path: dict[str, list[AttentionItem]] = {}
    for item in selected:
        kept_by_path.setdefault(item.path, []).append(item)
    section_items = tuple(
        _aggregate_section_item(entities_by_path[path], tuple(kept)) for path, kept in kept_by_path.items()
    )
    kept_kinds = list(dict.fromkeys(item.kind for item in selected))
    return build_section(
        "needs_attention",
        section_items,
        generated_at=generated_at,
        effective_filters={"kinds": kept_kinds},
    )


def my_priorities(
    index: WorkIndex,
    owner_id: str | None,
    today: date,
    *,
    generated_at: str,
    config: WorkConfig = DEFAULT_CONFIG,
) -> SectionResult:
    """Build the My Priorities section for an explicitly selected person."""
    person = next(
        (
            candidate
            for candidate in index.view_entities(EntityType.PERSON.value)
            if getattr(candidate, "person_id", None) == owner_id
        ),
        None,
    )
    effective_filters = {"owner_id": owner_id}
    if not owner_id or person is None:
        return build_section(
            "my_priorities",
            (),
            generated_at=generated_at,
            effective_filters=effective_filters,
            availability="unavailable",
            error_state="source_unavailable",
        )

    relationships = related_to(index, person)
    entities = tuple(entity for entity in (*relationships.actions, *relationships.tickets) if is_open_status(entity))
    attention_groups = attention_by_path(index, today, config)

    section_items = tuple(
        sorted(
            (
                SectionItem(
                    entity_id=entity_id_of(entity),
                    entity_type=entity.entity_type.value,
                    status=entity.status,
                    label=entity.title,
                    path=entity.path,
                    reason=attention_groups[entity.path][0].reason
                    if attention_groups.get(entity.path)
                    else entity.status,
                    priority=getattr(entity, "priority", None),
                    attention=tuple(item.kind for item in attention_groups.get(entity.path, ())),
                    timestamps=timestamps_for_entity(entity),
                )
                for entity in entities
            ),
            key=lambda item: (
                priority_rank(item.priority) if priority_rank(item.priority) is not None else float("inf"),
                item.label.casefold(),
                item.path,
            ),
        )
    )
    return build_section(
        "my_priorities",
        section_items,
        generated_at=generated_at,
        effective_filters=effective_filters,
    )


def section_state(result: SectionResult) -> str:
    """Return the single display state represented by a section result."""
    if result.availability == "unavailable":
        return "unavailable"
    if result.source_freshness == "stale":
        return "stale"
    if not result.items:
        return "empty"
    return "items"
