"""Detect and review duplicate action pairs.

Detection is deterministic: active ``action`` notes are scored pairwise with the shared
similarity scorer plus evidence bonuses for a shared project, shared owner, and shared
title terms. A match only ever creates a proposal; nothing is applied without a human
confirmation. The queue is persisted through :mod:`worksync.work.queue`, and this module
imports no ``context``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import parse_note
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.consolidate import merged_content, redirect_content
from worksync.work.models import EntityBase, EntityType
from worksync.work.queue import Manifest, Proposal, QueueStore, merge_manifest
from worksync.work.repository import WorkIndex
from worksync.work.schema import ACTIVE_ACTION_STATUSES, detect_type, link_target
from worksync.work.similarity import score, title_tokens

MANIFEST_REL = Path("duplicates") / "manifest.json"
DUPLICATE_THRESHOLD = 0.55
PROJECT_BONUS = 0.15
OWNER_BONUS = 0.10
TERM_BONUS = 0.05
TERM_BONUS_CAP = 0.15
PAIR_ID_LENGTH = 16


class DuplicatesError(ValueError):
    """Raised when a duplicate-queue review action cannot be applied."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class PairEvidence:
    """The deterministic evidence that linked two action notes."""

    score: float
    shared_project: bool
    shared_owner: bool
    shared_terms: tuple[str, ...]
    reasons: tuple[str, ...]


def pair_evidence(left: EntityBase, right: EntityBase) -> PairEvidence:
    """Return the similarity score and human-readable reasons for one pair."""
    base = score(left.title, right.title)
    left_project, right_project = (
        link_target(getattr(left, "project", "") or ""),
        link_target(getattr(right, "project", "") or ""),
    )
    shared_project = bool(left_project) and left_project == right_project
    left_owners = {link_target(owner) for owner in getattr(left, "owners", ())}
    right_owners = {link_target(owner) for owner in getattr(right, "owners", ())}
    shared_owner = bool(left_owners & right_owners)
    shared_terms = tuple(sorted(title_tokens(left.title) & title_tokens(right.title)))

    bonus = (PROJECT_BONUS if shared_project else 0.0) + (OWNER_BONUS if shared_owner else 0.0)
    bonus += min(TERM_BONUS * len(shared_terms), TERM_BONUS_CAP)

    reasons = [f"title similarity {base:.2f}"]
    if shared_project:
        reasons.append("shared project")
    if shared_owner:
        reasons.append("shared owner")
    if shared_terms:
        reasons.append("shared terms: " + ", ".join(shared_terms))
    return PairEvidence(
        score=round(min(1.0, base + bonus), 4),
        shared_project=shared_project,
        shared_owner=shared_owner,
        shared_terms=shared_terms,
        reasons=tuple(reasons),
    )


def discover_duplicates(vault: str | Path, index: WorkIndex) -> tuple[Proposal, ...]:
    """Return one pending proposal per likely duplicate pair among active actions."""
    vault_root = Path(vault).expanduser().resolve()
    actions = [
        entity for entity in index.view_entities(EntityType.ACTION.value) if entity.status in ACTIVE_ACTION_STATUSES
    ]
    proposals: list[Proposal] = []
    for index_left in range(len(actions)):
        for index_right in range(index_left + 1, len(actions)):
            left, right = actions[index_left], actions[index_right]
            evidence = pair_evidence(left, right)
            if evidence.score < DUPLICATE_THRESHOLD:
                continue
            canonical, duplicate = _canonical_choice(left, right)
            proposals.append(_proposal(vault_root, canonical, duplicate, evidence))
    return tuple(sorted(proposals, key=lambda proposal: (-proposal.confidence, proposal.id)))


def scan(vault: str | Path, runtime: str | Path, *, today: date | None = None, dry_run: bool = False) -> Manifest:
    """Detect duplicate pairs and persist the merged manifest with a precondition."""
    del today  # detection is date-independent; accepted for CLI symmetry
    index = WorkIndex.from_vault(vault)
    fresh = discover_duplicates(vault, index)
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


def dismiss(
    runtime: str | Path,
    proposal_id: str,
    *,
    reviewer: str,
    reason: str,
    dry_run: bool = False,
) -> Manifest:
    """Mark one pair dismissed with a named reviewer and reason."""
    if not str(reviewer).strip():
        raise DuplicatesError("missing_reviewer", "A dismissal requires a named reviewer.")
    if not str(reason).strip():
        raise DuplicatesError("missing_reason", "A dismissal requires a human-readable reason.")
    store = QueueStore(runtime, MANIFEST_REL)
    loaded = store.load_with_hash()
    if loaded is None:
        raise DuplicatesError("no_manifest", "No duplicates manifest; run 'worksync duplicates scan' first.")
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
        raise DuplicatesError("unknown_proposal", f"No proposal with id: {proposal_id}", affected=(proposal_id,))

    new_manifest = manifest.with_proposals(tuple(updated))
    if not dry_run:
        store.save(new_manifest, expected=expected, expected_absent=False)
    return new_manifest


def pair_id_for(left_path: str, right_path: str) -> str:
    """Return the stable, path-derived id for a pair (stable across rescans only)."""
    return hashlib.sha256("|".join(sorted([left_path, right_path])).encode("utf-8")).hexdigest()[:PAIR_ID_LENGTH]


def _proposal(vault_root: Path, canonical: EntityBase, duplicate: EntityBase, evidence: PairEvidence) -> Proposal:
    duplicate_sha = sha256_file(vault_root / duplicate.path)
    canonical_sha = sha256_file(vault_root / canonical.path)
    return Proposal(
        id=pair_id_for(canonical.path, duplicate.path),
        action="merge",
        source_path=duplicate.path,
        source_sha256=duplicate_sha,
        target_path=canonical.path,
        target_sha256=canonical_sha,
        basis_sha256=_basis(canonical.path, canonical_sha, duplicate.path, duplicate_sha),
        fields={
            "canonical_title": canonical.title,
            "duplicate_title": duplicate.title,
            "similarity": f"{evidence.score:.4f}",
        },
        confidence=evidence.score,
        provenance=evidence.reasons,
    )


def _basis(left_path: str, left_sha: str, right_path: str, right_sha: str) -> str:
    payload = sorted([f"{left_path}:{left_sha}", f"{right_path}:{right_sha}"])
    return hashlib.sha256("|".join(payload).encode("utf-8")).hexdigest()


def _scan_token(vault: str | Path, index: WorkIndex) -> str:
    vault_root = Path(vault).expanduser().resolve()
    payload = sorted(
        (entity.path, sha256_file(vault_root / entity.path))
        for entity in index.view_entities(EntityType.ACTION.value)
        if entity.status in ACTIVE_ACTION_STATUSES
    )
    return hashlib.sha256("|".join(f"{path}:{digest}" for path, digest in payload).encode("utf-8")).hexdigest()


def _canonical_choice(left: EntityBase, right: EntityBase) -> tuple[EntityBase, EntityBase]:
    """Return ``(canonical, duplicate)``: the older, more-established note survives."""
    if _better(left, right):
        return left, right
    return right, left


def _better(candidate: EntityBase, other: EntityBase) -> bool:
    candidate_meta, other_meta = _metadata_count(candidate), _metadata_count(other)
    if candidate_meta != other_meta:
        return candidate_meta > other_meta
    candidate_created, other_created = _created(candidate), _created(other)
    if candidate_created != other_created:
        return candidate_created < other_created
    return candidate.path < other.path


def _metadata_count(entity: EntityBase) -> int:
    raw = entity.raw or {}
    return sum(1 for key in ("owners", "project", "priority", "due") if raw.get(key))


def _created(entity: EntityBase) -> str:
    return str((entity.raw or {}).get("created") or "9999-99-99")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


RESOLUTIONS = ("merge", "redirect")


@dataclass(frozen=True)
class ApplyResult:
    """The visible outcome of applying a reviewed batch of duplicate resolutions."""

    committed: bool
    journal: Path
    changes: tuple[dict, ...]
    applied: tuple[str, ...]


@dataclass(frozen=True)
class _Note:
    relative: str
    content: str
    title: str
    frontmatter: dict
    sha: str


def load_manifest(runtime: str | Path) -> Manifest | None:
    """Load the duplicates manifest, or ``None`` when absent."""
    return QueueStore(runtime, MANIFEST_REL).load()


def manifest_path(runtime: str | Path) -> Path:
    """Return the duplicates manifest path under the staging zone."""
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
    """Apply the selected pending pairs as one transaction through the gateway."""
    if not str(reviewer).strip():
        raise DuplicatesError("missing_reviewer", "An apply requires a named reviewer.")
    if not str(reason).strip():
        raise DuplicatesError("missing_reason", "An apply requires a human-readable reason.")
    store = QueueStore(runtime, MANIFEST_REL)
    loaded = store.load_with_hash()
    if loaded is None:
        raise DuplicatesError("no_manifest", "No duplicates manifest; run 'worksync duplicates scan' first.")
    manifest, manifest_hash = loaded
    wanted = set(ids) if ids is not None else None
    selected = tuple(
        proposal
        for proposal in manifest.proposals
        if proposal.status == "pending" and (wanted is None or proposal.id in wanted)
    )
    if not selected:
        raise DuplicatesError("no_proposals", "No pending pairs were selected.")

    when = today or date.today()
    vault_root = Path(vault).expanduser().resolve()
    ops: list[FileOp] = []
    resolutions: list[str] = []
    for proposal in selected:
        override = (overrides or {}).get(proposal.id) or {}
        if not isinstance(override, dict):
            raise DuplicatesError(
                "invalid_override", f"Override for {proposal.id} must be an object.", affected=(proposal.id,)
            )
        pair_ops, resolution = _pair_ops(vault_root, proposal, override, when=when, reviewer=reviewer, reason=reason)
        ops.extend(pair_ops)
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

    verb = "merge" if "merge" in resolutions else "redirect"
    changeset = ChangeSet(verb, tuple(ops), reviewer=str(reviewer).strip(), reason=str(reason).strip())
    result: CommitResult = commit(changeset, write_zones(vault_root, runtime), confirmed=confirmed)
    return ApplyResult(
        committed=result.committed,
        journal=result.journal,
        changes=result.changes,
        applied=tuple(proposal.id for proposal in selected),
    )


def _pair_ops(
    vault_root: Path, proposal: Proposal, override: dict, *, when: date, reviewer: str, reason: str
) -> tuple[list[FileOp], str]:
    resolution = str(override.get("resolution") or proposal.action or "merge").strip().casefold()
    if resolution not in RESOLUTIONS:
        raise DuplicatesError(
            "unsupported_resolution", f"Unsupported resolution: {resolution}", affected=(proposal.id,)
        )
    canonical_path, duplicate_path = _sides(proposal, override)
    expected = {proposal.target_path: proposal.target_sha256, proposal.source_path: proposal.source_sha256}
    canonical = _load(vault_root, canonical_path, expected.get(canonical_path), proposal.id)
    duplicate = _load(vault_root, duplicate_path, expected.get(duplicate_path), proposal.id)

    ops: list[FileOp] = []
    if resolution == "merge":
        ops.append(
            FileOp(
                "update",
                Path(canonical_path),
                "trusted",
                content=merged_content(canonical.content, duplicate.content),
                expected=canonical.sha,
            )
        )
    ops.append(
        FileOp(
            "update",
            Path(duplicate_path),
            "trusted",
            content=redirect_content(
                duplicate.content,
                duplicate.frontmatter,
                canonical.title,
                when=when.isoformat(),
                reviewer=reviewer,
                reason=reason,
            ),
            expected=duplicate.sha,
        )
    )
    return ops, resolution


def _sides(proposal: Proposal, override: dict) -> tuple[str, str]:
    canonical = str(override.get("canonical") or proposal.target_path or "").strip()
    if canonical == proposal.source_path:
        return proposal.source_path, proposal.target_path or ""
    if canonical == proposal.target_path:
        return proposal.target_path or "", proposal.source_path
    raise DuplicatesError(
        "invalid_target", f"Canonical override must name one of the pair: {canonical}", affected=(canonical,)
    )


def _load(vault_root: Path, relative: str, expected: str | None, proposal_id: str) -> _Note:
    if not relative:
        raise DuplicatesError("missing_target", f"Pair is missing a side: {proposal_id}", affected=(proposal_id,))
    try:
        target = ensure_under(vault_root, vault_root / relative)
    except PathSafetyError as exc:
        raise DuplicatesError("invalid_source", str(exc), affected=(relative,)) from exc
    if not target.is_file():
        raise DuplicatesError("missing_source", f"Note not found: {relative}", affected=(relative,))
    current = sha256_file(target)
    if expected and current != expected:
        raise DuplicatesError("stale_source", f"Note changed since the scan: {relative}", affected=(relative,))
    record = parse_note(target, vault_root)
    if detect_type(record.frontmatter.get("type")) != EntityType.ACTION.value:
        raise DuplicatesError("not_action", f"Target is not an action note: {relative}", affected=(relative,))
    return _Note(
        relative=relative, content=record.content, title=record.title, frontmatter=record.frontmatter, sha=current
    )


def _op_dict(op: FileOp) -> dict:
    return {
        "kind": op.kind,
        "zone": op.zone,
        "path": str(op.path),
        "destination": str(op.destination) if op.destination else None,
        "before": None,
        "after": None,
    }
