"""The GUI write seam: named actions dispatched to existing canonical services.

Each action is a thin adapter that validates its payload, calls an existing ``work``
service, and normalizes the outcome. The dispatcher holds no domain logic; a canonical
write builds one ``safety.commit`` transaction inside the service, so SHA preconditions,
backups, and reverse-order rollback are never bypassed. A transport maps an
:class:`ActionError` to an HTTP status and never leaks an internal exception.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from worksync.ingest import IngestError
from worksync.ingest import apply as ingest_apply
from worksync.ingest import dismiss as ingest_dismiss
from worksync.ingest import scan as ingest_scan
from worksync.ingest.krisp import KrispAPIError, build_client, sync_status
from worksync.ingest.krisp import pull as run_krisp_pull
from worksync.safety.files import sha256_bytes
from worksync.safety.models import MutationError
from worksync.work import clarification as clarification_service
from worksync.work import duplicates as duplicates_service
from worksync.work import identity as identity_service
from worksync.work import reviewer as reviewer_store
from worksync.work.capture import capture_text
from worksync.work.clarification import ClarificationError
from worksync.work.duplicates import DuplicatesError
from worksync.work.layout_profile import KNOWN_SECTIONS, default_profile, read_profile
from worksync.work.layout_profile_store import reset_profile, save_profile
from worksync.work.lifecycle.transitions import apply_lifecycle_transition
from worksync.work.merge import apply_merge as run_identity_apply
from worksync.work.queue import QueueError
from worksync.work.reviewer import ReviewerError
from worksync.work.writer import (
    ActionWriteError,
    ActionWriteResult,
    commit_action_plans,
    complete_action,
    plan_complete_action,
    plan_update_action,
    update_action,
)

ActionHandler = Callable[..., dict]
CONFIRM_STATUS = 409


class WriteContext(Protocol):
    """The pinned write context an action adapter reads: vault, runtime, reviewer, model."""

    vault: Path
    runtime_root: Path
    reviewer: str | None
    model: object | None
    inbox_path: str | None
    rough_notes_path: str | None
    krisp_inbox_path: Path | None
    krisp_since_days: int
    krisp_api_key: str | None


_STATUS_BY_CODE = {
    "bad_request": 400,
    "missing_reason": 400,
    "missing_reviewer": 400,
    "invalid_target": 400,
    "invalid_source": 400,
    "invalid_root": 400,
    "invalid_override": 400,
    "missing_root": 400,
    "missing_target": 404,
    "missing_source": 404,
    "unknown_proposal": 404,
    "stale_hash": 409,
    "stale_source": 409,
    "needs_confirmation": 409,
    "no_manifest": 409,
    "target_appeared": 409,
    "conflict_present": 409,
    "provisional_present": 409,
    "no_proposals": 400,
    "merge_noop": 422,
    "unsupported_action": 422,
    "unmapped_field": 422,
    "unmappable_status": 422,
    "unmappable_priority": 422,
    "invalid_meeting_status": 422,
    "invalid_meeting_date": 422,
    "invalid_due": 422,
    "invalid_op": 422,
    "not_action": 422,
    "unsupported_resolution": 422,
    "missing_reclassify_fields": 422,
    "unknown_project": 422,
    "unknown_owner": 422,
    "invalid_next_review": 422,
    "owner_conflict": 409,
    "waiting_requires_waiting_on": 422,
    "already_done": 422,
    "rolled_back": 500,
    "rollback_failed": 500,
    "missing_key": 400,
    "unauthorized": 409,
    "rate_limited": 429,
    "network": 502,
    "http_error": 502,
    "bad_response": 502,
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
    except (
        ActionWriteError,
        ReviewerError,
        MutationError,
        IngestError,
        DuplicatesError,
        ClarificationError,
        KrispAPIError,
        QueueError,
    ) as exc:
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
        confirmed=confirmed,
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
        confirmed=confirmed,
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


def _save_layout_profile(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    """Persist the Command Center layout: section order, visibility, and the "Me" owner.

    Only the ``user_state`` profile record is written — never a note. ``reset`` restores
    the defaults instead. The profile is read back after the commit so the client caches
    the stored revision and timestamp rather than the pre-save values.
    """
    reset = payload.get("reset", False)
    if type(reset) is not bool:
        raise ActionError("bad_request", "reset must be a boolean.", 400)
    if reset:
        result = reset_profile(service.vault, service.runtime_root)
    else:
        section_order = _layout_section_order(payload.get("section_order"))
        visibility = _layout_visibility(payload.get("visibility"))
        try:
            current = read_profile(service.runtime_root)
        except ValueError:
            # Mirror the route's graceful degradation: a corrupt profile is replaced by the
            # defaults plus this payload rather than blocking the save (store ruling R5).
            current = default_profile()
        owner_id = _layout_owner_id(payload.get("owner_id", current.owner_id))
        profile = replace(current, section_order=section_order, visibility=visibility, owner_id=owner_id)
        result = save_profile(service.vault, service.runtime_root, profile)
    try:
        stored = read_profile(service.runtime_root)
    except ValueError as exc:
        raise ActionError(
            "write_failed", f"The layout profile was written but could not be read back: {exc}", 500
        ) from exc
    return {
        "state": "ok",
        "action": "save-layout-profile",
        "committed": result.committed,
        "profile": stored.to_dict(),
        "equivalent_cli": None,
    }


def _layout_section_order(value: object) -> tuple[str, ...]:
    """Return the section order, rejecting anything but the known ids exactly once."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ActionError("bad_request", "section_order must be a list of section ids.", 400)
    if len(value) != len(KNOWN_SECTIONS) or set(value) != set(KNOWN_SECTIONS):
        raise ActionError(
            "bad_request",
            "section_order must list each Command Center section exactly once.",
            400,
        )
    return tuple(value)


def _layout_visibility(value: object) -> dict[str, bool]:
    """Return the visibility map, rejecting anything but a boolean per known section."""
    if not isinstance(value, dict) or set(value) != set(KNOWN_SECTIONS):
        raise ActionError(
            "bad_request",
            "visibility must set every Command Center section to true or false.",
            400,
        )
    if any(type(flag) is not bool for flag in value.values()):
        raise ActionError("bad_request", "visibility values must be booleans.", 400)
    return {section: value[section] for section in KNOWN_SECTIONS}


def _layout_owner_id(value: object) -> str | None:
    """Return the "Me" person id, treating a blank string as no owner."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ActionError("bad_request", "owner_id must be a person id string or null.", 400)
    return value.strip() or None


def _apply_batch(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ActionError("bad_request", "A batch requires a non-empty items list.", 400)
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)

    plans = []
    equivalents: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise ActionError("bad_request", "Each batch item must be a JSON object.", 400)
        action = str(item.get("action") or "").strip()
        item_reason = str(item.get("reason") or reason).strip()
        path = _required(item, "path", "invalid_target")
        if action == "update-action":
            fields = item.get("fields") or {}
            if not isinstance(fields, dict) or not fields:
                raise ActionWriteError("invalid_op", "Provide at least one field to update.")
            plan = plan_update_action(
                service.vault,
                path,
                fields=fields,
                reason=item_reason,
                reviewer=reviewer,
                expected=_expected(item),
                today=today,
            )
            equivalent = _update_cli(plan.path, fields, item_reason, reviewer)
        elif action == "complete-action":
            plan = plan_complete_action(
                service.vault,
                path,
                reason=item_reason,
                reviewer=reviewer,
                expected=_expected(item),
                today=today,
            )
            equivalent = _complete_cli(plan.path, item_reason, reviewer)
        else:
            raise ActionError("unknown_action", f"Unknown batch action: {action}", 404)
        plans.append(plan)
        equivalents.append({"path": plan.path, "equivalent_cli": equivalent})

    committed = commit_action_plans(
        service.vault,
        service.runtime_root,
        tuple(plans),
        verb="apply_batch",
        reviewer=reviewer,
        reason=reason,
        confirmed=confirmed,
    )
    return {
        "state": "ok",
        "action": "apply-batch",
        "committed": committed.committed,
        "reviewer": reviewer,
        "reason": reason,
        "changes": [dict(change) for change in committed.changes],
        "items": equivalents,
        "equivalent_cli": None,
    }


def _capture(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ActionError("bad_request", "Captured text must not be empty.", 400)
    manifest = capture_text(service.runtime_root, text)
    digest = sha256_bytes(text.encode("utf-8"))
    proposal = next(proposal for proposal in manifest.proposals if proposal.source_sha256 == digest)
    return {
        "state": "ok",
        "action": "capture",
        "committed": False,
        "proposal": proposal.to_dict(),
        "equivalent_cli": None,
    }


def _ingest_scan(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    manifest = ingest_scan(
        service.vault,
        service.runtime_root,
        inbox_path=service.inbox_path,
        rough_notes_path=service.rough_notes_path,
        krisp_inbox_path=service.krisp_inbox_path,
        today=today,
        model=service.model,
    )
    return {
        "state": "ok",
        "action": "ingest-scan",
        "committed": False,
        "scan_token": manifest.scan_token,
        "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        "equivalent_cli": _scan_cli(service.inbox_path, service.rough_notes_path, today),
    }


def _ingest_apply(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    ids = payload.get("ids")
    if ids is not None and (not isinstance(ids, list) or not ids):
        raise ActionError("bad_request", "ids must be a non-empty list.", 400)
    overrides = payload.get("overrides")
    if overrides is not None and not isinstance(overrides, dict):
        raise ActionError("bad_request", "overrides must be a JSON object.", 400)
    result = ingest_apply(
        service.vault,
        service.runtime_root,
        reviewer=reviewer,
        reason=reason,
        ids=tuple(str(item) for item in ids) if ids else None,
        confirmed=confirmed,
        today=today,
        krisp_inbox_path=service.krisp_inbox_path,
        overrides=overrides,
    )
    return {
        "state": "ok",
        "action": "ingest-apply",
        "committed": result.committed,
        "reviewer": reviewer,
        "reason": reason,
        "applied": list(result.applied),
        "changes": [dict(change) for change in result.changes],
        "equivalent_cli": _apply_cli("ingest", reason, reviewer, ids, confirmed, overrides),
    }


def _ingest_dismiss(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    proposal_id = _required(payload, "id", "invalid_target")
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    manifest = ingest_dismiss(service.runtime_root, proposal_id, reviewer=reviewer, reason=reason)
    return {
        "state": "ok",
        "action": "ingest-dismiss",
        "committed": False,
        "reviewer": reviewer,
        "reason": reason,
        "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        "equivalent_cli": _dismiss_cli("ingest", proposal_id, reason, reviewer),
    }


def _krisp_pull(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    api_key = service.krisp_api_key
    if not str(api_key or "").strip():
        raise ActionError("missing_key", "No Krisp API key is configured.", 400)
    since = service.krisp_since_days
    client = build_client(api_key)
    result = run_krisp_pull(
        service.runtime_root, client=client, since_days=since, inbox=service.krisp_inbox_path, today=today
    )
    return {
        "state": "ok",
        "action": "krisp-pull",
        "committed": False,
        "summary": result.to_dict(),
        "equivalent_cli": _krisp_pull_cli(since),
    }


def _krisp_status(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    return {
        "state": "ok",
        "action": "krisp-status",
        "committed": False,
        "sync": sync_status(service.runtime_root),
        "since_days": service.krisp_since_days,
        "equivalent_cli": None,
    }


def _duplicates_scan(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    manifest = duplicates_service.scan(service.vault, service.runtime_root, today=today)
    return {
        "state": "ok",
        "action": "duplicates-scan",
        "committed": False,
        "scan_token": manifest.scan_token,
        "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        "equivalent_cli": _today_scan_cli("duplicates", today),
    }


def _duplicates_dismiss(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    proposal_id = _required(payload, "id", "invalid_target")
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    manifest = duplicates_service.dismiss(service.runtime_root, proposal_id, reviewer=reviewer, reason=reason)
    return {
        "state": "ok",
        "action": "duplicates-dismiss",
        "committed": False,
        "reviewer": reviewer,
        "reason": reason,
        "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        "equivalent_cli": _dismiss_cli("duplicates", proposal_id, reason, reviewer),
    }


def _duplicates_apply(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    ids = payload.get("ids")
    if ids is not None and (not isinstance(ids, list) or not ids):
        raise ActionError("bad_request", "ids must be a non-empty list.", 400)
    overrides = payload.get("overrides")
    if overrides is not None and not isinstance(overrides, dict):
        raise ActionError("bad_request", "overrides must be a JSON object.", 400)
    result = duplicates_service.apply(
        service.vault,
        service.runtime_root,
        reviewer=reviewer,
        reason=reason,
        ids=tuple(str(item) for item in ids) if ids else None,
        confirmed=confirmed,
        today=today,
        overrides=overrides,
    )
    return {
        "state": "ok",
        "action": "duplicates-apply",
        "committed": result.committed,
        "reviewer": reviewer,
        "reason": reason,
        "applied": list(result.applied),
        "changes": [dict(change) for change in result.changes],
        "equivalent_cli": _apply_cli("duplicates", reason, reviewer, ids, confirmed, overrides),
    }


def _clarification_scan(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    manifest = clarification_service.scan(service.vault, service.runtime_root, today=today)
    return {
        "state": "ok",
        "action": "clarification-scan",
        "committed": False,
        "scan_token": manifest.scan_token,
        "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        "equivalent_cli": _today_scan_cli("clarification", today),
    }


def _clarification_dismiss(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    proposal_id = _required(payload, "id", "invalid_target")
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    manifest = clarification_service.dismiss(service.runtime_root, proposal_id, reviewer=reviewer, reason=reason)
    return {
        "state": "ok",
        "action": "clarification-dismiss",
        "committed": False,
        "reviewer": reviewer,
        "reason": reason,
        "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        "equivalent_cli": _dismiss_cli("clarification", proposal_id, reason, reviewer),
    }


def _clarification_apply(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    ids = payload.get("ids")
    if ids is not None and (not isinstance(ids, list) or not ids):
        raise ActionError("bad_request", "ids must be a non-empty list.", 400)
    overrides = payload.get("overrides")
    if overrides is not None and not isinstance(overrides, dict):
        raise ActionError("bad_request", "overrides must be a JSON object.", 400)
    result = clarification_service.apply(
        service.vault,
        service.runtime_root,
        reviewer=reviewer,
        reason=reason,
        ids=tuple(str(item) for item in ids) if ids else None,
        confirmed=confirmed,
        today=today,
        overrides=overrides,
    )
    return {
        "state": "ok",
        "action": "clarification-apply",
        "committed": result.committed,
        "reviewer": reviewer,
        "reason": reason,
        "applied": list(result.applied),
        "changes": [dict(change) for change in result.changes],
        "equivalent_cli": _apply_cli("clarification", reason, reviewer, ids, confirmed, overrides),
    }


def _identity_scan(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    manifest = identity_service.scan(service.vault, service.runtime_root)
    return {
        "state": "ok",
        "action": "identity-scan",
        "committed": False,
        "scan_token": manifest.scan_token,
        "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        "equivalent_cli": "worksync identity scan",
    }


def _identity_dismiss(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    proposal_id = _required(payload, "id", "invalid_target")
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    manifest = identity_service.dismiss(service.runtime_root, proposal_id, reviewer=reviewer, reason=reason)
    return {
        "state": "ok",
        "action": "identity-dismiss",
        "committed": False,
        "reviewer": reviewer,
        "reason": reason,
        "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        "equivalent_cli": _dismiss_cli("identity", proposal_id, reason, reviewer),
    }


def _identity_apply(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    proposal_id = _required(payload, "id", "invalid_target")
    reason = _required(payload, "reason", "missing_reason")
    decisions = payload.get("decisions")
    if decisions is not None and not isinstance(decisions, dict):
        raise ActionError("bad_request", "decisions must be a JSON object.", 400)
    reviewer = _reviewer(service)
    field_decisions = {str(key): str(value) for key, value in decisions.items()} if decisions else None
    result = run_identity_apply(
        service.vault,
        service.runtime_root,
        proposal_id=proposal_id,
        reviewer=reviewer,
        reason=reason,
        field_decisions=field_decisions,
        confirmed=confirmed,
    )
    return {
        "state": "ok",
        "action": "identity-apply",
        "committed": result.committed,
        "reviewer": reviewer,
        "reason": reason,
        "applied": list(result.applied),
        "changes": [dict(change) for change in result.changes],
        "equivalent_cli": _identity_apply_cli(proposal_id, reason, reviewer, field_decisions, confirmed),
    }


def _lifecycle_transition(service: WriteContext, payload: dict, *, confirmed: bool, today: date | None) -> dict:
    project_id = _required(payload, "project_id", "invalid_target")
    record = _required(payload, "record", "invalid_target")
    kind = _required(payload, "kind", "invalid_target")
    action = _required(payload, "action", "invalid_target")
    reason = _required(payload, "reason", "missing_reason")
    reviewer = _reviewer(service)
    evidence = payload.get("evidence") or {}
    fields = payload.get("fields") or {}
    if not isinstance(evidence, dict) or not isinstance(fields, dict):
        raise ActionError("bad_request", "evidence and fields must be JSON objects.", 400)
    result = apply_lifecycle_transition(
        service.vault,
        service.runtime_root,
        project_id=project_id,
        record_id=record,
        kind=kind,
        action=action,
        actor=reviewer,
        reason=reason,
        today=today or date.today(),
        target_sha=_expected(payload),
        evidence=evidence,
        fields=fields,
        confirmed=confirmed,
        dry_run=bool(payload.get("dry_run")),
    )
    return {
        "state": "ok",
        "action": "lifecycle-transition",
        "committed": result.committed,
        "record_id": result.record_id,
        "kind": result.kind,
        "from_state": result.from_state,
        "to_state": result.to_state,
        "reviewer": reviewer,
        "reason": reason,
        "changes": [dict(change) for change in result.changes],
        "equivalent_cli": _lifecycle_cli(project_id, record, kind, action, reason, reviewer),
    }


def _lifecycle_cli(project_id: str, record: str, kind: str, action: str, reason: str, reviewer: str) -> str:
    return " ".join(
        [
            "worksync",
            "project",
            "lifecycle",
            "--project-id",
            _quote(project_id),
            "--record",
            _quote(record),
            "--kind",
            kind,
            "--action",
            action,
            "--reason",
            _quote(reason),
            "--actor",
            _quote(reviewer),
        ]
    )


def _identity_apply_cli(proposal_id: str, reason: str, reviewer: str, decisions: dict | None, confirmed: bool) -> str:
    parts = [
        "worksync",
        "identity",
        "apply",
        _quote(proposal_id),
        "--reason",
        _quote(reason),
        "--reviewer",
        _quote(reviewer),
    ]
    for field, choice in (decisions or {}).items():
        parts += ["--decision", _quote(f"{field}={choice}")]
    if confirmed:
        parts += ["--confirm"]
    return " ".join(parts)


ACTIONS: dict[str, ActionHandler] = {
    "update-action": _update_action,
    "complete-action": _complete_action,
    "set-reviewer": _set_reviewer,
    "save-layout-profile": _save_layout_profile,
    "apply-batch": _apply_batch,
    "capture": _capture,
    "ingest-scan": _ingest_scan,
    "ingest-apply": _ingest_apply,
    "ingest-dismiss": _ingest_dismiss,
    "krisp-pull": _krisp_pull,
    "krisp-status": _krisp_status,
    "duplicates-scan": _duplicates_scan,
    "duplicates-dismiss": _duplicates_dismiss,
    "duplicates-apply": _duplicates_apply,
    "identity-scan": _identity_scan,
    "identity-dismiss": _identity_dismiss,
    "identity-apply": _identity_apply,
    "clarification-scan": _clarification_scan,
    "clarification-apply": _clarification_apply,
    "clarification-dismiss": _clarification_dismiss,
    "lifecycle-transition": _lifecycle_transition,
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


def _scan_cli(inbox: str | None, rough: str | None, today: date | None) -> str:
    parts = ["worksync", "ingest", "scan"]
    if inbox:
        parts += ["--inbox", _quote(inbox)]
    if rough:
        parts += ["--rough-notes", _quote(rough)]
    if today is not None:
        parts += ["--today", today.isoformat()]
    return " ".join(parts)


def _today_scan_cli(command: str, today: date | None) -> str:
    parts = ["worksync", command, "scan"]
    if today is not None:
        parts += ["--today", today.isoformat()]
    return " ".join(parts)


def _krisp_pull_cli(since_days: int) -> str:
    return " ".join(["worksync", "krisp", "pull", "--since-days", str(since_days)])


def _apply_cli(command: str, reason: str, reviewer: str, ids: object, confirmed: bool, overrides: object) -> str:
    parts = ["worksync", command, "apply", "--reason", _quote(reason), "--reviewer", _quote(reviewer)]
    for item in ids if isinstance(ids, list) else ():
        parts += ["--id", _quote(str(item))]
    for proposal_id, fields in overrides.items() if isinstance(overrides, dict) else ():
        if fields:
            parts += ["--set", _quote(f"{proposal_id}={json.dumps(fields, ensure_ascii=False)}")]
    if confirmed:
        parts += ["--confirm"]
    return " ".join(parts)


def _dismiss_cli(command: str, proposal_id: str, reason: str, reviewer: str) -> str:
    return " ".join(
        [
            "worksync",
            command,
            "dismiss",
            _quote(proposal_id),
            "--reason",
            _quote(reason),
            "--reviewer",
            _quote(reviewer),
        ]
    )


def _quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
