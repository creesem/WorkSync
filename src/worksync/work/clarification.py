"""Surface and resolve active actions that need clarification.

The queue is a pure predicate over canonical frontmatter fields only — no prose parsing
and no model inference can originate or decide an item. Each item's basis is the hash of
the material fields the predicate and decision touched, so a body-only edit does not void
a remembered decision while a material change does. Resolutions commit as one batch
through the gateway via :mod:`worksync.work.queue`; this module imports no ``context``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import edit_frontmatter_fields, parse_note
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.consolidate import merged_content, redirect_content, revision
from worksync.work.dates import parse_iso_date
from worksync.work.models import EntityType
from worksync.work.queue import Manifest, Proposal, QueueStore, merge_manifest
from worksync.work.repository import WorkIndex
from worksync.work.schema import ACTIVE_ACTION_STATUSES, detect_type, link_target
from worksync.work.similarity import score
from worksync.work.writer import plan_update_action

MANIFEST_REL = Path("clarification") / "manifest.json"
MATERIAL_FIELDS = ("project", "owners", "priority", "status", "due")
PRIORITY_VALUES = frozenset({"P1", "P2", "P3", "P4"})
TERMINAL_STATUSES = frozenset({"done", "cancelled"})
RESOLUTIONS = ("keep", "merge", "reclassify", "archive")
MATCH_LIMIT = 3
MATCH_FLOOR = 0.3
LAST_ACTION_LIMIT = 240


class ClarificationError(ValueError):
    """Raised when a clarification-queue review action cannot be applied."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class ApplyResult:
    """The visible outcome of applying a reviewed clarification batch."""

    committed: bool
    journal: Path
    changes: tuple[dict, ...]
    applied: tuple[str, ...]


def discover_clarifications(vault: str | Path, index: WorkIndex, *, today: date) -> tuple[Proposal, ...]:
    """Return one proposal per active action that fails a clarification predicate."""
    vault_root = Path(vault).expanduser().resolve()
    actions = _active_actions(index)
    proposals: list[Proposal] = []
    for entity in actions:
        reasons = _reasons(entity, index, today)
        if not reasons:
            continue
        proposals.append(
            Proposal(
                id=f"{entity.path}#clarify",
                action="keep",
                source_path=entity.path,
                source_sha256=sha256_file(vault_root / entity.path),
                basis_sha256=_material_basis(entity),
                fields={"reasons": "; ".join(reasons), "matches": " · ".join(_top_matches(entity, actions))},
                confidence=round(min(1.0, 0.5 + 0.15 * len(reasons)), 4),
                provenance=tuple(reasons),
            )
        )
    return tuple(sorted(proposals, key=lambda proposal: proposal.source_path))


def scan(vault: str | Path, runtime: str | Path, *, today: date | None = None, dry_run: bool = False) -> Manifest:
    """Queue clarification items and persist the merged manifest with a precondition."""
    when = today or date.today()
    index = WorkIndex.from_vault(vault)
    fresh = discover_clarifications(vault, index, today=when)
    store = QueueStore(runtime, MANIFEST_REL)
    loaded = store.load_with_hash()
    previous = loaded[0] if loaded is not None else None
    manifest = merge_manifest(previous, fresh, token=_scan_token(vault, index))
    if not dry_run:
        store.save(
            manifest,
            expected=loaded[1] if loaded is not None else None,
            expected_absent=loaded is None,
        )
    return manifest


def dismiss(runtime: str | Path, proposal_id: str, *, reviewer: str, reason: str, dry_run: bool = False) -> Manifest:
    """Mark one clarification item dismissed with a named reviewer and reason."""
    if not str(reviewer).strip():
        raise ClarificationError("missing_reviewer", "A dismissal requires a named reviewer.")
    if not str(reason).strip():
        raise ClarificationError("missing_reason", "A dismissal requires a human-readable reason.")
    store = QueueStore(runtime, MANIFEST_REL)
    loaded = store.load_with_hash()
    if loaded is None:
        raise ClarificationError("no_manifest", "No clarification manifest; run 'worksync clarification scan' first.")
    manifest, expected = loaded

    found = False
    updated: list[Proposal] = []
    for proposal in manifest.proposals:
        if proposal.id == proposal_id:
            updated.append(replace(proposal, status="dismissed", reviewer=reviewer, reason=reason, decided_at=_now()))
            found = True
        else:
            updated.append(proposal)
    if not found:
        raise ClarificationError("unknown_proposal", f"No proposal with id: {proposal_id}", affected=(proposal_id,))

    new_manifest = manifest.with_proposals(tuple(updated))
    if not dry_run:
        store.save(new_manifest, expected=expected, expected_absent=False)
    return new_manifest


def load_manifest(runtime: str | Path) -> Manifest | None:
    """Load the clarification manifest, or ``None`` when absent."""
    return QueueStore(runtime, MANIFEST_REL).load()


def manifest_path(runtime: str | Path) -> Path:
    """Return the clarification manifest path under the staging zone."""
    return QueueStore(runtime, MANIFEST_REL).path()


def apply(
    vault: str | Path,
    runtime: str | Path,
    *,
    reviewer: str,
    reason: str,
    ids: tuple[str, ...] | None = None,
    confirmed: bool = False,
    today: date | None = None,
    overrides: dict[str, dict] | None = None,
    dry_run: bool = False,
) -> ApplyResult:
    """Apply the selected pending clarifications as one transaction through the gateway."""
    if not str(reviewer).strip():
        raise ClarificationError("missing_reviewer", "An apply requires a named reviewer.")
    if not str(reason).strip():
        raise ClarificationError("missing_reason", "An apply requires a human-readable reason.")
    store = QueueStore(runtime, MANIFEST_REL)
    loaded = store.load_with_hash()
    if loaded is None:
        raise ClarificationError("no_manifest", "No clarification manifest; run 'worksync clarification scan' first.")
    manifest, manifest_hash = loaded
    wanted = set(ids) if ids is not None else None
    selected = tuple(
        proposal
        for proposal in manifest.proposals
        if proposal.status == "pending" and (wanted is None or proposal.id in wanted)
    )
    if not selected:
        raise ClarificationError("no_proposals", "No pending clarifications were selected.")

    when = today or date.today()
    vault_root = Path(vault).expanduser().resolve()
    index = WorkIndex.from_vault(vault)
    ops: list[FileOp] = []
    resolutions: list[str] = []
    for proposal in selected:
        override = (overrides or {}).get(proposal.id) or {}
        if not isinstance(override, dict):
            raise ClarificationError(
                "invalid_override", f"Override for {proposal.id} must be an object.", affected=(proposal.id,)
            )
        item_ops, resolution = _item_ops(
            vault_root, index, proposal, override, when=when, reviewer=reviewer, reason=reason
        )
        ops.extend(item_ops)
        resolutions.append(resolution)

    selected_ids = {proposal.id for proposal in selected}
    updated = tuple(
        replace(proposal, status="applied", reviewer=reviewer, reason=reason, decided_at=_now())
        if proposal.id in selected_ids
        else proposal
        for proposal in manifest.proposals
    )
    ops.append(store.manifest_op(manifest.with_proposals(updated), expected=manifest_hash))

    if dry_run:
        return ApplyResult(
            committed=False,
            journal=Path(),
            changes=tuple(_op_dict(op) for op in ops),
            applied=tuple(proposal.id for proposal in selected),
        )

    changeset = ChangeSet(_verb(resolutions), tuple(ops), reviewer=str(reviewer).strip(), reason=str(reason).strip())
    result: CommitResult = commit(changeset, write_zones(vault_root, runtime), confirmed=confirmed)
    return ApplyResult(
        committed=result.committed,
        journal=result.journal,
        changes=result.changes,
        applied=tuple(proposal.id for proposal in selected),
    )


def _item_ops(
    vault_root: Path, index: WorkIndex, proposal: Proposal, override: dict, *, when: date, reviewer: str, reason: str
) -> tuple[list[FileOp], str]:
    resolution = str(override.get("resolution") or "keep").strip().casefold()
    if resolution not in RESOLUTIONS:
        raise ClarificationError(
            "unsupported_resolution", f"Unsupported resolution: {resolution}", affected=(proposal.id,)
        )
    note = _load(vault_root, proposal.source_path, proposal.source_sha256, proposal.id)

    if resolution == "keep":
        plan = plan_update_action(
            vault_root,
            note.relative,
            fields={},
            reason=reason,
            reviewer=reviewer,
            expected=note.sha,
            today=when,
        )
        return [FileOp("update", Path(plan.path), "trusted", content=plan.content, expected=plan.expected)], resolution

    if resolution == "archive":
        return [
            FileOp(
                "update",
                Path(note.relative),
                "trusted",
                content=redirect_content(
                    note.content, note.frontmatter, note.title, when=when.isoformat(), reviewer=reviewer, reason=reason
                ),
                expected=note.sha,
            )
        ], resolution

    if resolution == "reclassify":
        content = _reclassify_content(index, note, override, when=when, reviewer=reviewer, reason=reason)
        return [FileOp("update", Path(note.relative), "trusted", content=content, expected=note.sha)], resolution

    target = _merge_target(vault_root, override, note.relative, proposal.id)
    return [
        FileOp(
            "update",
            Path(target[0]),
            "trusted",
            content=merged_content(target[1], note.content),
            expected=target[2],
        ),
        FileOp(
            "update",
            Path(note.relative),
            "trusted",
            content=redirect_content(
                note.content,
                note.frontmatter,
                _title_of(vault_root, target[0]),
                when=when.isoformat(),
                reviewer=reviewer,
                reason=reason,
            ),
            expected=note.sha,
        ),
    ], resolution


def _merge_target(vault_root: Path, override: dict, item_path: str, proposal_id: str) -> tuple[str, str, str]:
    canonical = str(override.get("canonical") or "").strip()
    if not canonical:
        raise ClarificationError("missing_target", "A merge requires a canonical action.", affected=(proposal_id,))
    try:
        resolved = ensure_under(vault_root, vault_root / canonical)
    except PathSafetyError as exc:
        raise ClarificationError("invalid_target", str(exc), affected=(canonical,)) from exc
    if not resolved.is_file():
        raise ClarificationError("missing_source", f"Merge target not found: {canonical}", affected=(canonical,))
    if resolved.resolve() == (vault_root / item_path).resolve():
        raise ClarificationError("invalid_target", "A merge target cannot be the item itself.", affected=(canonical,))
    record = parse_note(resolved, vault_root)
    if detect_type(record.frontmatter.get("type")) != EntityType.ACTION.value:
        raise ClarificationError(
            "not_action", f"Merge target is not an action note: {canonical}", affected=(canonical,)
        )
    relative = resolved.resolve().relative_to(vault_root).as_posix()
    return relative, record.content, record.content_hash


def _title_of(vault_root: Path, relative: str) -> str:
    return parse_note(vault_root / relative, vault_root).title


def _reclassify_content(
    index: WorkIndex, note: _Note, override: dict, *, when: date, reviewer: str, reason: str
) -> str:
    project = str(override.get("project") or "").strip()
    owner = str(override.get("owner") or "").strip()
    dependency = str(override.get("dependency") or "").strip()
    next_review = str(override.get("next_review") or "").strip()
    missing = [
        name
        for name, value in (
            ("project", project),
            ("owner", owner),
            ("dependency", dependency),
            ("next_review", next_review),
        )
        if not value
    ]
    if missing:
        raise ClarificationError(
            "missing_reclassify_fields",
            f"A waiting-on reclassify requires: {', '.join(missing)}",
            affected=(note.relative,),
        )
    project_entity = index.get("project", project)
    if project_entity is None:
        raise ClarificationError("unknown_project", f"Unknown project: {project}", affected=(project,))
    owner_entity = index.get("person", owner)
    if owner_entity is None:
        raise ClarificationError("unknown_owner", f"Unknown owner: {owner}", affected=(owner,))
    if parse_iso_date(next_review) is None:
        raise ClarificationError(
            "invalid_next_review", f"Next review is not an ISO date: {next_review}", affected=(next_review,)
        )
    fields = {
        "status": "waiting",
        "waiting_on": dependency,
        "project": json.dumps(f"[[{project_entity.title}]]"),
        "due": next_review,
        "updated": when.isoformat(),
        "revision": str(revision(note.frontmatter) + 1),
        "updated_by": str(reviewer).strip(),
        "last_action": str(reason).strip()[:LAST_ACTION_LIMIT],
    }
    if not note.frontmatter.get("owners"):
        fields["owners"] = json.dumps(f"[[{owner_entity.title}]]")
    return edit_frontmatter_fields(note.content, set_fields=fields)


def _reasons(entity, index: WorkIndex, today: date) -> list[str]:
    reasons: list[str] = []
    project = link_target(getattr(entity, "project", "") or "")
    if not project:
        reasons.append("missing project")
    elif index.get("project", project) is None:
        reasons.append(f"unknown project: {project}")
    if not getattr(entity, "owners", ()):
        reasons.append("missing owner")
    priority = getattr(entity, "priority", None)
    if priority is not None and priority not in PRIORITY_VALUES:
        reasons.append(f"invalid priority: {priority}")
    due = parse_iso_date(getattr(entity, "due", None))
    if due is not None and due.date() < today and entity.status not in TERMINAL_STATUSES:
        reasons.append(f"past due {due.date().isoformat()} with status {entity.status}")
    return reasons


def _top_matches(entity, actions) -> list[str]:
    scored = []
    for other in actions:
        if other.path == entity.path:
            continue
        similarity = score(entity.title, other.title)
        if similarity >= MATCH_FLOOR:
            scored.append((similarity, other.title, other.path))
    scored.sort(key=lambda item: (-item[0], item[2]))
    return [f"{title} ({similarity:.2f})" for similarity, title, _path in scored[:MATCH_LIMIT]]


def _material_basis(entity) -> str:
    material = {key: (entity.raw or {}).get(key) for key in MATERIAL_FIELDS}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _scan_token(vault: str | Path, index: WorkIndex) -> str:
    vault_root = Path(vault).expanduser().resolve()
    payload = sorted((entity.path, sha256_file(vault_root / entity.path)) for entity in _active_actions(index))
    return hashlib.sha256("|".join(f"{path}:{digest}" for path, digest in payload).encode("utf-8")).hexdigest()


def _active_actions(index: WorkIndex) -> list:
    return [entity for entity in index.list_type(EntityType.ACTION.value) if entity.status in ACTIVE_ACTION_STATUSES]


@dataclass(frozen=True)
class _Note:
    relative: str
    content: str
    title: str
    frontmatter: dict
    sha: str


def _load(vault_root: Path, relative: str, expected: str | None, proposal_id: str) -> _Note:
    if not relative:
        raise ClarificationError("missing_target", f"Item is missing a path: {proposal_id}", affected=(proposal_id,))
    try:
        target = ensure_under(vault_root, vault_root / relative)
    except PathSafetyError as exc:
        raise ClarificationError("invalid_source", str(exc), affected=(relative,)) from exc
    if not target.is_file():
        raise ClarificationError("missing_source", f"Note not found: {relative}", affected=(relative,))
    current = sha256_file(target)
    if expected and current != expected:
        raise ClarificationError("stale_source", f"Note changed since the scan: {relative}", affected=(relative,))
    record = parse_note(target, vault_root)
    if detect_type(record.frontmatter.get("type")) != EntityType.ACTION.value:
        raise ClarificationError("not_action", f"Target is not an action note: {relative}", affected=(relative,))
    return _Note(
        relative=relative, content=record.content, title=record.title, frontmatter=record.frontmatter, sha=current
    )


def _verb(resolutions: list[str]) -> str:
    for verb in ("merge", "archive", "reclassify"):
        if verb in resolutions:
            return verb
    return "keep"


def _op_dict(op: FileOp) -> dict:
    return {
        "kind": op.kind,
        "zone": op.zone,
        "path": str(op.path),
        "destination": str(op.destination) if op.destination else None,
        "before": None,
        "after": None,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
