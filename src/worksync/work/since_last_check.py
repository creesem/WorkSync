"""The "Since Last Check" read model over the acknowledged checkpoint.

A checkpoint is the acknowledged baseline for "Since Last Check": the content hash of
every vault note at the moment the user acknowledged. It lives in the ``user_state``
zone (``runtime/user_state/checkpoint.json``). The write half —
``acknowledge_checkpoint`` — lives in ``worksync.work.checkpoint``, so this module stays
free of the safety layer and the read-only GUI seam can import it.

The stored shape is ruling R2: ``{"version": 1, "acknowledged_at": "<iso>", "notes":
{path: sha256}}``. A malformed file fails closed on read (ruling R3), while the acknowledge
write never parses the old file — it creates or sha-preconditioned-updates by presence alone,
so a corrupt checkpoint is repaired rather than blocking (ruling R4).

``since_last_check`` diffs the scanner's per-note hashes against a checkpoint and reports
each difference once as ``added`` / ``changed`` / ``removed``; with no checkpoint it reports
``unavailable`` / ``no_checkpoint`` rather than listing every note as added (ruling R3), and
sorts items by path (ruling R5). It is read-only: the diff never writes.

Deliberate deviation (ticket 05, I2): this module's result type is ``SinceLastCheckResult``,
not the entity-shaped ``SectionResult`` of ticket 02. "Since Last Check" rows are arbitrary
notes (not work entities), so the section carries no entity shape; the CC-02 GUI route must
render this section from ``SinceLastCheckResult`` rather than ``SectionResult``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from worksync.inventory.parse import scan_vault

CHECKPOINT_FILENAME = "checkpoint.json"
USER_STATE_ZONE = "user_state"


@dataclass(frozen=True)
class Checkpoint:
    """An acknowledged baseline: when it was taken and every note's content hash."""

    acknowledged_at: str
    notes: dict[str, str]


def user_state_root(runtime_root: str | Path) -> Path:
    """Return the user-state directory under the runtime root."""
    return Path(runtime_root).expanduser().resolve() / USER_STATE_ZONE


def checkpoint_path(runtime_root: str | Path) -> Path:
    """Return the checkpoint file's path under the runtime root."""
    return user_state_root(runtime_root) / CHECKPOINT_FILENAME


def read_checkpoint(runtime_root: str | Path) -> Checkpoint | None:
    """Return the acknowledged checkpoint, or None when none has been written.

    A present-but-malformed file fails closed: raise ``ValueError`` (unreadable JSON, an
    unexpected shape, or a schema version this build does not know). So does a present path
    that is not a regular file (e.g. a directory or a dangling symlink). A missing file is
    the normal "not yet acknowledged" state, not an error.
    """
    path = checkpoint_path(runtime_root)
    if not path.is_file():
        if path.exists() or path.is_symlink():
            raise ValueError(f"Checkpoint is not a regular file: {path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Checkpoint could not be read: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Checkpoint is not an object: {path}")
    if payload.get("version") != 1:
        raise ValueError(f"Checkpoint has an unsupported schema version: {path}")
    acknowledged_at = payload.get("acknowledged_at")
    notes = payload.get("notes")
    if not isinstance(acknowledged_at, str) or not isinstance(notes, dict):
        raise ValueError(f"Checkpoint has an unexpected shape: {path}")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in notes.items()):
        raise ValueError(f"Checkpoint has an unexpected shape: {path}")
    return Checkpoint(acknowledged_at=acknowledged_at, notes=notes)


def current_hashes(vault_root: str | Path) -> dict[str, str]:
    """Return every vault note's current content hash, keyed by path, from one scan."""
    return {record.path: record.content_hash for record in scan_vault(vault_root)}


class ChangeKind(StrEnum):
    """How a note's content hash differs from the acknowledged checkpoint."""

    ADDED = "added"
    CHANGED = "changed"
    REMOVED = "removed"


@dataclass(frozen=True)
class NoteChange:
    """One note that differs from the checkpoint, keyed by its path."""

    path: str
    kind: str
    title: str
    current_hash: str | None
    previous_hash: str | None


@dataclass(frozen=True)
class SinceLastCheckResult:
    """The "Since Last Check" section: a deterministic diff, or why it is unavailable.

    ``generated_at`` is injected so a fixed vault + checkpoint yields an equal result.
    """

    availability: Literal["available", "unavailable"]
    error_state: Literal["no_checkpoint"] | None
    acknowledged_at: str | None
    generated_at: str
    items: tuple[NoteChange, ...]
    total_count: int


def since_last_check(
    vault_root: str | Path,
    checkpoint: Checkpoint | None,
    *,
    generated_at: str,
) -> SinceLastCheckResult:
    """Diff the vault's current note hashes against *checkpoint*.

    With no checkpoint, report ``unavailable`` / ``no_checkpoint`` rather than listing every
    note as added. Items are sorted by path and each path appears at most once, so duplicate
    imports do not multiply events.
    """
    return since_last_check_from_records(scan_vault(vault_root), checkpoint, generated_at=generated_at)


def since_last_check_from_records(
    records: Iterable,
    checkpoint: Checkpoint | None,
    *,
    generated_at: str,
) -> SinceLastCheckResult:
    """Diff already-scanned records against *checkpoint* (see :func:`since_last_check`).

    Each record must expose ``path``, ``title``, and ``content_hash``; callers that already
    hold a scan (e.g. the read seam's cache) pass it here instead of re-scanning.
    """
    if checkpoint is None:
        return SinceLastCheckResult(
            availability="unavailable",
            error_state="no_checkpoint",
            acknowledged_at=None,
            generated_at=generated_at,
            items=(),
            total_count=0,
        )
    scanned = {record.path: (record.title, record.content_hash) for record in records}
    items: list[NoteChange] = []
    for path, (title, content_hash) in scanned.items():
        previous_hash = checkpoint.notes.get(path)
        if previous_hash is None:
            items.append(NoteChange(path, ChangeKind.ADDED, title, content_hash, None))
        elif previous_hash != content_hash:
            items.append(NoteChange(path, ChangeKind.CHANGED, title, content_hash, previous_hash))
    for path, previous_hash in checkpoint.notes.items():
        if path not in scanned:
            items.append(NoteChange(path, ChangeKind.REMOVED, "", None, previous_hash))
    items.sort(key=lambda item: item.path)
    return SinceLastCheckResult(
        availability="available",
        error_state=None,
        acknowledged_at=checkpoint.acknowledged_at,
        generated_at=generated_at,
        items=tuple(items),
        total_count=len(items),
    )


def since_last_check_state(result: SinceLastCheckResult) -> str:
    """Return the single display state represented by a since-last-check result.

    Mirrors ``command_center.section_state``'s vocabulary. This section carries no
    ``source_freshness`` (its rows are plain notes, not entities), so it never reports
    ``stale``: an available checkpoint with nothing changed is ``empty``.
    """
    if result.availability == "unavailable":
        return "unavailable"
    if not result.items:
        return "empty"
    return "items"


def since_last_check_to_dict(result: SinceLastCheckResult) -> dict:
    """Serialize the since-last-check result for the read seam.

    Rows are plain notes, not work entities, so this section does not use the
    entity-shaped ``SectionResult`` serialization: each item carries only the diff fields.
    The section id and the derived ``state`` are carried so the frontend can order and
    render every Command Center section the same way.
    """
    return {
        "section_id": "since_last_check",
        "availability": result.availability,
        "error_state": result.error_state,
        "acknowledged_at": result.acknowledged_at,
        "generated_at": result.generated_at,
        "items": [
            {
                "path": item.path,
                "kind": str(item.kind),
                "title": item.title,
                "current_hash": item.current_hash,
                "previous_hash": item.previous_hash,
            }
            for item in result.items
        ],
        "total_count": result.total_count,
        "state": since_last_check_state(result),
    }
