"""Apply a lifecycle transition as one canonical write through the mutation gateway.

A transition is a single ``safety.commit`` transaction: the canonical record update and
the derived registry append travel in the same ``ChangeSet``, so a metadata failure
restores the record and leaves the transition pending. The record update is SHA
preconditioned, backed up, and rolled back in reverse order by the gateway; the registry
lives only in the runtime zone. Quick completion and due-date changes remain canonical
task mutations (see :mod:`worksync.work.writer` and :mod:`worksync.work.lifecycle.date_gaps`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import edit_frontmatter_fields, parse_note
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.lifecycle import date_gaps, delivery, issue
from worksync.work.lifecycle.machine import TransitionError, resolve
from worksync.work.lifecycle.records import RegistryError, is_record_kind
from worksync.work.lifecycle.registry import LifecycleEntry, LifecycleRegistry, LifecycleStore, Transition, now
from worksync.work.lifecycle.waiting import WaitingError
from worksync.work.schema import detect_type

DEFAULT_STATE: dict[str, str] = {
    "issue": "reported",
    "delivery": "untracked",
    "date_gap": "needs-date",
    "waiting_on": "open",
}
WAITING_STATES = frozenset({"open", "resolved"})
WAITING_TRANSITIONS: dict[tuple[str, str], str] = {("open", "resolve"): "resolved"}
LAST_ACTION_LIMIT = 240
TRANSITION_VERB = "lifecycle_transition"
ALLOWED_ENTITY_TYPES = {"ticket", "action", "meeting"}


@dataclass(frozen=True)
class TransitionResult:
    """The visible outcome of a committed lifecycle transition."""

    committed: bool
    record_id: str
    kind: str
    action: str
    from_state: str
    to_state: str
    journal: Path | None
    changes: tuple[dict, ...]
    dry_run: bool = False
    planned: str | None = None


def apply_lifecycle_transition(
    vault: str | Path,
    runtime: str | Path,
    *,
    project_id: str,
    record_id: str,
    kind: str,
    action: str,
    actor: str,
    reason: str,
    today: date,
    target_sha: str | None = None,
    evidence: dict | None = None,
    fields: dict | None = None,
    dry_run: bool = False,
    confirmed: bool = False,
) -> TransitionResult:
    """Validate and commit one lifecycle transition (canonical record + registry) atomically."""
    if not is_record_kind(kind):
        raise RegistryError("unknown_record_kind", f"Unknown lifecycle record kind: {kind!r}")
    if not str(actor or "").strip():
        raise TransitionError("missing_actor", "A transition requires a named actor.")
    if not str(reason or "").strip():
        raise TransitionError("missing_reason", "A transition requires a human-readable reason.")
    evidence = dict(evidence or {})

    vault_root = Path(vault).expanduser().resolve()
    store = LifecycleStore(runtime, project_id)
    loaded = store.load_with_hash()
    registry = loaded[0] if loaded is not None else LifecycleRegistry(project_id=project_id)
    registry_hash = loaded[1] if loaded is not None else None

    entry = registry.entry(record_id)
    from_state = entry.lifecycle_state if entry is not None else DEFAULT_STATE[kind]
    to_state = _next_state(kind, from_state, action, actor=actor, reason=reason, evidence=evidence)

    target = _resolve_record(vault_root, record_id)
    record = parse_note(target, vault_root)
    entity_type = detect_type(record.frontmatter.get("type"))
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise RegistryError(
            "not_lifecycle_record", f"Target is not a lifecycle record: {record_id}", affected=(record_id,)
        )
    if target_sha is not None and target_sha != record.content_hash:
        raise RegistryError("stale_hash", f"Record changed since it was read: {record_id}", affected=(record_id,))

    content = edit_frontmatter_fields(
        record.content, set_fields=_canonical_edits(record.frontmatter, fields, today, actor, reason)
    )
    updated_entry = _append_transition(entry, kind, record_id, from_state, to_state, actor, reason, evidence)
    new_registry = registry.with_records(_replace_entry(registry.records, updated_entry))

    if dry_run:
        return TransitionResult(
            committed=False,
            record_id=record_id,
            kind=kind,
            action=action,
            from_state=from_state,
            to_state=to_state,
            journal=None,
            changes=(),
            dry_run=True,
            planned=content,
        )

    ops = [
        FileOp("update", Path(record_id), "trusted", content=content, expected=record.content_hash),
        store.registry_op(new_registry, expected=registry_hash),
    ]
    changeset = ChangeSet(TRANSITION_VERB, tuple(ops), reviewer=str(actor).strip(), reason=str(reason).strip())
    result: CommitResult = commit(changeset, write_zones(vault_root, runtime), confirmed=confirmed)
    return TransitionResult(
        committed=result.committed,
        record_id=record_id,
        kind=kind,
        action=action,
        from_state=from_state,
        to_state=to_state,
        journal=result.journal,
        changes=result.changes,
    )


def _next_state(kind: str, state: str, action: str, *, actor: str, reason: str, evidence: dict) -> str:
    if kind == "issue":
        return issue.apply_transition(state, action, actor=actor, reason=reason)
    if kind == "delivery":
        return delivery.apply_transition(
            state,
            action,
            actor=actor,
            reason=reason,
            tester=str(evidence.get("tester") or ""),
            business_acceptance=str(evidence.get("business_acceptance") or ""),
            accepter=str(evidence.get("accepter") or ""),
            rationale=str(evidence.get("rationale") or ""),
        )
    if kind == "date_gap":
        return date_gaps.apply_transition(
            state,
            action,
            actor=actor,
            reason=reason,
            previous=str(evidence.get("previous") or ""),
            revised=str(evidence.get("revised") or ""),
            source=str(evidence.get("source") or ""),
        )
    return resolve(
        WAITING_STATES, WAITING_TRANSITIONS, (), state, action, actor=actor, reason=reason, error=WaitingError
    ).to_state


def _resolve_record(vault_root: Path, record_id: str) -> Path:
    try:
        target = ensure_under(vault_root, vault_root / record_id)
    except PathSafetyError as exc:
        raise RegistryError("invalid_record", str(exc), affected=(record_id,)) from exc
    if not target.is_file():
        raise RegistryError("missing_record", f"Lifecycle record not found: {record_id}", affected=(record_id,))
    return target


def _canonical_edits(
    frontmatter: dict, fields: dict | None, today: date, actor: str, reason: str
) -> dict[str, str | None]:
    edits: dict[str, str | None] = dict(fields or {})
    edits["updated"] = today.isoformat()
    edits["updated_by"] = str(actor).strip()
    edits["last_action"] = str(reason).strip()[:LAST_ACTION_LIMIT]
    if frontmatter.get("revision") is not None:
        edits["revision"] = str(_revision(frontmatter) + 1)
    return edits


def _append_transition(
    entry: LifecycleEntry | None,
    kind: str,
    record_id: str,
    from_state: str,
    to_state: str,
    actor: str,
    reason: str,
    evidence: dict,
) -> LifecycleEntry:
    transition = Transition(
        at=now(),
        actor=str(actor).strip(),
        reason=str(reason).strip(),
        from_state=from_state,
        to_state=to_state,
        evidence=str(evidence.get("note") or evidence.get("source") or ""),
    )
    if entry is None:
        return LifecycleEntry(
            record_id=record_id, record_kind=kind, lifecycle_state=to_state, transitions=(transition,)
        )
    return replace(entry, lifecycle_state=to_state, transitions=(*entry.transitions, transition))


def _replace_entry(entries: tuple[LifecycleEntry, ...], updated: LifecycleEntry) -> tuple[LifecycleEntry, ...]:
    replaced = tuple(updated if entry.record_id == updated.record_id else entry for entry in entries)
    if not any(entry.record_id == updated.record_id for entry in entries):
        replaced = (*entries, updated)
    return replaced


def _revision(frontmatter: dict) -> int:
    try:
        return int(frontmatter.get("revision"))
    except (TypeError, ValueError):
        return 0


__all__ = ["TransitionResult", "apply_lifecycle_transition"]
