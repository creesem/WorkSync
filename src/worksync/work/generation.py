"""The work-generation read model: which actions and tickets are legacy reference.

A generation cutover snapshots every existing action and ticket id (and its current path)
into a ``user_state`` record. Live surfaces exclude those entities; the vault itself is never
modified. A missing record means generation 1 — nothing is excluded, which is the normal
"never cut over" state.

Reads fail closed with ``ValueError`` on a malformed record. The Command Center degrades to
"no exclusions" so the default screen still renders; scans let the error surface instead of
quietly reintroducing legacy work.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from worksync.inventory.parse import IndexRecord, scan_vault
from worksync.work.models import EntityBase, EntityType, entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.since_last_check import user_state_root

GENERATION_FILENAME = "work_generation.json"
SCHEMA_VERSION = 1
FIRST_GENERATION = 1
CUTOVER_GENERATION = 2


@dataclass(frozen=True)
class WorkGeneration:
    """The persisted cutover boundary between legacy and live work."""

    schema_version: int = SCHEMA_VERSION
    generation: int = FIRST_GENERATION
    legacy_action_ids: tuple[str, ...] = ()
    legacy_action_paths: tuple[str, ...] = ()
    legacy_ticket_ids: tuple[str, ...] = ()
    legacy_ticket_paths: tuple[str, ...] = ()
    cutover_at: str = ""
    reviewer: str = ""
    reason: str = ""

    @property
    def cut_over(self) -> bool:
        """Return whether a cutover has been recorded."""
        return self.generation > FIRST_GENERATION

    @property
    def legacy_paths(self) -> frozenset[str]:
        """Return every stored legacy path, for queue-proposal filtering."""
        return frozenset((*self.legacy_action_paths, *self.legacy_ticket_paths))

    def to_dict(self) -> dict:
        """Serialize to the stored shape, returning fresh lists."""
        return {
            "schema_version": self.schema_version,
            "generation": self.generation,
            "legacy_action_ids": list(self.legacy_action_ids),
            "legacy_action_paths": list(self.legacy_action_paths),
            "legacy_ticket_ids": list(self.legacy_ticket_ids),
            "legacy_ticket_paths": list(self.legacy_ticket_paths),
            "cutover_at": self.cutover_at,
            "reviewer": self.reviewer,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkGeneration:
        """Build a generation from stored JSON, raising ``ValueError`` on a bad shape."""
        if not isinstance(data, dict):
            raise ValueError("Work generation is not an object")
        if type(data.get("schema_version")) is not int:
            raise ValueError("Work generation has an invalid schema_version")
        if type(data.get("generation")) is not int or data["generation"] < FIRST_GENERATION:
            raise ValueError("Work generation has an invalid generation")

        def text(key: str) -> str:
            value = data.get(key, "")
            if not isinstance(value, str):
                raise ValueError(f"Work generation has an invalid {key}")
            return value

        def texts(key: str) -> tuple[str, ...]:
            value = data.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"Work generation has an invalid {key}")
            return tuple(value)

        return cls(
            schema_version=data["schema_version"],
            generation=data["generation"],
            legacy_action_ids=texts("legacy_action_ids"),
            legacy_action_paths=texts("legacy_action_paths"),
            legacy_ticket_ids=texts("legacy_ticket_ids"),
            legacy_ticket_paths=texts("legacy_ticket_paths"),
            cutover_at=text("cutover_at"),
            reviewer=text("reviewer"),
            reason=text("reason"),
        )


def generation_path(runtime_root: str | Path) -> Path:
    """Return the generation record's path in the ``user_state`` zone."""
    return user_state_root(runtime_root) / GENERATION_FILENAME


def read_generation(runtime_root: str | Path) -> WorkGeneration:
    """Return the stored generation, or generation 1 when no record exists.

    Raises ``ValueError`` when the record is present but unreadable, malformed, or carries an
    unknown schema version. Callers that render the default screen degrade to no exclusions;
    write paths and scans let the error surface.
    """
    path = generation_path(runtime_root)
    if not path.is_file():
        return WorkGeneration()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Work generation could not be read: {path}") from exc
    try:
        generation = WorkGeneration.from_dict(payload)
    except ValueError as exc:
        raise ValueError(f"Work generation has an unexpected shape: {path}") from exc
    if generation.schema_version != SCHEMA_VERSION:
        raise ValueError(f"Work generation has an unsupported schema version: {path}")
    return generation


def is_legacy(entity: EntityBase, generation: WorkGeneration) -> bool:
    """Return whether *entity* is frozen legacy work (an action or ticket at cutover)."""
    if entity.entity_type is EntityType.ACTION:
        return entity_id_of(entity) in generation.legacy_action_ids or entity.path in generation.legacy_action_paths
    if entity.entity_type is EntityType.TICKET:
        return entity_id_of(entity) in generation.legacy_ticket_ids or entity.path in generation.legacy_ticket_paths
    return False


def is_legacy_path(path: str | None, generation: WorkGeneration) -> bool:
    """Return whether a queue proposal's path belongs to frozen legacy work."""
    return bool(path) and path in generation.legacy_paths


def live_view(
    records: Iterable[IndexRecord],
    root: str | Path,
    generation: WorkGeneration,
) -> tuple[tuple[IndexRecord, ...], WorkIndex]:
    """Return the records and index with legacy action/ticket entities removed.

    Paths are resolved from the full index, so a moved legacy note is still excluded by its
    id. Every other entity type is preserved for project/person/meeting resolution.
    """
    ordered = tuple(records)
    full = WorkIndex.from_records(ordered, root=root)
    if not generation.cut_over:
        return ordered, full
    legacy_paths = {entity.path for entity in full.entities if is_legacy(entity, generation)}
    kept = tuple(record for record in ordered if record.path not in legacy_paths)
    return kept, WorkIndex.from_records(kept, root=root)


def live_index(vault_root: str | Path, runtime_root: str | Path) -> WorkIndex:
    """Scan *vault_root* and return a live index with legacy work excluded."""
    root = Path(vault_root).expanduser().resolve()
    generation = read_generation(runtime_root)
    _records, index = live_view(scan_vault(root), root, generation)
    return index
