"""Shared read-only result contract for Command Center sections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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


def section_state(result: SectionResult) -> str:
    """Return the single display state represented by a section result."""
    if result.availability == "unavailable":
        return "unavailable"
    if result.source_freshness == "stale":
        return "stale"
    if not result.items:
        return "empty"
    return "items"
