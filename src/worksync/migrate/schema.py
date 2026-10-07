"""Normalize work-entity frontmatter to the reconciled schema in one transaction.

Detection wraps the single inventory scanner (:func:`worksync.inventory.parse.scan_vault`)
and the pure mapping in :mod:`worksync.work.schema`; it adds no parser. The rewrite edits
only the mapped fields through the parse layer's writer and applies every change as one
:func:`worksync.safety.gateway.commit` transaction with backups, SHA preconditions, and
reverse-order rollback. A note that cannot be mapped deterministically is reported as
skipped and left untouched; nothing is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from worksync.inventory.parse import edit_frontmatter_fields, scan_vault
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.schema import detect_type, normalization_intent

REVIEWER = "worksync-migration"
VERB = "normalize_schema"
REASON = (
    "Normalize work-entity frontmatter to the reconciled schema: action types, "
    "canonical priorities/statuses, attendee keys"
)


@dataclass(frozen=True)
class SchemaChange:
    """One work note to rewrite, with its fresh source hash and new content."""

    path: str
    entity_type: str
    expected: str
    content: str
    changes: tuple[str, ...]


@dataclass(frozen=True)
class SkippedNote:
    """One work note that matches no deterministic mapping."""

    path: str
    entity_type: str
    reason: str


@dataclass(frozen=True)
class NormalizationReport:
    """The detected normalization set: notes to change and notes to report."""

    changes: tuple[SchemaChange, ...] = ()
    skipped: tuple[SkippedNote, ...] = ()


def detect(vault: str | Path, *, when: date | None = None) -> NormalizationReport:
    """Return every work note needing a schema edit, plus the unmappable notes; no writes."""
    migration_date = when or date.today()
    changes: list[SchemaChange] = []
    skipped: list[SkippedNote] = []
    for record in scan_vault(vault):
        entity_type = detect_type(record.frontmatter.get("type"))
        if entity_type is None:
            continue
        intent = normalization_intent(entity_type, record.path, record.frontmatter, when=migration_date)
        if intent.skipped:
            skipped.append(SkippedNote(record.path, entity_type, intent.skipped))
            continue
        if not intent.has_changes:
            continue
        content = edit_frontmatter_fields(
            record.content,
            set_fields=intent.set_fields or None,
            rename_keys=intent.rename_keys or None,
        )
        changes.append(SchemaChange(record.path, entity_type, record.content_hash, content, intent.changes))
    return NormalizationReport(tuple(changes), tuple(skipped))


def apply_normalization(
    vault: str | Path,
    runtime: str | Path,
    *,
    report: NormalizationReport | None = None,
    when: date | None = None,
) -> CommitResult | None:
    """Apply every detected schema edit as one gated canonical transaction.

    Returns ``None`` when there is nothing to change. The gateway owns backups, SHA
    preconditions, rollback, and the journal; a missing or changed source fails closed.
    """
    if report is None:
        report = detect(vault, when=when)
    if not report.changes:
        return None
    vault_path = Path(vault).expanduser().resolve()
    ops = tuple(
        FileOp("update", Path(change.path), "trusted", content=change.content, expected=change.expected)
        for change in report.changes
    )
    changeset = ChangeSet(VERB, ops, reviewer=REVIEWER, reason=REASON)
    return commit(changeset, write_zones(vault_path, runtime))
