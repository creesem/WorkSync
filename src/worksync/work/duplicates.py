"""Detect and review duplicate action pairs.

Detection is deterministic: active ``action`` notes are scored pairwise with the shared
similarity scorer plus evidence bonuses for a shared project, shared owner, and shared
title terms. A match only ever creates a proposal; nothing is applied without a human
confirmation. The queue is persisted through :mod:`worksync.work.queue`, and this module
imports no ``context``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from worksync.safety.files import sha256_file
from worksync.safety.models import FileOp
from worksync.work.consolidate import merged_content, redirect_content
from worksync.work.generation import is_legacy_path, live_index, read_generation
from worksync.work.models import EntityBase, EntityType
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
from worksync.work.schema import ACTIVE_ACTION_STATUSES, link_target
from worksync.work.similarity import score, title_tokens

MANIFEST_REL = Path("duplicates") / "manifest.json"
DUPLICATE_THRESHOLD = 0.55
PROJECT_BONUS = 0.15
OWNER_BONUS = 0.10
TERM_BONUS = 0.05
TERM_BONUS_CAP = 0.15
PAIR_ID_LENGTH = 16


class DuplicatesError(QueueError):
    """Raised when a duplicate-queue review action cannot be applied."""


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
    index = live_index(vault, runtime)
    fresh = discover_duplicates(vault, index)
    return scan_manifest(QueueStore(runtime, MANIFEST_REL), fresh, token=_scan_token(vault, index), dry_run=dry_run)


def dismiss(
    runtime: str | Path,
    proposal_id: str,
    *,
    reviewer: str,
    reason: str,
    dry_run: bool = False,
) -> Manifest:
    """Mark one pair dismissed with a named reviewer and reason."""
    return QueueStore(runtime, MANIFEST_REL).dismiss(
        proposal_id,
        reviewer=reviewer,
        reason=reason,
        error=DuplicatesError,
        no_manifest="No duplicates manifest; run 'worksync duplicates scan' first.",
        dry_run=dry_run,
    )


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
    active = [
        entity for entity in index.view_entities(EntityType.ACTION.value) if entity.status in ACTIVE_ACTION_STATUSES
    ]
    return content_scan_token(vault, active)


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


RESOLUTIONS = ("merge", "redirect")


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
    when = today or date.today()
    vault_root = Path(vault).expanduser().resolve()
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
        error=DuplicatesError,
        no_manifest="No duplicates manifest; run 'worksync duplicates scan' first.",
        empty_selection="No pending pairs were selected.",
        build_ops=lambda proposal, override: _pair_ops(
            vault_root, proposal, override, when=when, reviewer=reviewer, reason=reason
        ),
        verb=_batch_verb,
    )


def _batch_verb(resolutions: tuple[str, ...]) -> str:
    return "merge" if "merge" in resolutions else "redirect"


def _reject_legacy(manifest: Manifest | None, ids: tuple[str, ...] | None, generation) -> None:
    """Refuse to apply a proposal whose either side is frozen legacy work."""
    if manifest is None:
        return
    blocked = tuple(
        proposal.id
        for proposal in manifest.proposals
        if proposal.status == "pending"
        and (ids is None or proposal.id in ids)
        and (is_legacy_path(proposal.source_path, generation) or is_legacy_path(proposal.target_path, generation))
    )
    if blocked:
        raise DuplicatesError(
            "legacy_target",
            "Legacy work cannot be applied: " + ", ".join(blocked),
            affected=blocked,
        )


def _pair_ops(
    vault_root: Path, proposal: Proposal, override: dict, *, when: date, reviewer: str, reason: str
) -> tuple[list[FileOp], str]:
    resolution = str(override.get("resolution") or proposal.action or "merge").strip().casefold()
    if resolution not in RESOLUTIONS:
        raise DuplicatesError(
            "unsupported_resolution", f"Unsupported resolution: {resolution}", affected=(proposal.id,)
        )
    canonical_path, duplicate_path = _pair_sides(proposal, override)
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


def _pair_sides(proposal: Proposal, override: dict) -> tuple[str, str]:
    canonical = str(override.get("canonical") or proposal.target_path or "").strip()
    if canonical == proposal.source_path:
        return proposal.source_path, proposal.target_path or ""
    if canonical == proposal.target_path:
        return proposal.target_path or "", proposal.source_path
    raise DuplicatesError(
        "invalid_target", f"Canonical override must name one of the pair: {canonical}", affected=(canonical,)
    )


def _load(vault_root: Path, relative: str, expected: str | None, proposal_id: str) -> Note:
    return load_action_note(
        vault_root,
        relative,
        expected,
        proposal_id=proposal_id,
        error=DuplicatesError,
        missing_message=f"Pair is missing a side: {proposal_id}",
    )
