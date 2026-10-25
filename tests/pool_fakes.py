"""Shared builders for potential-task pool tests (schema, store, extraction, API, UI)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from supertag_fakes import write_definition
from worksync.work.pool import (
    CANDIDATE_SCHEMA_VERSION,
    DEFAULT_DEFINITION_ID,
    DEFAULT_DEFINITION_VERSION,
    DefinitionRef,
    HistoryEntry,
    PoolAuditEvent,
    PoolCandidate,
    PoolManifest,
    PoolSource,
    TaskFieldValue,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
HASH = "a" * 64
ACTION_SHA = "b" * 64
CANDIDATE_ID = "cand-0011223344556677"


def meeting_source(**overrides) -> PoolSource:
    source = PoolSource(
        kind="meeting",
        meeting_id="meeting-1",
        meeting_path="10. Meetings/Meeting 1.md",
        meeting_date="2026-10-25",
        content_hash=HASH,
        line=1,
        occurrence=0,
        quote="- [ ] Document the process",
        rule_version="extract-v1",
        extracted_at=NOW.isoformat(),
    )
    return replace(source, **overrides)


def manual_source(**overrides) -> PoolSource:
    source = PoolSource(
        kind="manual",
        initiated_by="Myles",
        provenance_classification="manual-note",
        provenance_note="Raised while reviewing the project.",
    )
    return replace(source, **overrides)


def task_fields(**values: object) -> dict[str, TaskFieldValue]:
    fields = {key: TaskFieldValue() for key in ("project", "owner", "due", "priority")}
    for key, value in values.items():
        if isinstance(value, TaskFieldValue):
            fields[key] = value
        else:
            text = None if value is None else str(value)
            fields[key] = TaskFieldValue(extracted=text, effective=text)
    return fields


_UNSET = object()


def candidate(
    candidate_id: str = CANDIDATE_ID,
    *,
    source: PoolSource | None = None,
    task_fields: dict[str, TaskFieldValue] | None = None,
    history: tuple[HistoryEntry, ...] | None = None,
    definition: object = _UNSET,
    **overrides,
) -> PoolCandidate:
    created = NOW.isoformat()
    if task_fields is None:
        task_fields = {key: TaskFieldValue() for key in ("project", "owner", "due", "priority")}
    resolved_definition = (
        DefinitionRef(DEFAULT_DEFINITION_ID, DEFAULT_DEFINITION_VERSION) if definition is _UNSET else definition
    )
    base = PoolCandidate(
        id=candidate_id,
        schema_version=CANDIDATE_SCHEMA_VERSION,
        revision=1,
        title="Document the process",
        state="new",
        state_reason="meeting_extraction",
        source=source or meeting_source(),
        task_fields=task_fields,
        parse_quality="minimal",
        parse_reasons=("title_only",),
        definition=resolved_definition,
        history=history
        or (
            HistoryEntry(
                at=created,
                by="extractor",
                from_state=None,
                to_state="new",
                reason="meeting_extraction",
                op="extract-v1",
            ),
        ),
        created_at=created,
        updated_at=created,
    )
    return replace(base, **overrides)


def manifest(
    *,
    candidates: tuple[PoolCandidate, ...] = (),
    meetings=(),
    revision: int = 1,
    **overrides,
) -> PoolManifest:
    base = PoolManifest(
        pool_start_at=NOW.isoformat(),
        pool_start_timezone="UTC",
        pool_start_local_date="2026-10-25",
        candidates=candidates,
        meetings=tuple(meetings),
        revision=revision,
        audit=(
            PoolAuditEvent(
                at=NOW.isoformat(),
                by="Myles",
                verb="pool_init",
                reason="Enable the pool",
            ),
        ),
    )
    return replace(base, **overrides)


def write_potential_task(write_note, vault: Path, *, fields: str = "") -> None:
    """Write the ``potential-task`` supertag definition used for pool presentation."""
    write_definition(
        write_note,
        vault,
        "Potential Task",
        tag_id=DEFAULT_DEFINITION_ID,
        name="Potential Task",
        fields=fields,
    )
