"""Canonical action write service: allowlisted field edits and quick completion.

Every mutation is one ``trusted`` :func:`worksync.safety.gateway.commit` transaction. The
source SHA is the precondition, the gateway owns the backup, journal, and reverse-order
rollback, and the in-note history fields are written in the same operation. Reads go
through the single inventory scanner; this module never imports ``context``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from worksync.core.paths import resolve_stored_path
from worksync.inventory.parse import edit_frontmatter_fields, parse_note
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.models import EntityType
from worksync.work.schema import canonical_action_status, canonical_priority, detect_type

ALLOWED_FIELDS = (
    "status",
    "priority",
    "due",
    "project",
    "waiting_on",
    "next_action",
    "blocker",
    "delay_reason",
)
EDIT_VERB = "update_action"
COMPLETE_VERB = "complete_action"
LAST_ACTION_LIMIT = 240


class ActionWriteError(ValueError):
    """Raised when an action edit cannot be applied; nothing partial survives."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class ActionWriteResult:
    """The visible outcome of an action write."""

    path: str
    committed: bool
    sha: str | None
    journal: Path | None
    changes: tuple[dict, ...]
    planned: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


def update_action(
    vault: str | Path,
    runtime: str | Path,
    path: str,
    *,
    fields: dict[str, Any],
    reason: str,
    reviewer: str,
    expected: str | None = None,
    today: date | None = None,
    dry_run: bool = False,
) -> ActionWriteResult:
    """Apply an allowlisted action edit as one canonical transaction."""
    return _apply_action(
        vault,
        runtime,
        path,
        fields=fields,
        verb=EDIT_VERB,
        reason=reason,
        reviewer=reviewer,
        expected=expected,
        today=today,
        dry_run=dry_run,
    )


def complete_action(
    vault: str | Path,
    runtime: str | Path,
    path: str,
    *,
    reason: str,
    reviewer: str,
    expected: str | None = None,
    today: date | None = None,
    dry_run: bool = False,
) -> ActionWriteResult:
    """Mark an action done and record its completion date in one canonical transaction."""
    return _apply_action(
        vault,
        runtime,
        path,
        fields={"status": "done"},
        verb=COMPLETE_VERB,
        reason=reason,
        reviewer=reviewer,
        expected=expected,
        today=today,
        dry_run=dry_run,
    )


def _apply_action(
    vault: str | Path,
    runtime: str | Path,
    path: str,
    *,
    fields: dict[str, Any],
    verb: str,
    reason: str,
    reviewer: str,
    expected: str | None,
    today: date | None,
    dry_run: bool,
) -> ActionWriteResult:
    when = today or date.today()
    if not str(reviewer).strip():
        raise ActionWriteError("missing_reviewer", "A canonical write requires a named reviewer.")
    if not str(reason).strip():
        raise ActionWriteError("missing_reason", "A canonical write requires a human-readable reason.")
    _reject_unknown_fields(fields)

    vault_root, target, relative = _resolve_target(vault, path)
    record = parse_note(target, vault_root)
    if detect_type(record.frontmatter.get("type")) != EntityType.ACTION.value:
        raise ActionWriteError("not_action", f"Target is not an action note: {relative}", affected=(relative,))
    if expected is not None and expected != record.content_hash:
        raise ActionWriteError("stale_hash", f"Target changed since it was read: {relative}", affected=(relative,))

    edits = _build_edits(record.frontmatter, fields, today=when, reviewer=reviewer, reason=reason)
    content = edit_frontmatter_fields(record.content, set_fields=edits)
    result_fields = {key: value for key, value in edits.items() if key in fields and value is not None}

    if dry_run:
        return ActionWriteResult(
            path=relative,
            committed=False,
            sha=record.content_hash,
            journal=None,
            changes=(),
            planned=content,
            fields=result_fields,
        )

    op = FileOp("update", Path(relative), "trusted", content=content, expected=record.content_hash)
    changeset = ChangeSet(verb, (op,), reviewer=reviewer, reason=reason)
    committed: CommitResult = commit(changeset, write_zones(vault_root, runtime))
    return ActionWriteResult(
        path=relative,
        committed=committed.committed,
        sha=sha256_file(target),
        journal=committed.journal,
        changes=committed.changes,
        planned=content,
        fields=result_fields,
    )


def _resolve_target(vault: str | Path, path: str) -> tuple[Path, Path, str]:
    vault_root = Path(vault).expanduser().resolve()
    if not str(path).strip():
        raise ActionWriteError("invalid_target", "A target path is required.")
    try:
        target = resolve_stored_path(vault_root, path)
    except FileNotFoundError as exc:
        raise ActionWriteError("missing_target", str(exc), affected=(str(path),)) from exc
    if target.suffix.casefold() != ".md":
        raise ActionWriteError("invalid_target", f"Target is not a markdown note: {path}", affected=(str(path),))
    return vault_root, target, target.relative_to(vault_root).as_posix()


def _reject_unknown_fields(fields: dict[str, Any]) -> None:
    """Reject a non-editable field before any target is read or resolved."""
    unknown = [key for key in fields if key not in ALLOWED_FIELDS]
    if unknown:
        raise ActionWriteError("unmapped_field", f"Field is not editable: {', '.join(sorted(unknown))}")


def _build_edits(
    frontmatter: dict[str, Any],
    fields: dict[str, Any],
    *,
    today: date,
    reviewer: str,
    reason: str,
) -> dict[str, str | None]:
    edits: dict[str, str | None] = {}
    for key in ALLOWED_FIELDS:
        if key not in fields:
            continue
        edits[key] = _field_value(key, fields[key])

    requested_status = edits.get("status")
    previous_status = canonical_action_status(frontmatter.get("status"))
    resulting_status = requested_status or previous_status
    if resulting_status == "waiting":
        waiting_on = edits.get("waiting_on")
        if waiting_on is None:
            waiting_on = _text(frontmatter.get("waiting_on"))
        if not waiting_on:
            raise ActionWriteError("waiting_requires_waiting_on", "A waiting action requires a waiting_on value.")
    if requested_status == "done":
        if previous_status == "done":
            raise ActionWriteError("already_done", "The action is already done.")
        edits["completed"] = today.isoformat()

    revision = _revision(frontmatter)
    edits["updated"] = today.isoformat()
    edits["revision"] = str(revision + 1)
    edits["updated_by"] = reviewer
    edits["last_action"] = str(reason).strip()[:LAST_ACTION_LIMIT]
    return edits


def _field_value(key: str, value: Any) -> str | None:
    if key == "status":
        canonical = canonical_action_status(value)
        if canonical is None:
            raise ActionWriteError("unmappable_status", f"Unknown action status: {value!r}")
        return canonical
    if key == "priority":
        mappable, canonical = canonical_priority(value)
        if not mappable:
            raise ActionWriteError("unmappable_priority", f"Unknown action priority: {value!r}")
        return canonical
    if key == "due":
        text = _text(value)
        if text is None:
            return None
        if _parse_date(text) is None:
            raise ActionWriteError("invalid_due", f"Due date is not an ISO date: {value!r}")
        return text
    return _text(value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _revision(frontmatter: dict[str, Any]) -> int:
    value = frontmatter.get("revision")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "ALLOWED_FIELDS",
    "COMPLETE_VERB",
    "EDIT_VERB",
    "ActionWriteError",
    "ActionWriteResult",
    "complete_action",
    "update_action",
]
