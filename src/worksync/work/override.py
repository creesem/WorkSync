"""The read model over the user's persisted overrides.

An override is a user decision about one work record — pin it, focus it today, defer
it, mark it not relevant, or always prioritize it. The records live in the ``user_state``
zone (``runtime/user_state/overrides.json``); the writes — ``save_override`` and
``clear_override`` — live in ``worksync.work.override_store``, so this module stays free
of the safety layer and the read-only GUI seam can import it.

The stored shape is ruling R1: ``{"version": 1, "overrides": [{override_id, target_id,
kind, reason, status, created_at, updated_at}]}``, with ``override_id`` equal to
``target_id`` and at most one record per target. A malformed or unknown-schema file fails
closed on read (ruling R2), while a missing file is the normal "no overrides" state.

``read_overrides`` maps only ``active`` records onto the ranker's ``Override``, so a
soft-cleared record remains in the file as provenance but never reaches the ranking.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from worksync.work.prioritization import Override
from worksync.work.since_last_check import user_state_root

OVERRIDES_FILENAME = "overrides.json"
SCHEMA_VERSION = 1
KNOWN_OVERRIDE_KINDS = ("pin", "focus_today", "defer", "not_relevant", "always_prioritize")

_KNOWN_KIND_SET = frozenset(KNOWN_OVERRIDE_KINDS)
_KNOWN_STATUSES = frozenset({"active", "cleared"})
_RECORD_FIELDS = ("override_id", "target_id", "kind", "reason", "status", "created_at", "updated_at")
_REQUIRED_FIELDS = ("override_id", "target_id", "kind")
_OPTIONAL_DEFAULTS = {"reason": "", "status": "active", "created_at": "", "updated_at": ""}


@dataclass(frozen=True)
class OverrideRecord:
    """One persisted user decision about one record, with its lifecycle stamps."""

    override_id: str
    target_id: str
    kind: str
    reason: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        """Serialize to the stored shape (ruling R1)."""
        return {
            "override_id": self.override_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OverrideRecord:
        """Build a record from stored JSON, raising ``ValueError`` on a bad shape.

        The kind must be one this build knows and the status must be ``active`` or
        ``cleared``; every field must be a string. The optional fields default to their
        R1 empties when absent.
        """
        if not isinstance(data, dict):
            raise ValueError("Override record is not an object")
        for name in _REQUIRED_FIELDS:
            if name not in data:
                raise ValueError(f"Override record is missing {name}")
        values: dict[str, str] = {}
        for name in _RECORD_FIELDS:
            value = data.get(name, _OPTIONAL_DEFAULTS.get(name, ""))
            if not isinstance(value, str):
                raise ValueError(f"Override record has an invalid {name}")
            values[name] = value
        if values["kind"] not in _KNOWN_KIND_SET:
            raise ValueError(f"Override record has an unknown kind: {values['kind']!r}")
        if values["status"] not in _KNOWN_STATUSES:
            raise ValueError(f"Override record has an unknown status: {values['status']!r}")
        return cls(**values)


def overrides_path(runtime_root: str | Path) -> Path:
    """Return the overrides file's path in the ``user_state`` zone."""
    return user_state_root(runtime_root) / OVERRIDES_FILENAME


def read_override_records(runtime_root: str | Path) -> tuple[OverrideRecord, ...]:
    """Return every stored override record, or ``()`` when none has been written.

    Fails closed (ruling R2): a present path that is not a regular file (a directory or a
    dangling symlink), unreadable or malformed JSON, a shape ``from_dict`` rejects, or a
    schema version this build does not know all raise ``ValueError``. A missing file is the
    normal "no overrides" state, not an error. Cleared records are returned as well, so a
    caller that rewrites the file preserves them.
    """
    path = overrides_path(runtime_root)
    if not path.is_file():
        if path.exists() or path.is_symlink():
            raise ValueError(f"Overrides file is not a regular file: {path}")
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Overrides file could not be read: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Overrides file is not an object: {path}")
    if payload.get("version") != SCHEMA_VERSION:
        raise ValueError(f"Overrides file has an unsupported schema version: {path}")
    stored = payload.get("overrides")
    if not isinstance(stored, list):
        raise ValueError(f"Overrides file has an unexpected shape: {path}")
    try:
        return tuple(OverrideRecord.from_dict(item) for item in stored)
    except ValueError as exc:
        raise ValueError(f"Overrides file has an unexpected shape: {path}") from exc


def read_overrides(runtime_root: str | Path) -> tuple[Override, ...]:
    """Return the active overrides in the ranker's ``Override`` shape (ruling R2).

    A soft-cleared record is omitted; a malformed or unknown-schema file propagates the
    fail-closed ``ValueError`` from :func:`read_override_records`.
    """
    return tuple(
        Override(
            override_id=record.override_id,
            target_id=record.target_id,
            kind=record.kind,
            reason=record.reason,
        )
        for record in read_override_records(runtime_root)
        if record.status == "active"
    )
