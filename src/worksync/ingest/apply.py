"""Apply a reviewed batch of proposals through the single mutation gateway.

Every canonical write and the proposal-manifest update travel in one ``ChangeSet``, so a
batch either commits coherently or restores its prior state. A source is never unlinked:
it is disposition-moved only after its destination write succeeds and a backup exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from worksync.core.names import safe_name
from worksync.core.paths import PathSafetyError, ensure_under, unique_target
from worksync.ingest.discover import IngestError
from worksync.ingest.manifest import (
    MANIFEST_REL,
    Manifest,
    load_manifest_with_hash,
    save_manifest,
)
from worksync.ingest.proposal import Proposal
from worksync.inventory.parse import edit_frontmatter_fields, parse_note, split_frontmatter
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.queue import QueueStore, op_dict
from worksync.work.schema import canonical_action_status, canonical_priority

DEFAULT_ACTIVE = "7. Task Notes/Active"
DEFAULT_DROPPED = "7. Task Notes/Dropped"
DEFAULT_MEETINGS = "10. Meetings"
DEFAULT_KRISP_INBOX = "krisp/inbox"
PROCESSED_DIRNAME = "Processed"
OVERLAY_FIELDS = frozenset({"title", "status", "priority", "owners", "project", "due"})
MEETING_OVERLAY_FIELDS = frozenset({"title", "date", "status", "attendees", "projects", "meeting_type"})
MEETING_STATUSES = ("scheduled", "held", "cancelled")


@dataclass(frozen=True)
class ApplyResult:
    """The visible outcome of applying a reviewed batch."""

    committed: bool
    journal: Path
    changes: tuple[dict, ...]
    applied: tuple[str, ...]


def apply(
    vault: str | Path,
    runtime: str | Path,
    *,
    reviewer: str,
    reason: str,
    ids: tuple[str, ...] | None = None,
    confirmed: bool = False,
    today: date | None = None,
    active_path: str | None = None,
    dropped_path: str | None = None,
    meetings_path: str | None = None,
    krisp_inbox_path: str | Path | None = None,
    overrides: dict[str, dict] | None = None,
    dry_run: bool = False,
) -> ApplyResult:
    """Apply the selected pending proposals as one transaction."""
    if not str(reviewer).strip():
        raise IngestError("missing_reviewer", "An apply requires a named reviewer.")
    if not str(reason).strip():
        raise IngestError("missing_reason", "An apply requires a human-readable reason.")
    loaded = load_manifest_with_hash(runtime)
    if loaded is None:
        raise IngestError("no_manifest", "No ingest manifest; run 'ingest scan' first.")
    manifest, manifest_hash = loaded
    selected = _apply_overrides(_select(manifest, ids), overrides)
    if not selected:
        raise IngestError("no_proposals", "No pending proposals were selected.")

    when = today or date.today()
    vault_root = Path(vault).expanduser().resolve()
    runtime_root = Path(runtime).expanduser().resolve()
    active_root = _contained_root(vault_root, active_path or DEFAULT_ACTIVE)
    dropped_root = _contained_root(vault_root, dropped_path or DEFAULT_DROPPED)
    meetings_root = _contained_root(vault_root, meetings_path or DEFAULT_MEETINGS)
    inbox_root = (
        Path(krisp_inbox_path).expanduser().resolve()
        if krisp_inbox_path is not None
        else runtime_root / DEFAULT_KRISP_INBOX
    )
    try:
        inbox_root = ensure_under(runtime_root, inbox_root)
    except PathSafetyError as exc:
        raise IngestError("invalid_root", f"Krisp inbox must be inside the runtime root: {inbox_root}") from exc

    ops: list[FileOp] = []
    for proposal in selected:
        if proposal.action == "meeting":
            ops.extend(
                _meeting_ops(
                    vault_root,
                    runtime_root,
                    meetings_root,
                    inbox_root,
                    proposal,
                    today=when,
                    reviewer=reviewer,
                    reason=reason,
                )
            )
        else:
            ops.extend(
                _proposal_ops(
                    vault_root, active_root, dropped_root, proposal, today=when, reviewer=reviewer, reason=reason
                )
            )

    selected_by_id = {proposal.id: proposal for proposal in selected}
    updated = tuple(
        replace(selected_by_id[proposal.id], status="applied", reviewer=reviewer, reason=reason)
        if proposal.id in selected_by_id
        else proposal
        for proposal in manifest.proposals
    )
    new_manifest = manifest.with_proposals(updated)
    ops.append(QueueStore(runtime, MANIFEST_REL).manifest_op(new_manifest, expected=manifest_hash))

    if dry_run:
        return ApplyResult(
            committed=False,
            journal=Path(),
            changes=tuple(op_dict(op) for op in ops),
            applied=tuple(proposal.id for proposal in selected),
        )

    changeset = ChangeSet(_verb(selected), tuple(ops), reviewer=reviewer, reason=str(reason).strip())
    result: CommitResult = commit(changeset, write_zones(vault_root, runtime), confirmed=confirmed)
    return ApplyResult(
        committed=result.committed,
        journal=result.journal,
        changes=result.changes,
        applied=tuple(proposal.id for proposal in selected),
    )


def dismiss(runtime: str | Path, proposal_id: str, *, reviewer: str, reason: str) -> Manifest:
    """Mark one proposal dismissed with a named reviewer and reason."""
    if not str(reviewer).strip():
        raise IngestError("missing_reviewer", "A dismissal requires a named reviewer.")
    if not str(reason).strip():
        raise IngestError("missing_reason", "A dismissal requires a human-readable reason.")
    loaded = load_manifest_with_hash(runtime)
    if loaded is None:
        raise IngestError("no_manifest", "No ingest manifest; run 'ingest scan' first.")
    manifest, expected = loaded

    found = False
    updated: list[Proposal] = []
    for proposal in manifest.proposals:
        if proposal.id == proposal_id:
            updated.append(replace(proposal, status="dismissed", reviewer=reviewer, reason=reason))
            found = True
        else:
            updated.append(proposal)
    if not found:
        raise IngestError("unknown_proposal", f"No proposal with id: {proposal_id}", affected=(proposal_id,))

    new_manifest = manifest.with_proposals(tuple(updated))
    save_manifest(runtime, new_manifest, expected=expected, expected_absent=False)
    return new_manifest


def _select(manifest: Manifest, ids: tuple[str, ...] | None) -> tuple[Proposal, ...]:
    wanted = set(ids) if ids is not None else None
    return tuple(
        proposal
        for proposal in manifest.proposals
        if proposal.status == "pending" and (wanted is None or proposal.id in wanted)
    )


def _apply_overrides(selected: tuple[Proposal, ...], overrides: dict[str, dict] | None) -> tuple[Proposal, ...]:
    if not overrides:
        return selected
    updated: list[Proposal] = []
    for proposal in selected:
        override = overrides.get(proposal.id)
        if override is None:
            updated.append(proposal)
            continue
        if not isinstance(override, dict):
            raise IngestError(
                "invalid_override", f"Override for {proposal.id} must be an object.", affected=(proposal.id,)
            )
        clean: dict = {}
        allowed = MEETING_OVERLAY_FIELDS if proposal.action == "meeting" else OVERLAY_FIELDS
        for key, value in override.items():
            if key not in allowed:
                raise IngestError("invalid_override", f"Unknown override field: {key}", affected=(proposal.id,))
            clean[key] = _normalize_override(key, value, proposal.id, action=proposal.action)
        updated.append(replace(proposal, fields={**proposal.fields, **clean}) if clean else proposal)
    return tuple(updated)


def _normalize_override(key: str, value: object, proposal_id: str, *, action: str = "") -> object:
    if action == "meeting":
        return _normalize_meeting_override(key, value, proposal_id)
    if key == "owners":
        return _override_owners(value, proposal_id)
    if key == "project":
        text = _override_text(value, proposal_id)
        return text if text.startswith("[[") else f"[[{text}]]"
    if key == "priority":
        mappable, canonical = canonical_priority(_override_text(value, proposal_id))
        if not mappable or canonical is None:
            raise IngestError("invalid_override", f"Unknown priority: {value!r}", affected=(proposal_id,))
        return canonical
    return _override_text(value, proposal_id)


def _normalize_meeting_override(key: str, value: object, proposal_id: str) -> object:
    if key in ("attendees", "projects"):
        return _override_owners(value, proposal_id)
    if key == "date":
        text = _override_text(value, proposal_id)
        try:
            date.fromisoformat(text)
        except ValueError as exc:
            raise IngestError("invalid_override", f"Unknown date: {value!r}", affected=(proposal_id,)) from exc
        return text
    if key == "status":
        text = _override_text(value, proposal_id).casefold()
        if text not in MEETING_STATUSES:
            raise IngestError("invalid_override", f"Unknown meeting status: {value!r}", affected=(proposal_id,))
        return text
    return _override_text(value, proposal_id)


def _override_text(value: object, proposal_id: str) -> str:
    if not isinstance(value, str):
        raise IngestError("invalid_override", "Override values must be strings.", affected=(proposal_id,))
    return value.strip()


def _override_owners(value: object, proposal_id: str) -> list[str]:
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        items = [item.strip() for item in value if item.strip()]
    else:
        raise IngestError(
            "invalid_override", "owners override must be a name or list of names.", affected=(proposal_id,)
        )
    return [item if item.startswith("[[") else f"[[{item}]]" for item in items]


def _proposal_ops(
    vault_root: Path,
    active_root: Path,
    dropped_root: Path,
    proposal: Proposal,
    *,
    today: date,
    reviewer: str,
    reason: str,
) -> list[FileOp]:
    source = _resolve_source(vault_root, proposal.source_path, proposal.id)
    if sha256_file(source) != proposal.source_sha256:
        raise IngestError(
            "stale_source",
            f"Source changed since the scan: {proposal.source_path}",
            affected=(proposal.source_path,),
        )
    destination = _archive_destination(dropped_root, source)
    ops: list[FileOp] = []

    if proposal.action == "action":
        ops.append(_create_op(vault_root, active_root, proposal, source, today=today, reviewer=reviewer, reason=reason))
    elif proposal.action == "link-existing":
        if not proposal.target_path:
            raise IngestError(
                "missing_target", f"A link-existing requires a target: {proposal.id}", affected=(proposal.id,)
            )
        _resolve_source(vault_root, proposal.target_path, proposal.id)
    elif proposal.action == "merge":
        ops.extend(_merge_ops(vault_root, proposal))
    elif proposal.action != "drop":
        raise IngestError(
            "unsupported_action", f"Unsupported proposal action: {proposal.action}", affected=(proposal.id,)
        )

    ops.append(
        FileOp(
            "move",
            _relative(vault_root, source),
            "trusted",
            destination=_relative(vault_root, destination),
            expected=proposal.source_sha256,
        )
    )
    return ops


def _create_op(
    vault_root: Path,
    active_root: Path,
    proposal: Proposal,
    source: Path,
    *,
    today: date,
    reviewer: str,
    reason: str,
) -> FileOp:
    title = str(proposal.fields.get("title") or source.stem).strip() or source.stem
    target = unique_target(active_root, f"{safe_name(title, fallback='untitled')}.md")
    body = split_frontmatter(source.read_text(encoding="utf-8"))[1]
    content = _action_content(proposal.fields, body, today=today, reviewer=reviewer, reason=reason)
    return FileOp("create", _relative(vault_root, target), "trusted", content=content)


def _merge_ops(vault_root: Path, proposal: Proposal) -> list[FileOp]:
    if not proposal.target_path:
        raise IngestError("missing_target", f"A merge requires a target: {proposal.id}", affected=(proposal.id,))
    target = _resolve_source(vault_root, proposal.target_path, proposal.id)
    record = parse_note(target, vault_root)
    edits: dict[str, str] = {}
    for key in ("priority", "due"):
        if proposal.fields.get(key) and not record.frontmatter.get(key):
            edits[key] = str(proposal.fields[key])
    if not edits:
        raise IngestError(
            "merge_noop",
            f"The merge target already has every proposed field: {proposal.id}",
            affected=(proposal.id,),
        )
    content = edit_frontmatter_fields(record.content, set_fields=edits)
    return [FileOp("update", _relative(vault_root, target), "trusted", content=content, expected=record.content_hash)]


def _action_content(fields: dict, body: str, *, today: date, reviewer: str, reason: str) -> str:
    status = canonical_action_status(fields.get("status") or "open")
    if status is None:
        raise IngestError("unmappable_status", f"Unknown action status: {fields.get('status')!r}")
    lines = ["---", "type: action", f"status: {status}"]
    if fields.get("priority"):
        mappable, canonical = canonical_priority(fields["priority"])
        if not mappable or canonical is None:
            raise IngestError("unmappable_priority", f"Unknown action priority: {fields['priority']!r}")
        lines.append(f"priority: {canonical}")
    owners = fields.get("owners") or []
    if owners:
        lines.append("owners:")
        lines.extend(f"  - {_scalar(owner)}" for owner in owners)
    if fields.get("project"):
        lines.append(f"project: {_scalar(fields['project'])}")
    if fields.get("due"):
        lines.append(f"due: {fields['due']}")
    if fields.get("source"):
        stem = Path(str(fields["source"])).stem
        lines.append(f"source: {_scalar(f'[[{stem}]]')}")
    lines.append(f"created: {today.isoformat()}")
    lines.append(f"updated: {today.isoformat()}")
    lines.append("revision: 1")
    lines.append(f"updated_by: {_scalar(reviewer)}")
    lines.append(f"last_action: {_scalar(reason)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


def _scalar(value: object) -> str:
    return json.dumps(str(value))


def _meeting_ops(
    vault_root: Path,
    runtime_root: Path,
    meetings_root: Path,
    inbox_root: Path,
    proposal: Proposal,
    *,
    today: date,
    reviewer: str,
    reason: str,
) -> list[FileOp]:
    transcript = _resolve_krisp_source(inbox_root, proposal.source_path, proposal.source_sha256, proposal.id)
    sidecar = transcript.with_suffix(".krisp.json")
    if not sidecar.is_file():
        raise IngestError("missing_source", f"Sidecar not found: {sidecar}", affected=(proposal.source_path,))
    title = str(proposal.fields.get("title") or "meeting").strip() or "meeting"
    target = unique_target(meetings_root, f"Meeting - {safe_name(title, fallback='meeting')}.md")
    content = render_meeting_note(proposal.fields)
    processed = inbox_root / PROCESSED_DIRNAME / today.isoformat()
    transcript_dest = unique_target(processed, transcript.name)
    sidecar_dest = unique_target(processed, sidecar.name)
    return [
        FileOp("create", _relative(vault_root, target), "trusted", content=content),
        FileOp(
            "move",
            _relative(runtime_root, transcript),
            "runtime",
            destination=_relative(runtime_root, transcript_dest),
            expected=proposal.source_sha256,
        ),
        FileOp(
            "move",
            _relative(runtime_root, sidecar),
            "runtime",
            destination=_relative(runtime_root, sidecar_dest),
            expected=sha256_file(sidecar),
        ),
    ]


def _resolve_krisp_source(inbox_root: Path, relative: str, expected_sha: str, proposal_id: str) -> Path:
    if not relative:
        raise IngestError("missing_source", f"Proposal has no transcript: {proposal_id}", affected=(proposal_id,))
    try:
        resolved = ensure_under(inbox_root, inbox_root / relative)
    except PathSafetyError as exc:
        raise IngestError("invalid_source", str(exc), affected=(relative,)) from exc
    if not resolved.is_file():
        raise IngestError("missing_source", f"Transcript not found: {relative}", affected=(relative,))
    if expected_sha and sha256_file(resolved) != expected_sha:
        raise IngestError("stale_source", f"Transcript changed since the scan: {relative}", affected=(relative,))
    return resolved


def render_meeting_note(fields: dict) -> str:
    """Render a meeting note using only the current ``meeting`` schema.

    Fails closed on an invalid draft instead of coercing it: a status outside the
    canonical set, or a missing/unparseable date, aborts the render so the whole batch
    writes nothing.
    """
    status = str(fields.get("status") or "").strip().casefold()
    if status not in MEETING_STATUSES:
        raise IngestError("invalid_meeting_status", f"Unknown meeting status: {fields.get('status')!r}")
    date_value = str(fields.get("date") or "").strip()
    try:
        date.fromisoformat(date_value)
    except ValueError as exc:
        raise IngestError(
            "invalid_meeting_date", f"Meeting date is missing or not an ISO date: {fields.get('date')!r}"
        ) from exc
    lines = ["---", "type: meeting", f"status: {status}", f"date: {date_value}"]
    if fields.get("date_status"):
        lines.append(f"date_status: {_scalar(fields['date_status'])}")
    attendees = fields.get("attendees") or []
    if attendees:
        lines.append("attendees:")
        lines.extend(f"  - {_scalar(item)}" for item in attendees)
    projects = fields.get("projects") or []
    if projects:
        lines.append("projects:")
        lines.extend(f"  - {_scalar(item)}" for item in projects)
    if fields.get("meeting_type"):
        lines.append(f"meeting_type: {_scalar(fields['meeting_type'])}")
    if fields.get("source_system"):
        lines.append(f"source_system: {_scalar(fields['source_system'])}")
    if fields.get("external_id"):
        lines.append(f"external_id: {_scalar(fields['external_id'])}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + _meeting_body(fields) + "\n"


def _meeting_body(fields: dict) -> str:
    notes_text = str(fields.get("notes_text") or "").strip()
    notes = notes_text or "\n".join(f"- {point}" for point in fields.get("key_points") or [])
    sections = ["## Notes\n\n" + notes if notes else "## Notes"]

    action_lines: list[str] = []
    for item in fields.get("action_items") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        assignee = str(item.get("assignee") or "").strip()
        action_lines.append(f"- {assignee}: {text}" if assignee else f"- {text}")
    sections.append("## Actions\n\n" + "\n".join(action_lines) if action_lines else "## Actions")

    sections.append("## Decisions")
    sections.append("## Risks / Blockers")
    return "\n\n".join(sections)


def _resolve_source(vault_root: Path, relative: str, proposal_id: str) -> Path:
    if not relative:
        raise IngestError("missing_source", f"Proposal has no source: {proposal_id}", affected=(proposal_id,))
    try:
        resolved = ensure_under(vault_root, vault_root / relative)
    except PathSafetyError as exc:
        raise IngestError("invalid_source", str(exc), affected=(relative,)) from exc
    if not resolved.is_file():
        raise IngestError("missing_source", f"Source not found: {relative}", affected=(relative,))
    return resolved


def _contained_root(vault_root: Path, relative: str) -> Path:
    try:
        return ensure_under(vault_root, vault_root / relative)
    except PathSafetyError as exc:
        raise IngestError("invalid_root", str(exc), affected=(relative,)) from exc


def _archive_destination(dropped_root: Path, source: Path) -> Path:
    destination = dropped_root / source.name
    if destination.exists():
        destination = unique_target(dropped_root, source.name)
    return destination


def _relative(vault_root: Path, path: Path) -> Path:
    return path.resolve().relative_to(vault_root)


def _verb(selected: tuple[Proposal, ...]) -> str:
    kinds = {proposal.action for proposal in selected}
    if "drop" in kinds:
        return "drop"
    if "merge" in kinds:
        return "merge"
    return "promote"
