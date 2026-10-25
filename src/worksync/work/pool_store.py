"""Gateway-backed writes for the runtime potential-task pool.

The pool is user state: one ``pool.json`` record. Initialization is explicit and one-shot;
ordinary reads never create it. Every write is journalled/backed up by the canonical gateway,
uses the current SHA, and records an audit event without evidence text. Promotion (the only
cross-zone write) lives in its own ticket/module and uses the same gateway.

Recovery and restore
--------------------
A successful update leaves the previous pool file under
``runtime/backups/backup-<txid>/file-<hash>.json`` and the transaction under
``runtime/journal``. Reads fail closed with ``pool_recovery_required`` while a journal is
unresolved. Run a pool write (or the reconcile path in ticket 04) to let the gateway recover
it; never delete a journal by hand. ``restore_pool`` restores a validated backup from under
``runtime/backups`` through the same gateway with an explicit reviewer, reason, confirmation,
and current-SHA precondition; it never accepts an arbitrary path and never modifies the
activation boundary. A missing pool file is not restored implicitly: ``pool init`` remains the
only boundary creator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit, recover
from worksync.safety.models import ChangeSet, CommitResult, FileOp, MutationError
from worksync.safety.zones import write_zones
from worksync.work.permissions import restrict_private_paths
from worksync.work.pool import (
    CANDIDATE_SCHEMA_VERSION,
    EXTRACTION_VERSION,
    POOL_FILENAME,
    POOL_RESTORE_VERB,
    POOL_SCHEMA_VERSION,
    POOL_START_VERB,
    POOL_WRITE_VERB,
    SCORING_VERSION,
    PoolAuditEvent,
    PoolError,
    PoolManifest,
    pool_path,
    pool_zone,
    read_manifest,
    validate_manifest,
)
from worksync.work.since_last_check import USER_STATE_ZONE


@dataclass(frozen=True)
class PoolWriteResult:
    """The visible outcome of a pool user-state write."""

    manifest: PoolManifest
    committed: bool
    journal: Path | None
    changes: tuple[dict, ...]
    limitations: tuple[str, ...] = ()


def init_pool(
    vault_root: str | Path,
    runtime_root: str | Path,
    *,
    start_at: str | datetime,
    timezone: str,
    reviewer: str,
    reason: str,
    confirmed: bool = False,
    now: datetime | None = None,
) -> PoolWriteResult:
    """Create the pool activation boundary exactly once.

    Reads/startup/schema validation never call this. The UTC timestamp, configured IANA
    timezone, and derived local date are persisted and never rewritten by later writes.
    """
    reviewer = _required(reviewer, "missing_reviewer", "A reviewer is required.")
    reason = _required(reason, "missing_reason", "A reason is required.")
    if not confirmed:
        raise PoolError("needs_confirmation", "Initializing the pool requires confirmation.", 409)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    start_utc, local_date = _resolve_start(start_at, timezone)
    manifest = PoolManifest(
        pool_start_at=start_utc,
        pool_start_timezone=timezone,
        pool_start_local_date=local_date,
        schema_version=POOL_SCHEMA_VERSION,
        candidate_schema_version=CANDIDATE_SCHEMA_VERSION,
        scoring_version=SCORING_VERSION,
        extraction_version=EXTRACTION_VERSION,
        revision=1,
        candidates=(),
        meetings=(),
        audit=(
            PoolAuditEvent(
                at=when.isoformat(),
                by=reviewer,
                verb=POOL_START_VERB,
                reason=reason,
            ),
        ),
    )
    validate_manifest(manifest)
    zones = write_zones(vault_root, runtime_root)
    _recover(zones, when)
    if pool_path(runtime_root).exists():
        raise PoolError("pool_already_initialized", "The potential-task pool is already initialized.", 409)
    limitations = restrict_private_paths(runtime_root)
    result = _commit(
        ChangeSet(
            POOL_START_VERB,
            (
                FileOp(
                    "create",
                    Path(POOL_FILENAME),
                    USER_STATE_ZONE,
                    content=_render(manifest),
                ),
            ),
            reviewer=reviewer,
            reason=reason,
        ),
        zones,
        when=when,
        confirmed=True,
    )
    limitations += restrict_private_paths(runtime_root)
    return PoolWriteResult(
        manifest=manifest,
        committed=result.committed,
        journal=result.journal,
        changes=result.changes,
        limitations=limitations,
    )


def write_pool(
    vault_root: str | Path,
    runtime_root: str | Path,
    manifest: PoolManifest,
    *,
    reviewer: str,
    reason: str,
    expected_revision: int | None = None,
    expected_sha: str | None = None,
    verb: str = POOL_WRITE_VERB,
    confirmed: bool = False,
    now: datetime | None = None,
) -> PoolWriteResult:
    """Write the full pool manifest through the gateway with revision/SHA preconditions."""
    reviewer = _required(reviewer, "missing_reviewer", "A reviewer is required.")
    reason = _required(reason, "missing_reason", "A reason is required.")
    when = (now or datetime.now(UTC)).astimezone(UTC)
    zones = write_zones(vault_root, runtime_root)
    _recover(zones, when)
    current = read_manifest(runtime_root)
    if expected_revision is not None and current.revision != expected_revision:
        raise PoolError(
            "pool_conflict",
            f"The pool revision changed (expected {expected_revision}, found {current.revision}).",
            409,
        )
    target = pool_path(runtime_root)
    if not target.is_file():
        raise PoolError("pool_not_initialized", "The potential-task pool is not initialized.", 409)
    current_sha = sha256_file(target)
    if expected_sha is not None and expected_sha != current_sha:
        raise PoolError("pool_conflict", "The pool record changed since it was read.", 409)
    if (
        manifest.pool_start_at,
        manifest.pool_start_timezone,
        manifest.pool_start_local_date,
    ) != (
        current.pool_start_at,
        current.pool_start_timezone,
        current.pool_start_local_date,
    ):
        raise PoolError(
            "pool_start_immutable",
            "pool_start_at/timezone/local date are immutable after initialization.",
            409,
        )
    validate_manifest(manifest)
    saved = replace(
        manifest,
        revision=current.revision + 1,
        audit=(
            *manifest.audit,
            PoolAuditEvent(at=when.isoformat(), by=reviewer, verb=verb, reason=reason),
        ),
    )
    validate_manifest(saved)
    limitations = restrict_private_paths(runtime_root)
    result = _commit(
        ChangeSet(
            verb,
            (
                FileOp(
                    "update",
                    Path(POOL_FILENAME),
                    USER_STATE_ZONE,
                    content=_render(saved),
                    expected=current_sha,
                ),
            ),
            reviewer=reviewer,
            reason=reason,
        ),
        zones,
        when=when,
        confirmed=confirmed,
    )
    limitations += restrict_private_paths(runtime_root)
    return PoolWriteResult(
        manifest=saved,
        committed=result.committed,
        journal=result.journal,
        changes=result.changes,
        limitations=limitations,
    )


def restore_pool(
    vault_root: str | Path,
    runtime_root: str | Path,
    backup_path: str | Path,
    *,
    reviewer: str,
    reason: str,
    confirmed: bool = False,
    now: datetime | None = None,
) -> PoolWriteResult:
    """Restore a validated gateway backup through the gateway, with explicit confirmation.

    Only files under ``runtime/backups`` are accepted. The restored manifest keeps its own
    activation boundary (the backup was taken from this pool), gains a restore audit event, and
    is written with the current corrupt/valid pool file's SHA as the precondition.
    """
    reviewer = _required(reviewer, "missing_reviewer", "A reviewer is required.")
    reason = _required(reason, "missing_reason", "A reason is required.")
    if not confirmed:
        raise PoolError("needs_confirmation", "Restoring the pool requires confirmation.", 409)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    backup = Path(backup_path).expanduser().resolve()
    backups_root = (Path(runtime_root).expanduser().resolve() / "backups").resolve()
    try:
        backup.relative_to(backups_root)
    except ValueError as exc:
        raise PoolError("invalid_backup", "A restore requires a backup under runtime/backups.", 400) from exc
    if not backup.is_file():
        raise PoolError("invalid_backup", f"Backup is not a regular file: {backup}", 400)
    try:
        payload = json.loads(backup.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise PoolError("invalid_backup", f"The backup could not be read: {exc}", 400) from exc
    restored = PoolManifest.from_dict(payload)
    try:
        current = read_manifest(runtime_root)
    except PoolError:
        current = None
    if current is not None and (
        current.pool_start_at,
        current.pool_start_timezone,
        current.pool_start_local_date,
    ) != (
        restored.pool_start_at,
        restored.pool_start_timezone,
        restored.pool_start_local_date,
    ):
        raise PoolError(
            "pool_start_immutable",
            "A restore cannot change the activation boundary.",
            409,
        )
    target = pool_path(runtime_root)
    if not target.is_file():
        raise PoolError(
            "pool_not_initialized",
            "A missing pool is created only by explicit pool init, not by restore.",
            409,
        )
    zones = write_zones(vault_root, runtime_root)
    _recover(zones, when)
    current_sha = sha256_file(target)
    restored = replace(
        restored,
        revision=restored.revision + 1,
        audit=(
            *restored.audit,
            PoolAuditEvent(at=when.isoformat(), by=reviewer, verb=POOL_RESTORE_VERB, reason=reason),
        ),
    )
    validate_manifest(restored)
    limitations = restrict_private_paths(runtime_root)
    result = _commit(
        ChangeSet(
            POOL_RESTORE_VERB,
            (
                FileOp(
                    "update",
                    Path(POOL_FILENAME),
                    USER_STATE_ZONE,
                    content=_render(restored),
                    expected=current_sha,
                ),
            ),
            reviewer=reviewer,
            reason=reason,
        ),
        zones,
        when=when,
        confirmed=True,
    )
    limitations += restrict_private_paths(runtime_root)
    return PoolWriteResult(
        manifest=restored,
        committed=result.committed,
        journal=result.journal,
        changes=result.changes,
        limitations=limitations,
    )


def _resolve_start(start_at: str | datetime, timezone: str) -> tuple[str, str]:
    if isinstance(start_at, str):
        try:
            parsed = datetime.fromisoformat(start_at)
        except ValueError as exc:
            raise PoolError("bad_start", "pool_start_at must be an ISO timestamp.", 400) from exc
    elif isinstance(start_at, datetime):
        parsed = start_at
    else:
        raise PoolError("bad_start", "pool_start_at must be a datetime or ISO timestamp.", 400)
    if parsed.tzinfo is None:
        raise PoolError("bad_start", "pool_start_at must include a timezone.", 400)
    zone_name = _required(timezone, "bad_timezone", "An IANA timezone is required.")
    zone = pool_zone(zone_name)
    start_utc = parsed.astimezone(UTC)
    return start_utc.isoformat(), start_utc.astimezone(zone).date().isoformat()


def _recover(zones: dict[str, Path], when: datetime) -> None:
    try:
        recover(zones, now=when)
    except MutationError as exc:
        raise PoolError("pool_recovery_required", str(exc), 409) from exc


def _commit(
    changeset: ChangeSet,
    zones: dict[str, Path],
    *,
    when: datetime,
    confirmed: bool,
) -> CommitResult:
    try:
        return commit(changeset, zones, confirmed=confirmed, now=when)
    except MutationError as exc:
        status = 409 if exc.code in {"stale_hash", "stale_source", "needs_confirmation"} else 500
        raise PoolError(exc.code, str(exc), status) from exc


def _render(manifest: PoolManifest) -> str:
    return json.dumps(manifest.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _required(value: str, code: str, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PoolError(code, message, 400)
    return text
