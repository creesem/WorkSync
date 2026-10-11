"""Assign a stable person_id to every person note that lacks one, in one gated transaction.

Person identity needs an immutable, path-independent id. This migration derives a kebab-case
id from each person's display name, deduplicating against ids already present in the vault and
among the notes being assigned, and writes them as one
:func:`worksync.safety.gateway.commit` transaction with backups, SHA preconditions, and
reverse-order rollback. A note that already has a person_id is left untouched; nothing is
guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from worksync.inventory.parse import edit_frontmatter_fields, scan_vault
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.models import EntityType
from worksync.work.schema import detect_type, entity_from_record, person_id_slug

REVIEWER = "worksync-migration"
VERB = "normalize_schema"
REASON = "Assign a stable person_id to person notes that lack one"


@dataclass(frozen=True)
class PersonIdAssignment:
    """One person note to rewrite with its new id, fresh source hash, and content."""

    path: str
    person_id: str
    expected: str
    content: str


def detect_person_ids(vault: str | Path) -> tuple[PersonIdAssignment, ...]:
    """Return every person note needing a person_id, with a unique id each; no writes."""
    existing: set[str] = set()
    missing = []
    for record in scan_vault(vault):
        if detect_type(record.frontmatter.get("type")) != EntityType.PERSON.value:
            continue
        entity = entity_from_record(record)
        if entity is None:
            continue
        person_id = getattr(entity, "person_id", None)
        if person_id:
            existing.add(person_id)
        else:
            missing.append(record)

    used = set(existing)
    assignments: list[PersonIdAssignment] = []
    for record in sorted(missing, key=lambda item: item.path):
        base = person_id_slug(record.title) or "person"
        candidate = base
        counter = 2
        while candidate in used:
            candidate = f"{base}-{counter}"
            counter += 1
        used.add(candidate)
        content = edit_frontmatter_fields(record.content, set_fields={"person_id": candidate})
        assignments.append(PersonIdAssignment(record.path, candidate, record.content_hash, content))
    return tuple(assignments)


def apply_person_ids(
    vault: str | Path,
    runtime: str | Path,
    *,
    assignments: tuple[PersonIdAssignment, ...] | None = None,
) -> CommitResult | None:
    """Assign every detected person_id as one gated canonical transaction, or ``None`` if none.

    The gateway owns backups, SHA preconditions, rollback, and the journal; a changed source
    fails closed.
    """
    if assignments is None:
        assignments = detect_person_ids(vault)
    if not assignments:
        return None
    vault_path = Path(vault).expanduser().resolve()
    ops = tuple(
        FileOp("update", Path(item.path), "trusted", content=item.content, expected=item.expected)
        for item in assignments
    )
    return commit(ChangeSet(VERB, ops, reviewer=REVIEWER, reason=REASON), write_zones(vault_path, runtime))
