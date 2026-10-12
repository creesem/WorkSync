"""Assign canonical ticket, meeting, and action ids in one gated transaction.

Each type gets its own id field (``ticket_id``, ``meeting_id``, ``action_id``). An id is a
kebab-case slug of the note title, deduplicated per field across the vault and among the
notes being assigned. Notes that already carry their field are left untouched. Writes use
:func:`worksync.safety.gateway.commit` with backups, SHA preconditions, and reverse-order
rollback, so a changed source fails closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from worksync.inventory.parse import edit_frontmatter_fields, scan_vault
from worksync.safety.files import sha256_file
from worksync.safety.gateway import BACKUP_DIRNAME, commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp, MutationError
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


MAX_ID_LENGTH = 60


def _capped_slug(title: str) -> str:
    """Slugify a title and cut it at the last word boundary within ``MAX_ID_LENGTH``."""
    slug = person_id_slug(title)
    if len(slug) <= MAX_ID_LENGTH:
        return slug
    head = slug[:MAX_ID_LENGTH]
    if slug[MAX_ID_LENGTH] == "-":
        return head
    if "-" in head:
        head = head.rsplit("-", 1)[0]
    return head


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
        base = _capped_slug(Path(record.path).stem) or field_name.removesuffix("_id")
        candidate = base
        counter = 2
        while candidate in used:
            candidate = f"{base}-{counter}"
            counter += 1
        used.add(candidate)
        content = edit_frontmatter_fields(record.content, set_fields={field_name: candidate})
        assignments.append(EntityIdAssignment(record.path, field_name, candidate, record.content_hash, content))
    return tuple(assignments)


def plan_entity_id_revert(
    vault: str | Path,
    runtime: str | Path,
    journal: str | Path,
) -> tuple[FileOp, ...]:
    """Build the ops that restore every note journaled by one ``entity-ids`` apply; no writes.

    Each op carries the note's pre-migration bytes from its backup and the post-migration
    hash as the precondition, so a note edited since the apply fails closed through the
    gateway's ``stale_hash`` check.
    """
    vault_path = Path(vault).expanduser().resolve()
    runtime_path = Path(runtime).expanduser().resolve()
    record = json.loads(Path(journal).read_text(encoding="utf-8"))
    if not record.get("committed") or record.get("verb") != VERB or record.get("reason") != REASON:
        raise MutationError("invalid_journal", f"Not an entity-ids apply journal: {journal}")
    backup_dir = runtime_path / BACKUP_DIRNAME / record["backup_dir"]
    ops = []
    for op in record["ops"]:
        if op["kind"] != "update" or not op.get("backup"):
            raise MutationError("invalid_journal", f"Unexpected operation in journal: {op['path']}")
        target = Path(op["path"]).resolve()
        backup = backup_dir / op["backup"]
        if not backup.is_file() or sha256_file(backup) != op["before"]:
            raise MutationError("backup_corrupt", f"Backup missing or changed: {backup}", affected=(str(backup),))
        content = backup.read_bytes().decode("utf-8")
        ops.append(
            FileOp(
                "update",
                target.relative_to(vault_path),
                "trusted",
                content=content,
                expected=op["after"],
            )
        )
    return tuple(ops)


def revert_entity_ids(
    vault: str | Path,
    runtime: str | Path,
    journal: str | Path,
) -> CommitResult | None:
    """Restore every note from one ``entity-ids`` apply as one gated, journaled transaction."""
    ops = plan_entity_id_revert(vault, runtime, journal)
    if not ops:
        return None
    vault_path = Path(vault).expanduser().resolve()
    reason = f"Revert the canonical id migration recorded in {Path(journal).name}"
    return commit(ChangeSet(VERB, ops, reviewer=REVIEWER, reason=reason), write_zones(vault_path, runtime))


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
