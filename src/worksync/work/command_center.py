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
from worksync.work.section_meta import section_meta

QUERY_VERSION = 1


@dataclass(frozen=True)
class SectionItem:
    """One entity displayed in a Command Center section."""

    entity_id: str
    entity_type: str
    status: str
    label: str
    path: str
    reason: str | None
    priority: str | None
    attention: tuple[str, ...]
    timestamps: tuple[tuple[str, str], ...] = ()
    override_kind: str | None = None
    band: int | None = None
    owner: str | None = None
    owner_id: str | None = None
    due: str | None = None
    severity: str | None = None


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


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _top_severity(signals: Iterable[AttentionItem]) -> str | None:
    """Return the highest attention severity carried by an entity's signals, or ``None``."""
    severities = [signal.severity for signal in signals if signal.severity]
    if not severities:
        return None
    return min(severities, key=lambda value: _SEVERITY_ORDER.get(value, 3))


def _owner_fields(entity: EntityBase, index: WorkIndex) -> tuple[str | None, str | None]:
    """Return ``(owner_id, owner)`` for an entity's first accountable person.

    The owner reference is resolved through the index's person lookup — the same one the rest
    of the engine uses — so a wikilink, alias, or id all resolve. ``owner`` is the
    engine-resolved display label and ``owner_id`` the person's stable id; both are ``None``
    when the person is not in the registry, so the shell shows "Not recorded" rather than
    inventing a name.
    """
    owners = entity.owners
    if not owners:
        return None, None
    person = index.get("person", owners[0])
    if person is None:
        return None, None
    return getattr(person, "person_id", None), person.title


def _aggregate_section_item(entity: EntityBase, kept: tuple[AttentionItem, ...], index: WorkIndex) -> SectionItem:
    """Fold one entity's kept attention signals into a single section row."""
    owner_id, owner = _owner_fields(entity, index)
    return SectionItem(
        entity_id=entity_id_of(entity),
        entity_type=entity.entity_type.value,
        status=entity.status,
        label=entity.title,
        path=entity.path,
        reason=kept[0].reason if kept else None,
        priority=getattr(entity, "priority", None),
        attention=tuple(item.kind for item in kept),
        timestamps=timestamps_for_entity(entity),
        owner=owner,
        owner_id=owner_id,
        due=getattr(entity, "due", None),
        severity=_top_severity(kept),
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
        _aggregate_section_item(entities_by_path[path], tuple(kept), index) for path, kept in kept_by_path.items()
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
        _ranked_section_item(ranked, entities_by_path, attention_groups, override_kinds, index)
        for ranked in ranking.items
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
    index: WorkIndex,
) -> SectionItem:
    """Fold one ranked candidate into a row carrying its band and requested override."""
    candidate = ranked.candidate
    kept = attention_groups.get(candidate.path, ())
    entity = entities_by_path[candidate.path]
    owner_id, owner = _owner_fields(entity, index)
    return SectionItem(
        entity_id=candidate.entity_id,
        entity_type=candidate.entity_type,
        status=candidate.status,
        label=candidate.title,
        path=candidate.path,
        reason=kept[0].reason if kept else candidate.status,
        priority=candidate.priority,
        attention=tuple(item.kind for item in kept),
        timestamps=timestamps_for_entity(entity),
        override_kind=override_kinds.get(candidate.entity_id),
        band=ranked.band,
        owner=owner,
        owner_id=owner_id,
        due=getattr(entity, "due", None),
        severity=_top_severity(kept),
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
        "owner": item.owner,
        "owner_id": item.owner_id,
        "due": item.due,
        "severity": item.severity,
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
    title, subtitle = section_meta(result.section_id)
    return {
        "section_id": result.section_id,
        "title": title,
        "subtitle": subtitle,
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


def entity_contract_dict(
    entity: EntityBase,
    *,
    index: WorkIndex,
    attention_kinds: tuple[str, ...] = (),
) -> dict:
    """Serialize one entity as the contract's intrinsic detail object.

    Only the declared contract fields travel: no raw frontmatter, no note body, and no
    unindexed file content. ``owner`` is the engine-resolved label (``None`` when unknown).
    """
    owner_id, owner = _owner_fields(entity, index)
    return {
        "entity_id": entity_id_of(entity),
        "entity_type": entity.entity_type.value,
        "label": entity.title,
        "status": entity.status,
        "priority": getattr(entity, "priority", None),
        "owner": owner,
        "owner_id": owner_id,
        "due": getattr(entity, "due", None),
        "path": entity.path,
        "attention": list(attention_kinds),
        "timestamps": [list(timestamp) for timestamp in timestamps_for_entity(entity)],
        "tags": list(entity.tags),
        "aliases": list(entity.aliases),
    }
