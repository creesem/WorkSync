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
from datetime import date
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import edit_frontmatter_fields, parse_note
from worksync.safety.files import sha256_file
from worksync.safety.models import FileOp
from worksync.work.consolidate import append_update_entry, archive_content, merged_content, redirect_content, revision
from worksync.work.dates import parse_iso_date
from worksync.work.generation import is_legacy_path, live_index, read_generation
from worksync.work.models import EntityType
from worksync.work.notes import Note, load_action_note
from worksync.work.queue import (
    ApplyResult,
    Manifest,
    Proposal,
    QueueError,
    QueueStore,
    apply_proposals,
    content_scan_token,
    scan_manifest,
)
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


class ClarificationError(QueueError):
    """Raised when a clarification-queue review action cannot be applied."""


def discover_clarifications(vault: str | Path, index: WorkIndex, *, today: date) -> tuple[Proposal, ...]:
    """Return one proposal per active action that fails a clarification predicate."""
    vault_root = Path(vault).expanduser().resolve()
    actions = _active_actions(index)
    proposals: list[Proposal] = []
    for entity in actions:
        reasons = _reasons(entity, today)
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
    index = live_index(vault, runtime)
    fresh = discover_clarifications(vault, index, today=when)
    return scan_manifest(QueueStore(runtime, MANIFEST_REL), fresh, token=_scan_token(vault, index), dry_run=dry_run)


def dismiss(runtime: str | Path, proposal_id: str, *, reviewer: str, reason: str, dry_run: bool = False) -> Manifest:
    """Mark one clarification item dismissed with a named reviewer and reason."""
    return QueueStore(runtime, MANIFEST_REL).dismiss(
        proposal_id,
        reviewer=reviewer,
        reason=reason,
        error=ClarificationError,
        no_manifest="No clarification manifest; run 'worksync clarification scan' first.",
        dry_run=dry_run,
    )


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
    when = today or date.today()
    vault_root = Path(vault).expanduser().resolve()
    index: WorkIndex | None = None

    def build_ops(proposal: Proposal, override: dict) -> tuple[list[FileOp], str]:
        nonlocal index
        if index is None:
            index = WorkIndex.from_vault(vault)
        return _item_ops(vault_root, index, proposal, override, when=when, reviewer=reviewer, reason=reason)

    store = QueueStore(runtime, MANIFEST_REL)
    _reject_legacy(store.load(), ids, read_generation(runtime))
    return apply_proposals(
        store,
        vault_root=vault_root,
        reviewer=reviewer,
        reason=reason,
        ids=ids,
        overrides=overrides,
        confirmed=confirmed,
        dry_run=dry_run,
        error=ClarificationError,
        no_manifest="No clarification manifest; run 'worksync clarification scan' first.",
        empty_selection="No pending clarifications were selected.",
        build_ops=build_ops,
        verb=_batch_verb,
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
        content = append_update_entry(plan.content, when=when.isoformat(), reviewer=reviewer, reason=reason)
        return [FileOp("update", Path(plan.path), "trusted", content=content, expected=plan.expected)], resolution

    if resolution == "archive":
        return [
            FileOp(
                "update",
                Path(note.relative),
                "trusted",
                content=archive_content(
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


def _reclassify_content(index: WorkIndex, note: Note, override: dict, *, when: date, reviewer: str, reason: str) -> str:
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
    if owner_entity is None or getattr(owner_entity, "status", "") != "active":
        raise ClarificationError("unknown_owner", f"Owner is not a current active person: {owner}", affected=(owner,))
    if not str(getattr(owner_entity, "team", "") or "").strip():
        raise ClarificationError("unknown_owner", f"Owner is not a current team member: {owner}", affected=(owner,))
    existing_owners = _owner_targets(note.frontmatter)
    if existing_owners and link_target(owner) not in existing_owners:
        raise ClarificationError(
            "owner_conflict", f"Item already has a different owner than: {owner}", affected=(note.relative,)
        )
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


def _reasons(entity, today: date) -> list[str]:
    reasons: list[str] = []
    if not link_target(getattr(entity, "project", "") or ""):
        reasons.append("missing project")
    if not getattr(entity, "owners", ()):
        reasons.append("missing owner")
    priority = getattr(entity, "priority", None)
    if priority is not None and priority not in PRIORITY_VALUES:
        reasons.append(f"invalid priority: {priority}")
    due = parse_iso_date(getattr(entity, "due", None))
    if due is not None and due.date() < today and entity.status not in TERMINAL_STATUSES:
        reasons.append(f"past due {due.date().isoformat()} with status {entity.status}")
    return reasons


def _owner_targets(frontmatter: dict) -> set[str]:
    owners = frontmatter.get("owners")
    if isinstance(owners, (list, tuple)):
        return {link_target(str(owner)) for owner in owners if link_target(str(owner))}
    if owners is None:
        return set()
    target = link_target(str(owners))
    return {target} if target else set()


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
    return content_scan_token(vault, _active_actions(index))


def _active_actions(index: WorkIndex) -> list:
    return [entity for entity in index.list_type(EntityType.ACTION.value) if entity.status in ACTIVE_ACTION_STATUSES]


def _load(vault_root: Path, relative: str, expected: str | None, proposal_id: str) -> Note:
    return load_action_note(
        vault_root,
        relative,
        expected,
        proposal_id=proposal_id,
        error=ClarificationError,
        missing_message=f"Item is missing a path: {proposal_id}",
    )


def _batch_verb(resolutions: tuple[str, ...]) -> str:
    for verb in ("merge", "archive", "reclassify"):
        if verb in resolutions:
            return verb
    return "keep"


def _reject_legacy(manifest: Manifest | None, ids: tuple[str, ...] | None, generation) -> None:
    """Refuse to apply a clarification whose action is frozen legacy work."""
    if manifest is None:
        return
    blocked = tuple(
        proposal.id
        for proposal in manifest.proposals
        if proposal.status == "pending"
        and (ids is None or proposal.id in ids)
        and is_legacy_path(proposal.source_path, generation)
    )
    if blocked:
        raise ClarificationError(
            "legacy_target",
            "Legacy work cannot be applied: " + ", ".join(blocked),
            affected=blocked,
        )
