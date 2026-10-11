"""One-shot, fail-closed migration of legacy lifecycle state into the runtime home.

Reads the retired ``9. Project/<project>/issue-registry.json`` and
``delivery-registry.json`` sidecars, maps every legacy loose state to an explicit state
(ADR-0019/Q1/Q2/Q4/Q5), and writes the derived registry under ``var/project/<id>/`` as
one gateway transaction. Any unmappable state or unresolved record aborts the run with
no writes. The migration is idempotent: a second run is a no-op. Communications and
update-review records are deferred (out of 0.1) and are not migrated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult
from worksync.safety.zones import write_zones
from worksync.work.lifecycle.registry import LifecycleEntry, LifecycleRegistry, LifecycleStore, Transition

ISSUE_REGISTRY_FILENAME = "issue-registry.json"
DELIVERY_REGISTRY_FILENAME = "delivery-registry.json"

ISSUE_STATE_MAP: dict[str, str] = {
    state: state
    for state in ("reported", "confirmed", "fixing", "fixed", "retesting", "verified", "rejected", "deferred")
}
REPORT_STATE_MAP: dict[str, str] = {
    state: state
    for state in (
        "untracked",
        "build_complete",
        "ready_for_testing",
        "testing",
        "defect_found",
        "fix_reported",
        "retest_pending",
        "accepted",
        "accepted_exception",
    )
}
DATE_STATE_MAP: dict[str, str] = {
    "needs_date": "needs-date",
    "requested": "needs-date",
    "date_provided": "conditional",
    "confirmed": "confirmed",
}
WAITING_LANE_MAP: dict[str, str] = {
    lane: lane.replace("_", "-")
    for lane in ("teammate", "vendor", "tester", "business_acceptance", "user_decision", "external_dependency")
}


class LegacyMigrationError(ValueError):
    """Raised when legacy lifecycle state cannot be mapped or resolved."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class MigrationResult:
    """The visible outcome of a legacy-state migration."""

    committed: bool
    changed: bool
    entries: tuple[LifecycleEntry, ...]
    journal: Path | None = None
    dry_run: bool = False


def _map(table: dict[str, str], value: object, label: str) -> str:
    key = str(value or "").strip().casefold()
    if key in table:
        return table[key]
    raise LegacyMigrationError(
        "unmappable_state", f"Unmappable legacy {label} state: {value!r}", affected=(str(value),)
    )


def map_issue_state(value: object) -> str:
    return _map(ISSUE_STATE_MAP, value, "issue")


def map_report_state(value: object) -> str:
    return _map(REPORT_STATE_MAP, value, "report")


def map_date_state(value: object) -> str:
    return _map(DATE_STATE_MAP, value, "date-gap")


def map_waiting_lane(value: object) -> str:
    return _map(WAITING_LANE_MAP, value, "waiting-on lane")


def migrate_legacy(
    vault: str | Path,
    runtime: str | Path,
    project_id: str,
    *,
    legacy_dir: str | Path,
    reviewer: str,
    reason: str,
    today: date,
    dry_run: bool = False,
) -> MigrationResult:
    """Migrate the legacy sidecars for one project into the runtime registry home."""
    vault_root = Path(vault).expanduser().resolve()
    legacy = Path(legacy_dir).expanduser().resolve()

    entries: list[LifecycleEntry] = []
    entries.extend(_issue_entries(vault_root, legacy))
    entries.extend(_delivery_entries(vault_root, legacy))
    record_ids = [entry.record_id for entry in entries]
    if len(record_ids) != len(set(record_ids)):
        raise LegacyMigrationError("duplicate_record", "A record is tracked by more than one legacy concern.")

    store = LifecycleStore(runtime, project_id)
    loaded = store.load_with_hash()
    existing = loaded[0] if loaded is not None else None
    if existing is not None and _is_noop(existing, entries):
        return MigrationResult(committed=False, changed=False, entries=tuple(entries))

    new_registry = LifecycleRegistry(project_id=project_id).with_records(tuple(entries))
    if dry_run:
        return MigrationResult(committed=False, changed=True, entries=tuple(entries), dry_run=True)

    op = store.registry_op(new_registry, expected=loaded[1] if loaded is not None else None)
    changeset = ChangeSet("migrate_legacy_lifecycle", (op,), reviewer=str(reviewer).strip(), reason=str(reason).strip())
    result: CommitResult = commit(changeset, write_zones(vault_root, runtime), force=True)
    return MigrationResult(committed=result.committed, changed=True, entries=tuple(entries), journal=result.journal)


def _issue_entries(vault_root: Path, legacy: Path) -> list[LifecycleEntry]:
    registry = _load_json(legacy / ISSUE_REGISTRY_FILENAME)
    if registry is None:
        return []
    issues = registry.get("issues") or {}
    if not isinstance(issues, dict):
        raise LegacyMigrationError("malformed_registry", "Legacy issue registry has an invalid structure.")
    entries: list[LifecycleEntry] = []
    for issue_id, record in issues.items():
        if not isinstance(record, dict):
            raise LegacyMigrationError("malformed_registry", f"Legacy issue record is invalid: {issue_id}")
        legacy_state = record.get("lifecycle_state", "reported")
        state = map_issue_state(legacy_state)
        entries.append(_entry(vault_root, issue_id, "issue", state, legacy_state, record.get("transitions")))
    return entries


def _delivery_entries(vault_root: Path, legacy: Path) -> list[LifecycleEntry]:
    registry = _load_json(legacy / DELIVERY_REGISTRY_FILENAME)
    if registry is None:
        return []
    entries: list[LifecycleEntry] = []
    for report_id, record in _bucket(registry, "reports"):
        state = map_report_state(record.get("lifecycle_state", "untracked"))
        entries.append(
            _entry(vault_root, report_id, "delivery", state, record.get("lifecycle_state"), record.get("transitions"))
        )
    for gap_id, record in _bucket(registry, "date_gaps"):
        state = map_date_state(record.get("lifecycle_state", "needs_date"))
        entries.append(
            _entry(vault_root, gap_id, "date_gap", state, record.get("lifecycle_state"), record.get("transitions"))
        )
    for item_id, record in _bucket(registry, "waiting"):
        lane = map_waiting_lane(record.get("lane", ""))
        state = str(record.get("status") or record.get("lifecycle_state") or "open").strip().casefold()
        entries.append(_entry(vault_root, item_id, "waiting_on", state, lane, record.get("transitions")))
    return entries


def _bucket(registry: dict, key: str) -> list[tuple[str, dict]]:
    bucket = registry.get(key) or {}
    if not isinstance(bucket, dict):
        raise LegacyMigrationError("malformed_registry", f"Legacy delivery registry bucket is invalid: {key}")
    for record_id, record in bucket.items():
        if not isinstance(record, dict):
            raise LegacyMigrationError("malformed_registry", f"Legacy delivery record is invalid: {record_id}")
    return list(bucket.items())


def _entry(
    vault_root: Path, record_id: object, kind: str, state: str, legacy_state: object, transitions: object
) -> LifecycleEntry:
    resolved = _resolve_record(vault_root, record_id)
    return LifecycleEntry(
        record_id=resolved,
        record_kind=kind,
        lifecycle_state=state,
        provenance=(f"legacy {kind} state {legacy_state!r} -> {state!r}",),
        transitions=_transitions(transitions),
    )


def _transitions(raw: object) -> tuple[Transition, ...]:
    if not isinstance(raw, list):
        return ()
    converted: list[Transition] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        converted.append(
            Transition(
                at=str(item.get("at") or ""),
                actor=str(item.get("by") or ""),
                reason=str(item.get("evidence") or "migrated legacy transition"),
                from_state=str(item.get("from") or ""),
                to_state=str(item.get("to") or ""),
                evidence=str(item.get("evidence") or ""),
            )
        )
    return tuple(converted)


def _resolve_record(vault_root: Path, record_id: object) -> str:
    text = str(record_id or "").strip()
    if not text:
        raise LegacyMigrationError("unmappable_record", "A legacy record is missing its id.")
    try:
        target = ensure_under(vault_root, vault_root / text)
    except PathSafetyError as exc:
        raise LegacyMigrationError("unmappable_record", str(exc), affected=(text,)) from exc
    if not target.is_file():
        raise LegacyMigrationError("unmappable_record", f"Legacy record does not resolve: {text}", affected=(text,))
    return target.relative_to(vault_root).as_posix()


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise LegacyMigrationError("malformed_registry", f"Legacy registry could not be read: {path}") from exc
    if not isinstance(data, dict):
        raise LegacyMigrationError("malformed_registry", f"Legacy registry is not a JSON object: {path}")
    return data


def _is_noop(existing: LifecycleRegistry, entries: list[LifecycleEntry]) -> bool:
    by_id = {entry.record_id: entry for entry in existing.records}
    for entry in entries:
        current = by_id.get(entry.record_id)
        if (
            current is None
            or current.record_kind != entry.record_kind
            or current.lifecycle_state != entry.lifecycle_state
        ):
            return False
    return True


__all__ = [
    "LegacyMigrationError",
    "MigrationResult",
    "map_date_state",
    "map_issue_state",
    "map_report_state",
    "map_waiting_lane",
    "migrate_legacy",
]
