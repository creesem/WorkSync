"""The GUI write seam: named actions dispatched to existing canonical services.

Each action is a thin adapter that validates its payload, calls an existing ``work``
service, and normalizes the outcome. The dispatcher holds no domain logic; a canonical
write builds one ``safety.commit`` transaction inside the service, so SHA preconditions,
backups, and reverse-order rollback are never bypassed. A transport maps an
:class:`ActionError` to an HTTP status and never leaks an internal exception.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from worksync.safety.models import MutationError
from worksync.work import reviewer as reviewer_store
from worksync.work.reviewer import ReviewerError
from worksync.work.writer import ActionWriteError, ActionWriteResult, complete_action, update_action

ActionHandler = Callable[..., dict]
CONFIRM_STATUS = 409


class WriteContext(Protocol):
    """The pinned write context an action adapter reads: vault, runtime, reviewer."""

    vault: Path
    runtime_root: Path
    reviewer: str | None


_STATUS_BY_CODE = {
    "bad_request": 400,
    "missing_reason": 400,
    "missing_reviewer": 400,
    "invalid_target": 400,
    "missing_target": 404,
    "stale_hash": 409,
    "needs_confirmation": 409,
    "target_appeared": 409,
    "conflict_present": 409,
    "provisional_present": 409,
    "unmapped_field": 422,
    "unmappable_status": 422,
    "unmappable_priority": 422,
    "invalid_due": 422,
    "invalid_op": 422,
    "not_action": 422,
    "waiting_requires_waiting_on": 422,
    "already_done": 422,
    "rolled_back": 500,
    "rollback_failed": 500,
}


class ActionError(ValueError):
    """A GUI action failure carrying its mapped HTTP status and affected paths."""

    def __init__(self, code: str, message: str, status: int, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.affected = tuple(affected)


def dispatch_action(
    service: WriteContext,
    name: str,
    payload: dict | None,
    *,
    today: date | None = None,
) -> dict:
    """Dispatch one named action, mapping any service failure to an :class:`ActionError`."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ActionError("bad_request", "The action body must be a JSON object.", 400)
    handler = ACTIONS.get(name)
    if handler is None:
        raise ActionError("unknown_action", f"Unknown action: {name}", 404)
    try:
        return handler(service, payload, confirmed=bool(payload.get("confirmed")), today=today)
    except (ActionWriteError, ReviewerError, MutationError) as exc:
        raise _as_action_error(exc) from exc


def _as_action_error(exc: Exception) -> ActionError:
    code = str(getattr(exc, "code", "error"))
    affected = tuple(getattr(exc, "affected", ()))
    return ActionError(code, str(exc), _STATUS_BY_CODE.get(code, 500), affected=affected)


def _update_action(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    path = _required(payload, "path", "invalid_target")
    reason = _required(payload, "reason", "missing_reason")
    fields = payload.get("fields") or {}
    if not isinstance(fields, dict):
        raise ActionError("bad_request", "fields must be a JSON object.", 400)
    if not fields:
        raise ActionWriteError("invalid_op", "Provide at least one field to update.")
    reviewer = _reviewer(service)
    dry_run = bool(payload.get("dry_run"))
    result = update_action(
        service.vault,
        service.runtime_root,
        path,
        fields=fields,
        reason=reason,
        reviewer=reviewer,
        expected=_expected(payload),
        today=today,
        dry_run=dry_run,
    )
    return _write_result(
        "update-action",
        result,
        reviewer=reviewer,
        reason=reason,
        dry_run=dry_run,
        equivalent_cli=_update_cli(result.path or path, fields, reason, reviewer),
    )


def _complete_action(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    path = _required(payload, "path", "invalid_target")
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    dry_run = bool(payload.get("dry_run"))
    result = complete_action(
        service.vault,
        service.runtime_root,
        path,
        reason=reason,
        reviewer=reviewer,
        expected=_expected(payload),
        today=today,
        dry_run=dry_run,
    )
    return _write_result(
        "complete-action",
        result,
        reviewer=reviewer,
        reason=reason,
        dry_run=dry_run,
        equivalent_cli=_complete_cli(result.path or path, reason, reviewer),
    )


def _set_reviewer(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    name = _required(payload, "reviewer", "missing_reviewer")
    stored = reviewer_store.store_reviewer(service.runtime_root, name)
    return {
        "state": "ok",
        "action": "set-reviewer",
        "committed": False,
        "reviewer": stored,
        "changes": (),
        "equivalent_cli": None,
    }


ACTIONS: dict[str, ActionHandler] = {
    "update-action": _update_action,
    "complete-action": _complete_action,
    "set-reviewer": _set_reviewer,
}


def _reviewer(service: WriteContext) -> str:
    return reviewer_store.resolve_reviewer(service.runtime_root, configured=service.reviewer)


def _write_result(
    action: str,
    result: ActionWriteResult,
    *,
    reviewer: str,
    reason: str,
    dry_run: bool,
    equivalent_cli: str,
) -> dict:
    payload: dict[str, Any] = {
        "state": "ok",
        "action": action,
        "committed": result.committed,
        "dry_run": dry_run,
        "path": result.path,
        "reviewer": reviewer,
        "reason": reason,
        "sha": result.sha,
        "fields": result.fields,
        "changes": [dict(change) for change in result.changes],
        "equivalent_cli": equivalent_cli,
    }
    if dry_run:
        payload["planned"] = result.planned
    return payload


def _required(payload: dict, key: str, code: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ActionError(code, f"Missing required field: {key}", 400)
    return value


def _expected(payload: dict) -> str | None:
    value = payload.get("expected") or payload.get("sha")
    text = str(value).strip() if value is not None else ""
    return text or None


def _update_cli(path: str, fields: dict, reason: str, reviewer: str) -> str:
    parts = ["worksync", "task", "update", _quote(path)]
    for key, value in fields.items():
        parts += [f"--{key.replace('_', '-')}", _quote(str(value))]
    parts += ["--reason", _quote(reason), "--reviewer", _quote(reviewer)]
    return " ".join(parts)


def _complete_cli(path: str, reason: str, reviewer: str) -> str:
    return " ".join(
        ["worksync", "task", "complete", _quote(path), "--reason", _quote(reason), "--reviewer", _quote(reviewer)]
    )


def _quote(value: str) -> str:
    return f'"{value}"'
