"""The since-last-check checkpoint store.

A checkpoint is the acknowledged baseline for "Since Last Check": the content hash of
every vault note at the moment the user acknowledged. It lives in the ``user_state``
zone (``runtime/user_state/checkpoint.json``), so the one write here is journaled and
backed up but never touches a note — acknowledging can never complete an action.

The stored shape is ruling R2: ``{"version": 1, "acknowledged_at": "<iso>", "notes":
{path: sha256}}``. A malformed file fails closed on read (ruling R3), while acknowledging
never parses the old file — it creates or sha-preconditioned-updates by presence alone,
so a corrupt checkpoint is repaired rather than blocking (ruling R4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
