"""Assign canonical ticket, meeting, and action ids in one gated transaction.

Each type gets its own id field (``ticket_id``, ``meeting_id``, ``action_id``). An id is a
kebab-case slug of the note title, deduplicated per field across the vault and among the
notes being assigned. Notes that already carry their field are left untouched. Writes use
:func:`worksync.safety.gateway.commit` with backups, SHA preconditions, and reverse-order
rollback, so a changed source fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from worksync.inventory.parse import edit_frontmatter_fields, scan_vault
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.schema import (
    CANONICAL_ID_FIELD_BY_TYPE,
    detect_type,
    entity_from_record,
    person_id_slug,
)

REVIEWER = "worksync-migration"
VERB = "normalize_schema"
REASON = "Assign canonical ids to ticket, meeting, and action notes that lack one"


@dataclass(frozen=True)
class EntityIdAssignment:
    """One note to rewrite with its new id, fresh source hash, and content."""

    path: str
    field: str
    value: str
    expected: str
    content: str


def detect_entity_ids(vault: str | Path) -> tuple[EntityIdAssignment, ...]:
    """Return every ticket, meeting, or action note needing an id, with a unique value each."""
    existing: dict[str, set[str]] = {}
    missing = []
    for record in scan_vault(vault):
        entity_type = detect_type(record.frontmatter.get("type"))
        field_name = CANONICAL_ID_FIELD_BY_TYPE.get(entity_type or "")
        if field_name is None:
            continue
        entity = entity_from_record(record)
        if entity is None:
            continue
        value = getattr(entity, field_name, None)
        if value:
            existing.setdefault(field_name, set()).add(value)
        else:
            missing.append((record, field_name))

    assignments: list[EntityIdAssignment] = []
    for record, field_name in sorted(missing, key=lambda item: item[0].path):
        used = existing.setdefault(field_name, set())
        base = person_id_slug(record.title) or field_name.removesuffix("_id")
        candidate = base
        counter = 2
        while candidate in used:
            candidate = f"{base}-{counter}"
            counter += 1
        used.add(candidate)
        content = edit_frontmatter_fields(record.content, set_fields={field_name: candidate})
        assignments.append(EntityIdAssignment(record.path, field_name, candidate, record.content_hash, content))
    return tuple(assignments)


def apply_entity_ids(
    vault: str | Path,
    runtime: str | Path,
    *,
    assignments: tuple[EntityIdAssignment, ...] | None = None,
) -> CommitResult | None:
    """Assign every detected canonical id as one gated transaction, or ``None`` if none."""
    if assignments is None:
        assignments = detect_entity_ids(vault)
    if not assignments:
        return None
    vault_path = Path(vault).expanduser().resolve()
    ops = tuple(
        FileOp("update", Path(item.path), "trusted", content=item.content, expected=item.expected)
        for item in assignments
    )
    return commit(ChangeSet(VERB, ops, reviewer=REVIEWER, reason=REASON), write_zones(vault_path, runtime))
