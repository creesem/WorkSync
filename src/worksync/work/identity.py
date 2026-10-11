"""Detect and review duplicate person pairs — the Person identity foundation.

Detection is deterministic: active ``person`` notes are scored pairwise with the shared
similarity scorer plus evidence bonuses for an exact normalized name, a shared alias, and a
shared team. A match only ever creates a proposal; nothing is applied without a human
review. The queue is persisted through :mod:`worksync.work.queue`, so this module inherits
the manifest-as-ledger, basis fingerprint, decision memory, and stale-safe persistence, and
imports no ``context``.

Merge *apply* is deliberately not here: a person merge must resolve every conflicting field
and rewrite indexed references, which is the merge planner's job (WP-04). This module only
detects, remembers a dismissal, and proposes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from worksync.safety.files import sha256_file
from worksync.work.models import EntityBase, EntityType
from worksync.work.queue import (
    Manifest,
    Proposal,
    QueueError,
    QueueStore,
    content_scan_token,
    scan_manifest,
)
from worksync.work.repository import WorkIndex
from worksync.work.schema import normalize_target
from worksync.work.similarity import score

MANIFEST_REL = Path("identity") / "manifest.json"
DUPLICATE_THRESHOLD = 0.60
NAME_EXACT_BONUS = 0.30
ALIAS_BONUS = 0.20
TEAM_BONUS = 0.05
PAIR_ID_LENGTH = 16
RULESET_VERSION = 1
PERSON_ID_PREFIX = "person-dup"


class IdentityError(QueueError):
    """Raised when a person-identity queue review action cannot be applied."""


@dataclass(frozen=True)
class PersonPairEvidence:
    """The deterministic, explainable evidence that linked two person notes."""

    score: float
    exact_name: bool
    shared_team: bool
    shared_aliases: tuple[str, ...]
    reasons: tuple[str, ...]


def person_pair_evidence(left: EntityBase, right: EntityBase) -> PersonPairEvidence:
    """Return the similarity score and human-readable reasons for one person pair."""
    base = score(left.title, right.title)
    left_name, right_name = normalize_target(left.title), normalize_target(right.title)
    exact_name = bool(left_name) and left_name == right_name
    shared_team = bool(getattr(left, "team", None)) and normalize_target(left.team) == normalize_target(right.team)
    shared_aliases = _alias_overlap(left, right)

    bonus = NAME_EXACT_BONUS if exact_name else 0.0
    bonus += TEAM_BONUS if shared_team else 0.0
    bonus += ALIAS_BONUS if shared_aliases else 0.0

    reasons = [f"name similarity {base:.2f}"]
    if exact_name:
        reasons.append("exact name match")
    if shared_aliases:
        reasons.append("shared alias: " + ", ".join(shared_aliases))
    if shared_team:
        reasons.append("same team")
    return PersonPairEvidence(
        score=round(min(1.0, base + bonus), 4),
        exact_name=exact_name,
        shared_team=shared_team,
        shared_aliases=shared_aliases,
        reasons=tuple(reasons),
    )


def discover_duplicates(vault: str | Path, index: WorkIndex) -> tuple[Proposal, ...]:
    """Return one pending proposal per likely duplicate pair among active persons."""
    vault_root = Path(vault).expanduser().resolve()
    people = [entity for entity in index.view_entities(EntityType.PERSON.value) if entity.status == "active"]
    proposals: list[Proposal] = []
    for index_left in range(len(people)):
        for index_right in range(index_left + 1, len(people)):
            left, right = people[index_left], people[index_right]
            evidence = person_pair_evidence(left, right)
            if evidence.score < DUPLICATE_THRESHOLD:
                continue
            canonical, duplicate = _canonical_choice(left, right)
            proposals.append(_proposal(vault_root, canonical, duplicate, evidence))
    return tuple(sorted(proposals, key=lambda proposal: (-proposal.confidence, proposal.id)))


def scan(vault: str | Path, runtime: str | Path, *, dry_run: bool = False) -> Manifest:
    """Detect duplicate person pairs and persist the merged manifest with a precondition."""
    index = WorkIndex.from_vault(vault)
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
    """Mark one person pair dismissed with a named reviewer and reason."""
    return QueueStore(runtime, MANIFEST_REL).dismiss(
        proposal_id,
        reviewer=reviewer,
        reason=reason,
        error=IdentityError,
        no_manifest="No identity manifest; run 'worksync identity scan' first.",
        dry_run=dry_run,
    )


def load_manifest(runtime: str | Path) -> Manifest | None:
    """Load the identity manifest, or ``None`` when absent."""
    return QueueStore(runtime, MANIFEST_REL).load()


def manifest_path(runtime: str | Path) -> Path:
    """Return the identity manifest path under the staging zone."""
    return QueueStore(runtime, MANIFEST_REL).path()


def _identity_key(entity: EntityBase) -> str:
    """Prefer the stable person_id; fall back to the path for a legacy note without one."""
    return getattr(entity, "person_id", None) or entity.path


def pair_id_for(left: EntityBase, right: EntityBase) -> str:
    """Return the stable, identity-derived id for a person pair."""
    keys = sorted([_identity_key(left), _identity_key(right)])
    digest = hashlib.sha256("|".join(keys).encode("utf-8")).hexdigest()[:PAIR_ID_LENGTH]
    return f"{PERSON_ID_PREFIX}:{digest}"


def person_basis(left: EntityBase, right: EntityBase) -> str:
    """Hash exactly the identity-bearing facts, so a body-only edit never voids a decision."""
    payload = sorted([_fact_json(left), _fact_json(right)])
    payload.append(f"ruleset:{RULESET_VERSION}")
    return hashlib.sha256("|".join(payload).encode("utf-8")).hexdigest()


def _fact_json(entity: EntityBase) -> str:
    facts = {
        "person_id": getattr(entity, "person_id", None) or "",
        "name": normalize_target(entity.title),
        "aliases": sorted(normalize_target(alias) for alias in entity.aliases),
        "role": getattr(entity, "role", None) or "",
        "team": getattr(entity, "team", None) or "",
        "email": getattr(entity, "email", None) or "",
    }
    return json.dumps(facts, sort_keys=True)


def _alias_overlap(left: EntityBase, right: EntityBase) -> tuple[str, ...]:
    left_keys = {normalize_target(alias) for alias in left.aliases} | {normalize_target(left.title)}
    right_keys = {normalize_target(alias) for alias in right.aliases} | {normalize_target(right.title)}
    shared = left_keys & right_keys
    titles = {normalize_target(left.title), normalize_target(right.title)}
    return tuple(sorted(shared - titles - {""}))


def _proposal(vault_root: Path, canonical: EntityBase, duplicate: EntityBase, evidence: PersonPairEvidence) -> Proposal:
    return Proposal(
        id=pair_id_for(canonical, duplicate),
        action="merge",
        source_path=duplicate.path,
        source_sha256=sha256_file(vault_root / duplicate.path),
        target_path=canonical.path,
        target_sha256=sha256_file(vault_root / canonical.path),
        basis_sha256=person_basis(canonical, duplicate),
        fields={
            "canonical_title": canonical.title,
            "duplicate_title": duplicate.title,
            "similarity": f"{evidence.score:.4f}",
        },
        confidence=evidence.score,
        provenance=evidence.reasons,
    )


def _scan_token(vault: str | Path, index: WorkIndex) -> str:
    active = [entity for entity in index.view_entities(EntityType.PERSON.value) if entity.status == "active"]
    return content_scan_token(vault, active)


def _canonical_choice(left: EntityBase, right: EntityBase) -> tuple[EntityBase, EntityBase]:
    """Return ``(canonical, duplicate)``: the older, more-established person survives."""
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
    return sum(1 for key in ("role", "team", "email", "manager", "person_id") if raw.get(key))


def _created(entity: EntityBase) -> str:
    return str((entity.raw or {}).get("created") or "9999-99-99")
