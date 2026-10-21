"""Shared read-only result contract for Command Center sections."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from worksync.work.config import DEFAULT_CONFIG, WorkConfig
from worksync.work.models import EntityBase, EntityType, entity_id_of
from worksync.work.prioritization import (
    Override,
    OverrideConflict,
    RankedItem,
    build_candidates,
    rank,
)
from worksync.work.relationships import related_to
from worksync.work.repository import WorkIndex
from worksync.work.review import (
    AttentionItem,
    attention_by_path,
    attention_items,
    is_open_status,
)

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
    override_kind: str | None = None
    band: int | None = None


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
    conflicts: tuple[OverrideConflict, ...] = ()


def build_section(
    section_id: str,
    items: tuple[SectionItem, ...],
    *,
    generated_at: str,
    effective_filters: dict | None = None,
    source_freshness: Literal["fresh", "stale", "unknown"] = "unknown",
    availability: Literal["available", "unavailable"] = "available",
    error_state: Literal["source_unavailable"] | None = None,
    conflicts: tuple[OverrideConflict, ...] = (),
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
        conflicts=tuple(conflicts),
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
    overrides: Iterable[Override] = (),
    config: WorkConfig = DEFAULT_CONFIG,
) -> SectionResult:
    """Build the My Priorities section for an explicitly selected person.

    The rows are ordered by the ranker, with the caller's overrides decided before the
    safety floors: pin, focus-today, and always-prioritize lift a row, defer sinks it,
    and not-relevant drops it. A lowering override refused because of urgent evidence is
    reported in ``conflicts`` and its row stays at its safety band. With no overrides the
    output is the baseline ranking. ``overrides`` are passed in, never read here, so the
    section stays a pure function of its input.
    """
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
    override_tuple = tuple(overrides)
    ranking = rank(
        build_candidates(index, entities, today=today, config=config),
        today=today,
        overrides=override_tuple,
    )
    attention_groups = attention_by_path(index, today, config)
    entities_by_path = {entity.path: entity for entity in entities}
    override_kinds = {override.target_id: override.kind for override in override_tuple}

    section_items = tuple(
        _ranked_section_item(ranked, entities_by_path, attention_groups, override_kinds) for ranked in ranking.items
    )
    return build_section(
        "my_priorities",
        section_items,
        generated_at=generated_at,
        effective_filters=effective_filters,
        conflicts=ranking.conflicts,
    )


def _ranked_section_item(
    ranked: RankedItem,
    entities_by_path: dict[str, EntityBase],
    attention_groups: dict[str, tuple[AttentionItem, ...]],
    override_kinds: dict[str, str],
) -> SectionItem:
    """Fold one ranked candidate into a row carrying its band and requested override."""
    candidate = ranked.candidate
    kept = attention_groups.get(candidate.path, ())
    return SectionItem(
        entity_id=candidate.entity_id,
        entity_type=candidate.entity_type,
        status=candidate.status,
        label=candidate.title,
        path=candidate.path,
        reason=kept[0].reason if kept else candidate.status,
        priority=candidate.priority,
        attention=tuple(item.kind for item in kept),
        timestamps=timestamps_for_entity(entities_by_path[candidate.path]),
        override_kind=override_kinds.get(candidate.entity_id),
        band=ranked.band,
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


def section_item_to_dict(item: SectionItem) -> dict:
    """Serialize one section item; the tuple sequences become JSON lists."""
    return {
        "entity_id": item.entity_id,
        "entity_type": item.entity_type,
        "status": item.status,
        "label": item.label,
        "path": item.path,
        "reason": item.reason,
        "priority": item.priority,
        "attention": list(item.attention),
        "timestamps": [list(timestamp) for timestamp in item.timestamps],
        "override_kind": item.override_kind,
        "band": item.band,
    }


def _conflict_to_dict(conflict: OverrideConflict) -> dict:
    """Serialize one refused override with the evidence that refused it."""
    return {
        "override_id": conflict.override_id,
        "entity_id": conflict.entity_id,
        "kind": conflict.kind,
        "evidence": conflict.evidence,
        "detail": conflict.detail,
    }


def section_result_to_dict(result: SectionResult) -> dict:
    """Serialize a section result for the read seam.

    Every ``SectionResult`` field is carried, plus the derived ``state`` so the frontend can
    render empty vs stale vs unavailable without re-deriving it. ``conflicts`` is a list of
    records so the view can surface a refused override without parsing the ranker's objects.
    """
    return {
        "section_id": result.section_id,
        "query_version": result.query_version,
        "generated_at": result.generated_at,
        "effective_filters": dict(result.effective_filters),
        "items": [section_item_to_dict(item) for item in result.items],
        "total_count": result.total_count,
        "source_freshness": result.source_freshness,
        "availability": result.availability,
        "error_state": result.error_state,
        "conflicts": [_conflict_to_dict(conflict) for conflict in result.conflicts],
        "state": section_state(result),
    }
