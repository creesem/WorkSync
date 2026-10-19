"""The single mutation gateway: ordered, preconditioned, journalled file operations.

``commit`` validates every precondition before it writes, applies in order, journals
before applying, and either commits coherently or restores the prior state. An
incomplete journal (no committed marker) rolls back on the next run.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.safety import activity
from worksync.safety.files import (
    atomic_write_bytes,
    atomic_write_text,
    conflicts_for,
    is_conflict_copy,
    is_provisional_file,
    sha256_bytes,
    sha256_file,
)
from worksync.safety.models import (
    CANONICAL_ZONES,
    CONFIRM_VERBS,
    USER_STATE_ZONES,
    ChangeSet,
    CommitResult,
    FileOp,
    MutationError,
)

JOURNAL_DIRNAME = "journal"
BACKUP_DIRNAME = "backups"
OP_KINDS = frozenset({"create", "update", "move"})


def _zone_root(zones: Mapping[str, Path], zone: object) -> Path:
    root = zones.get(str(zone)) if isinstance(zone, str) else None
    if root is None:
        raise MutationError("unknown_zone", f"No writable root is configured for zone '{zone}'.")
    return Path(root)


def _contained(root: Path, target: object) -> Path:
    if target is None:
        raise MutationError("invalid_op", "Operation is missing a path.")
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return ensure_under(root, candidate)
    except PathSafetyError as exc:
        raise MutationError("containment_escape", str(exc), affected=(str(target),)) from exc


def _reject_conflicts(target: Path) -> None:
    if is_provisional_file(target):
        raise MutationError(
            "provisional_present", f"A provisional/temp file is present: {target}", affected=(str(target),)
        )
    if is_conflict_copy(target) or conflicts_for(target):
        raise MutationError("conflict_present", f"A sync-conflict copy is present: {target}", affected=(str(target),))


def _content_bytes(op: FileOp) -> bytes:
    if op.content is None:
        raise MutationError("invalid_op", f"{op.kind} requires content.", affected=(str(op.path),))
    return op.content.encode("utf-8")


def _backup_name(path: Path) -> str:
    return f"file-{sha1(str(path).encode('utf-8')).hexdigest()[:12]}{path.suffix}"


def _precondition(zones: Mapping[str, Path], op: FileOp) -> dict:
    if op.kind not in OP_KINDS:
        raise MutationError("invalid_op", f"Unknown operation kind: {op.kind}")
    root = _zone_root(zones, op.zone)
    if op.kind == "create":
        target = _contained(root, op.path)
        _reject_conflicts(target)
        if target.is_dir():
            raise MutationError(
                "ambiguous_path", f"A directory occupies the target path: {target}", affected=(str(target),)
            )
        if target.exists():
            raise MutationError("target_appeared", f"Target already exists: {target}", affected=(str(target),))
        content = _content_bytes(op)
        return {
            "kind": "create",
            "zone": op.zone,
            "path": target,
            "destination": None,
            "before": None,
            "after": sha256_bytes(content),
            "content": content.decode("utf-8"),
            "backup": None,
        }
    if op.kind == "update":
        target = _contained(root, op.path)
        _reject_conflicts(target)
        if target.is_dir():
            raise MutationError(
                "ambiguous_path", f"A directory occupies the target path: {target}", affected=(str(target),)
            )
        if not target.is_file():
            raise MutationError("missing_target", f"Target does not exist: {target}", affected=(str(target),))
        if not op.expected:
            raise MutationError(
                "missing_precondition", f"Update requires an expected sha256: {target}", affected=(str(target),)
            )
        before = sha256_file(target)
        if before != op.expected:
            raise MutationError("stale_hash", f"Target changed since it was read: {target}", affected=(str(target),))
        content = _content_bytes(op)
        return {
            "kind": "update",
            "zone": op.zone,
            "path": target,
            "destination": None,
            "before": before,
            "after": sha256_bytes(content),
            "content": content.decode("utf-8"),
            "backup": _backup_name(target),
        }
    source = _contained(root, op.path)
    destination = _contained(root, op.destination)
    _reject_conflicts(source)
    _reject_conflicts(destination)
    if not source.is_file():
        raise MutationError("missing_target", f"Move source does not exist: {source}", affected=(str(source),))
    if not op.expected:
        raise MutationError(
            "missing_precondition", f"Move requires an expected sha256: {source}", affected=(str(source),)
        )
    before = sha256_file(source)
    if before != op.expected:
        raise MutationError("stale_hash", f"Move source changed since it was read: {source}", affected=(str(source),))
    if destination.exists():
        raise MutationError(
            "target_appeared", f"Move destination already exists: {destination}", affected=(str(destination),)
        )
    return {
        "kind": "move",
        "zone": op.zone,
        "path": source,
        "destination": destination,
        "before": before,
        "after": before,
        "content": None,
        "backup": None,
    }


def _journal_ops(planned: list[dict]) -> list[dict]:
    return [
        {
            "kind": item["kind"],
            "zone": item["zone"],
            "path": str(item["path"]),
            "destination": str(item["destination"]) if item["destination"] is not None else None,
            "before": item["before"],
            "after": item["after"],
            "backup": item["backup"],
        }
        for item in planned
    ]


def _changes(planned: list[dict], *, reviewer: str | None, reason: str | None) -> tuple[dict, ...]:
    return tuple(
        {
            "kind": item["kind"],
            "zone": item["zone"],
            "path": str(item["path"]),
            "destination": str(item["destination"]) if item["destination"] is not None else None,
            "before": item["before"],
            "after": item["after"],
            "reviewer": reviewer,
            "reason": reason,
        }
        for item in planned
    )


def _write_journal(
    journal_path: Path, *, changeset: ChangeSet, class_: str, backup_dir: Path, planned: list[dict], when: datetime
) -> None:
    record = {
        "schema": 1,
        "verb": changeset.verb,
        "class": class_,
        "reviewer": changeset.reviewer,
        "reason": changeset.reason,
        "created_at": when.isoformat(timespec="seconds"),
        "backup_dir": backup_dir.name,
        "committed": False,
        "rolled_back": False,
        "ops": _journal_ops(planned),
    }
    _write_json(journal_path, record)


def _write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def _update_journal(journal_path: Path, **flags: object) -> None:
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(flags)
    _write_json(journal_path, record)


def _apply(planned: list[dict], backup_dir: Path) -> None:
    for item in planned:
        if item["kind"] == "create":
            atomic_write_text(item["path"], item["content"], expected_absent=True)
        elif item["kind"] == "update":
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / item["backup"]
            atomic_write_bytes(backup, item["path"].read_bytes(), expected_absent=True)
            if sha256_file(backup) != item["before"]:
                raise RuntimeError(f"Backup verification failed: {item['path']}")
            atomic_write_text(item["path"], item["content"], expected_sha256=item["before"])
        else:
            if item["destination"].exists():
                raise RuntimeError(f"Move destination appeared during processing: {item['destination']}")
            item["destination"].parent.mkdir(parents=True, exist_ok=True)
            os.replace(item["path"], item["destination"])


def _rollback(planned: list[dict], backup_dir: Path) -> None:
    failures: list[str] = []
    for item in reversed(planned):
        try:
            if item["kind"] == "create":
                if item["path"].is_file():
                    if sha256_file(item["path"]) != item["after"]:
                        raise RuntimeError("created file changed after the write")
                    item["path"].unlink()
            elif item["kind"] == "update":
                current = sha256_file(item["path"]) if item["path"].is_file() else None
                if current == item["before"]:
                    continue
                backup = backup_dir / str(item["backup"])
                if not backup.is_file() or sha256_file(backup) != item["before"]:
                    raise RuntimeError("backup is missing or corrupt")
                if current != item["after"]:
                    raise RuntimeError("target changed after the write")
                atomic_write_bytes(item["path"], backup.read_bytes(), expected_sha256=item["after"])
            else:
                destination = item["destination"]
                if not destination.is_file():
                    if item["path"].is_file() and sha256_file(item["path"]) == item["after"]:
                        continue
                    raise RuntimeError("move source changed without a destination")
                if sha256_file(destination) != item["after"]:
                    raise RuntimeError("move destination changed after the write")
                os.replace(destination, item["path"])
        except Exception as exc:
            failures.append(f"{item['path']}: {exc}")
    if failures:
        raise MutationError(
            "rollback_failed", "Rollback could not complete: " + "; ".join(failures), affected=tuple(failures)
        )


def _new_txid(runtime: Path, when: datetime) -> str:
    """Reserve a collision-proof transaction id by atomically creating its journal file.

    A timestamp alone collides when two processes commit within the same microsecond, so
    the id carries a random suffix and the journal path is created with ``O_EXCL``: the
    first writer wins the name and the loser retries, so concurrent commits can never share
    a journal or a backup directory. The reserved file starts as an empty ``{}`` journal so
    a crash before the real record is written still recovers as a no-op rather than as an
    unreadable journal.
    """
    journal_dir = runtime / JOURNAL_DIRNAME
    journal_dir.mkdir(parents=True, exist_ok=True)
    base = f"{when:%Y%m%d-%H%M%S-%f}-{secrets.token_hex(3)}"
    candidate = base
    counter = 1
    while True:
        try:
            handle = os.open(journal_dir / f"{candidate}.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            candidate = f"{base}-{counter:02d}"
            counter += 1
            continue
        os.write(handle, b"{}\n")
        os.close(handle)
        return candidate


def _planned_from_journal(record: dict) -> list[dict]:
    planned: list[dict] = []
    for op in record.get("ops", []):
        planned.append(
            {
                "kind": op["kind"],
                "zone": op["zone"],
                "path": Path(op["path"]),
                "destination": Path(op["destination"]) if op.get("destination") else None,
                "before": op.get("before"),
                "after": op.get("after"),
                "content": None,
                "backup": op.get("backup"),
            }
        )
    return planned


def _record(runtime: Path, event: dict) -> None:
    with contextlib.suppress(Exception):
        activity.append_event(runtime, event)


def commit(
    changeset: ChangeSet,
    zones: Mapping[str, Path],
    *,
    confirmed: bool = False,
    force: bool = False,
    now: datetime | None = None,
) -> CommitResult:
    """Apply a change set as one transaction, or restore the prior state and raise."""
    when = now or datetime.now(UTC)
    runtime = _zone_root(zones, "runtime")
    recover(zones, now=when)

    canonical = any(op.zone in CANONICAL_ZONES for op in changeset.ops)
    user_state = any(op.zone in USER_STATE_ZONES for op in changeset.ops)
    class_ = "canonical" if canonical else ("user_state" if user_state else "derived")
    event = {
        "type": "write",
        "verb": changeset.verb,
        "class": class_,
        "reviewer": changeset.reviewer,
        "reason": changeset.reason,
    }
    try:
        _validate(changeset, canonical=canonical, user_state=user_state, confirmed=confirmed, force=force)
        planned = [_precondition(zones, op) for op in changeset.ops]
    except MutationError as exc:
        outcome = "needs_confirmation" if exc.code == "needs_confirmation" else "error"
        _record(runtime, {**event, "result": outcome, "error": exc.code})
        raise

    journal_dir = runtime / JOURNAL_DIRNAME
    journal_dir.mkdir(parents=True, exist_ok=True)
    txid = _new_txid(runtime, when)
    journal_path = journal_dir / f"{txid}.json"
    backup_dir = runtime / BACKUP_DIRNAME / f"backup-{txid}"
    _write_journal(journal_path, changeset=changeset, class_=class_, backup_dir=backup_dir, planned=planned, when=when)

    try:
        _apply(planned, backup_dir)
    except Exception as exc:
        _rollback(planned, backup_dir)
        _update_journal(journal_path, rolled_back=True)
        paths = [str(item["path"]) for item in planned]
        _record(runtime, {**event, "result": "error", "error": "rolled_back", "paths": paths})
        raise MutationError(
            "rolled_back",
            f"Transaction failed and was rolled back: {exc}",
            affected=tuple(paths),
        ) from exc

    _update_journal(journal_path, committed=True)
    paths = [str(item["path"]) for item in planned]
    _record(runtime, {**event, "result": "ok", "paths": paths, "journal": str(journal_path)})
    return CommitResult(
        committed=True,
        journal=journal_path,
        changes=_changes(planned, reviewer=changeset.reviewer, reason=changeset.reason),
    )


def _validate(changeset: ChangeSet, *, canonical: bool, user_state: bool, confirmed: bool, force: bool) -> None:
    if not changeset.ops:
        raise MutationError("invalid_op", "A change set requires at least one operation.")
    if canonical:
        if not changeset.reviewer or not changeset.reviewer.strip():
            raise MutationError("missing_reviewer", "A canonical write requires a named reviewer.")
        if not changeset.reason or not changeset.reason.strip():
            raise MutationError("missing_reason", "A canonical write requires a human-readable reason.")
    if canonical and changeset.verb in CONFIRM_VERBS and not confirmed:
        raise MutationError("needs_confirmation", f"Verb '{changeset.verb}' requires explicit confirmation.")
    if not canonical and not user_state and not force and any(op.kind == "update" for op in changeset.ops):
        raise MutationError("needs_force", "Regenerating a derived artifact requires explicit force.")


def recover(zones: Mapping[str, Path], *, now: datetime | None = None) -> list[str]:
    """Roll back every incomplete transaction; returns the journals recovered."""
    runtime = _zone_root(zones, "runtime")
    journal_dir = runtime / JOURNAL_DIRNAME
    if not journal_dir.is_dir():
        return []
    recovered: list[str] = []
    for journal_path in sorted(journal_dir.glob("*.json")):
        try:
            record = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MutationError(
                "journal_unreadable",
                f"An incomplete transaction journal could not be read: {journal_path}",
                affected=(str(journal_path),),
            ) from exc
        if record.get("committed") or record.get("rolled_back"):
            continue
        backup_dir = runtime / BACKUP_DIRNAME / str(record.get("backup_dir") or "")
        _rollback(_planned_from_journal(record), backup_dir)
        _update_journal(journal_path, rolled_back=True)
        recovered.append(str(journal_path))
    return recovered
