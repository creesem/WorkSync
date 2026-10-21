"""The override write path.

The read model lives in ``worksync.work.override``. The writes live here, in their own
module, so the GUI's read seam can import the read model without dragging the safety
layer into its import closure (mirroring the checkpoint and layout-profile splits).

Overrides are a ``user_state`` record (``runtime/user_state/overrides.json``), so these
writes are journaled and backed up but never touch a note. Ruling R3: ``save_override``
upserts by ``target_id``, keeping one active record per target, and ``clear_override``
soft-clears the record (``status="cleared"``) rather than deleting it. A save creates the
file on the first write and sha-preconditioned-updates it thereafter; its presence alone
decides which, so the existing contents are never parsed to choose the op. A clear with no
matching record writes nothing at all.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.override import (
    KNOWN_OVERRIDE_KINDS,
    OVERRIDES_FILENAME,
    SCHEMA_VERSION,
    OverrideRecord,
    overrides_path,
    read_override_records,
)
from worksync.work.since_last_check import USER_STATE_ZONE

SAVE_VERB = "save_override"
CLEAR_VERB = "clear_override"


def save_override(
    vault_root: str | Path,
    runtime_root: str | Path,
    target_id: str,
    kind: str,
    reason: str = "",
    *,
    now: datetime | None = None,
) -> CommitResult:
    """Upsert one active override for *target_id*, replacing that target's record.

    A target keeps exactly one record: an existing record — active or cleared — is
    replaced in place and keeps its original ``created_at``; a new target is appended.
    Both stamps come from the single injected *now*. Writes only the ``user_state``
    record — never a note.
    """
    _validate_target(target_id)
    if not isinstance(kind, str) or kind not in KNOWN_OVERRIDE_KINDS:
        raise ValueError(f"Unknown override kind: {kind!r}")
    if not isinstance(reason, str):
        raise ValueError("Override reason must be a string")
    when = now or datetime.now(UTC)
    stamp = when.isoformat()
    records = list(read_override_records(runtime_root))
    for index, record in enumerate(records):
        if record.target_id == target_id:
            records[index] = OverrideRecord(
                override_id=target_id,
                target_id=target_id,
                kind=kind,
                reason=reason,
                status="active",
                created_at=record.created_at or stamp,
                updated_at=stamp,
            )
            break
    else:
        records.append(
            OverrideRecord(
                override_id=target_id,
                target_id=target_id,
                kind=kind,
                reason=reason,
                status="active",
                created_at=stamp,
                updated_at=stamp,
            )
        )
    return _commit(
        vault_root,
        runtime_root,
        records,
        verb=SAVE_VERB,
        reason=f"Save {kind} override for {target_id}",
        when=when,
    )


def clear_override(
    vault_root: str | Path,
    runtime_root: str | Path,
    target_id: str,
    *,
    now: datetime | None = None,
) -> CommitResult:
    """Soft-clear the override for *target_id* (``status="cleared"``).

    The record stays in the file as provenance but ``read_overrides`` omits it. Clearing
    a target that has no record is a no-op that writes nothing at all — no empty file, no
    journal entry, no backup — so the GUI action never fails on a stale view and never
    records a mutation that changed nothing. Writes only the ``user_state`` record.
    """
    _validate_target(target_id)
    when = now or datetime.now(UTC)
    stamp = when.isoformat()
    stored = read_override_records(runtime_root)
    if not any(record.target_id == target_id for record in stored):
        return CommitResult(committed=False, journal=Path(), changes=())
    records = [
        replace(record, status="cleared", updated_at=stamp) if record.target_id == target_id else record
        for record in stored
    ]
    return _commit(
        vault_root,
        runtime_root,
        records,
        verb=CLEAR_VERB,
        reason=f"Clear the override for {target_id}",
        when=when,
    )


def _validate_target(target_id: str) -> None:
    """Reject a target that cannot name a record."""
    if not isinstance(target_id, str) or not target_id.strip():
        raise ValueError("Override target_id must be a non-empty string")


def _commit(
    vault_root: str | Path,
    runtime_root: str | Path,
    records: list[OverrideRecord],
    *,
    verb: str,
    reason: str,
    when: datetime,
) -> CommitResult:
    """Write the record list as the ``overrides.json`` user-state record."""
    target = overrides_path(runtime_root)
    content = json.dumps(
        {
            "version": SCHEMA_VERSION,
            "overrides": [record.to_dict() for record in records],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    if target.is_file():
        op = FileOp(
            "update",
            Path(OVERRIDES_FILENAME),
            USER_STATE_ZONE,
            content=content,
            expected=sha256_file(target),
        )
    else:
        op = FileOp("create", Path(OVERRIDES_FILENAME), USER_STATE_ZONE, content=content)
    changeset = ChangeSet(verb=verb, ops=(op,), reason=reason)
    return commit(changeset, write_zones(vault_root, runtime_root), now=when)
