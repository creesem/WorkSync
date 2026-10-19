"""The since-last-check checkpoint store and read model.

A checkpoint is the acknowledged baseline for "Since Last Check": the content hash of
every vault note at the moment the user acknowledged. It lives in the ``user_state``
zone (``runtime/user_state/checkpoint.json``), so the one write here is journaled and
backed up but never touches a note — acknowledging can never complete an action.

The stored shape is ruling R2: ``{"version": 1, "acknowledged_at": "<iso>", "notes":
{path: sha256}}``. A malformed file fails closed on read (ruling R3), while acknowledging
never parses the old file — it creates or sha-preconditioned-updates by presence alone,
so a corrupt checkpoint is repaired rather than blocking (ruling R4).

``since_last_check`` diffs the scanner's per-note hashes against a checkpoint and reports
each difference once as ``added`` / ``changed`` / ``removed``; with no checkpoint it reports
``unavailable`` / ``no_checkpoint`` rather than listing every note as added (ruling R3), and
sorts items by path (ruling R5). It is read-only: the diff never writes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from worksync.inventory.parse import scan_vault
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones

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

    A present-but-malformed file fails closed: raise ``ValueError`` (unreadable JSON or an
    unexpected shape). A missing file is the normal "not yet acknowledged" state, not an error.
    """
    path = checkpoint_path(runtime_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Checkpoint could not be read: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Checkpoint is not an object: {path}")
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


def acknowledge_checkpoint(
    vault_root: str | Path,
    runtime_root: str | Path,
    snapshot: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> CommitResult:
    """Write *snapshot* (path -> sha256) as the acknowledged checkpoint, atomically.

    Creates the file on first acknowledge and sha-preconditioned-updates it thereafter. Writes
    only ``checkpoint.json`` in the ``user_state`` zone — never a note — so acknowledging can
    never complete an action.
    """
    when = now or datetime.now(UTC)
    target = checkpoint_path(runtime_root)
    content = json.dumps(
        {
            "version": 1,
            "acknowledged_at": when.isoformat(),
            "notes": dict(sorted(snapshot.items())),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    if target.is_file():
        op = FileOp(
            "update",
            Path(CHECKPOINT_FILENAME),
            USER_STATE_ZONE,
            content=content,
            expected=sha256_file(target),
        )
    else:
        op = FileOp("create", Path(CHECKPOINT_FILENAME), USER_STATE_ZONE, content=content)
    changeset = ChangeSet(
        verb="acknowledge",
        ops=(op,),
        reason="Acknowledge the current vault as the since-last-check checkpoint",
    )
    return commit(changeset, write_zones(vault_root, runtime_root), now=when)


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
    if checkpoint is None:
        return SinceLastCheckResult(
            availability="unavailable",
            error_state="no_checkpoint",
            acknowledged_at=None,
            generated_at=generated_at,
            items=(),
            total_count=0,
        )
    scanned = {record.path: (record.title, record.content_hash) for record in scan_vault(vault_root)}
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
