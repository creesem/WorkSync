"""The generic review-queue primitive shared by ingest, duplicates, and clarification.

A *proposal* is one reviewable candidate; a *manifest* is the persisted queue for one
vault scan. This module owns review and remembering only: proposal/manifest shape,
stale-safe guarded persistence, decision-basis invalidation, and merge-on-rescan. It
holds no domain detection logic — no duplicate scoring, no clarification predicates,
and no concern-specific canonical file operations. A domain module supplies the
proposals and its canonical ops, and places this module's manifest-update op in the same
``ChangeSet`` so the decision and the mutation commit as one transaction.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from worksync.safety import derived
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import staging_root, write_zones
from worksync.work.models import EntityBase

PROPOSAL_STATUSES = ("pending", "applied", "dismissed", "obsolete", "blocked")
DECISION_STATUSES = ("dismissed",)
MANIFEST_VERSION = 1


class QueueError(ValueError):
    """Raised when a review-queue action cannot be applied."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class ApplyResult:
    """The visible outcome of applying a reviewed batch through the gateway."""

    committed: bool
    journal: Path
    changes: tuple[dict, ...]
    applied: tuple[str, ...]


@dataclass(frozen=True)
class DecisionEntry:
    """One prior decision recorded when a retained decision is voided."""

    outcome: str
    reason: str
    at: str

    def to_dict(self) -> dict[str, str]:
        return {"outcome": self.outcome, "reason": self.reason, "at": self.at}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionEntry:
        return cls(
            outcome=str(data.get("outcome") or ""),
            reason=str(data.get("reason") or ""),
            at=str(data.get("at") or ""),
        )


@dataclass(frozen=True)
class Proposal:
    """One reviewable candidate for a canonical write, with its decision state."""

    id: str
    action: str
    source_path: str
    source_sha256: str
    fields: dict[str, Any] = field(default_factory=dict)
    target_path: str | None = None
    confidence: float = 0.0
    provenance: tuple[str, ...] = ()
    status: str = "pending"
    reviewer: str | None = None
    reason: str | None = None
    basis_sha256: str = ""
    target_sha256: str | None = None
    decided_at: str | None = None
    decision_history: tuple[DecisionEntry, ...] = ()

    def effective_basis(self) -> str:
        """Return the basis a decision is honored against, falling back to the source hash."""
        return self.basis_sha256 or self.source_sha256

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a stable, JSON-safe mapping; decision fields appear only when set."""
        data: dict[str, Any] = {
            "id": self.id,
            "action": self.action,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "fields": dict(self.fields),
            "target_path": self.target_path,
            "confidence": round(float(self.confidence), 4),
            "provenance": list(self.provenance),
            "status": self.status,
            "reviewer": self.reviewer,
            "reason": self.reason,
        }
        if self.basis_sha256:
            data["basis_sha256"] = self.basis_sha256
        if self.target_sha256:
            data["target_sha256"] = self.target_sha256
        if self.decided_at:
            data["decided_at"] = self.decided_at
        if self.decision_history:
            data["decision_history"] = [entry.to_dict() for entry in self.decision_history]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Proposal:
        """Rebuild a proposal from its serialized mapping."""
        fields = data.get("fields")
        provenance = data.get("provenance")
        history = data.get("decision_history")
        return cls(
            id=str(data.get("id") or ""),
            action=str(data.get("action") or ""),
            source_path=str(data.get("source_path") or ""),
            source_sha256=str(data.get("source_sha256") or ""),
            fields=dict(fields) if isinstance(fields, dict) else {},
            target_path=str(data["target_path"]) if data.get("target_path") else None,
            confidence=float(data.get("confidence") or 0.0),
            provenance=tuple(str(item) for item in provenance) if isinstance(provenance, list) else (),
            status=str(data.get("status") or "pending"),
            reviewer=str(data["reviewer"]) if data.get("reviewer") else None,
            reason=str(data["reason"]) if data.get("reason") else None,
            basis_sha256=str(data.get("basis_sha256") or ""),
            target_sha256=str(data["target_sha256"]) if data.get("target_sha256") else None,
            decided_at=str(data["decided_at"]) if data.get("decided_at") else None,
            decision_history=tuple(DecisionEntry.from_dict(item) for item in history if isinstance(item, dict))
            if isinstance(history, list)
            else (),
        )


@dataclass(frozen=True)
class Manifest:
    """The persisted proposal queue for one vault scan."""

    scan_token: str
    proposals: tuple[Proposal, ...] = ()
    version: int = MANIFEST_VERSION
    updated_at: str = ""

    def to_dict(self) -> dict:
        """Serialize the manifest to a stable, JSON-safe mapping."""
        return {
            "version": self.version,
            "scan_token": self.scan_token,
            "updated_at": self.updated_at,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Manifest:
        """Rebuild a manifest from its serialized mapping."""
        proposals = data.get("proposals")
        return cls(
            scan_token=str(data.get("scan_token") or ""),
            proposals=tuple(Proposal.from_dict(item) for item in proposals if isinstance(item, dict))
            if isinstance(proposals, list)
            else (),
            version=int(data.get("version") or MANIFEST_VERSION),
            updated_at=str(data.get("updated_at") or ""),
        )

    def with_proposals(self, proposals: tuple[Proposal, ...], *, scan_token: str | None = None) -> Manifest:
        """Return a new manifest carrying *proposals* and a fresh timestamp."""
        return replace(
            self,
            proposals=tuple(proposals),
            scan_token=scan_token if scan_token is not None else self.scan_token,
            updated_at=now(),
        )


@dataclass(frozen=True)
class QueueStore:
    """Guarded, stale-safe persistence for one concern's manifest under the staging zone."""

    runtime_root: str | Path
    rel: Path

    def path(self) -> Path:
        """Return the manifest path under the staging derived zone."""
        return staging_root(self.runtime_root) / self.rel

    def sha256(self) -> str | None:
        """Return the manifest's current content hash, or ``None`` when absent."""
        path = self.path()
        return sha256_file(path) if path.is_file() else None

    def load_with_hash(self) -> tuple[Manifest, str] | None:
        """Load the manifest and the hash of the exact bytes read."""
        path = self.path()
        if not path.is_file():
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        digest = hashlib.sha256(raw).hexdigest()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            return Manifest.from_dict(data), digest
        except (ValueError, TypeError):
            # Valid JSON with wrong-typed fields ("version": "not-a-number", a non-numeric
            # "confidence") raises while rebuilding the dataclass. "Absent or unreadable"
            # includes malformed state, so fail closed here rather than at every caller.
            return None

    def load(self) -> Manifest | None:
        """Load the manifest, or ``None`` when it is absent or unreadable."""
        loaded = self.load_with_hash()
        return loaded[0] if loaded is not None else None

    def save(
        self,
        manifest: Manifest,
        *,
        expected: str | None = None,
        expected_absent: bool = False,
    ) -> Path:
        """Write the manifest with a stale-state precondition; a mismatch fails closed."""
        return derived.write_text(
            staging_root(self.runtime_root),
            self.rel,
            render_manifest(manifest),
            expected=expected,
            expected_absent=expected_absent,
        )

    def manifest_op(self, manifest: Manifest, *, expected: str | None) -> FileOp:
        """Return the manifest-update ``FileOp`` for a domain apply's ``ChangeSet``."""
        return FileOp("update", self.rel, "staging", content=render_manifest(manifest), expected=expected)

    def dismiss(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        reason: str,
        error: type[QueueError] = QueueError,
        no_manifest: str = "No review manifest; run the queue scan first.",
        dry_run: bool = False,
    ) -> Manifest:
        """Mark one proposal dismissed with a named reviewer and reason, guarded by hash."""
        if not str(reviewer).strip():
            raise error("missing_reviewer", "A dismissal requires a named reviewer.")
        if not str(reason).strip():
            raise error("missing_reason", "A dismissal requires a human-readable reason.")
        loaded = self.load_with_hash()
        if loaded is None:
            raise error("no_manifest", no_manifest)
        manifest, expected = loaded

        found = False
        updated: list[Proposal] = []
        for proposal in manifest.proposals:
            if proposal.id == proposal_id:
                updated.append(
                    replace(proposal, status="dismissed", reviewer=reviewer, reason=reason, decided_at=now())
                )
                found = True
            else:
                updated.append(proposal)
        if not found:
            raise error("unknown_proposal", f"No proposal with id: {proposal_id}", affected=(proposal_id,))

        new_manifest = manifest.with_proposals(tuple(updated))
        if not dry_run:
            self.save(new_manifest, expected=expected, expected_absent=False)
        return new_manifest


def render_manifest(manifest: Manifest) -> str:
    """Return the exact manifest bytes as text, shared by scan and apply."""
    return json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n"


def merge_manifest(previous: Manifest | None, fresh: tuple[Proposal, ...], *, token: str) -> Manifest:
    """Merge fresh proposals with the previous manifest.

    A retained decision is honored only while its basis is unchanged; a basis change
    voids it back to ``pending`` with a history entry rather than dropping it. A pending
    proposal that was not rediscovered is retired as ``obsolete``.
    """
    previous_by_id = {proposal.id: proposal for proposal in previous.proposals} if previous else {}
    fresh_ids = {proposal.id for proposal in fresh}
    merged: list[Proposal] = []
    for proposal in fresh:
        old = previous_by_id.get(proposal.id)
        if old is not None and old.status in DECISION_STATUSES:
            if old.effective_basis() == proposal.effective_basis():
                merged.append(old)
            else:
                entry = DecisionEntry(outcome=old.status, reason="basis changed", at=now())
                merged.append(replace(proposal, status="pending", decision_history=(*old.decision_history, entry)))
        else:
            merged.append(proposal)
    if previous:
        for old in previous.proposals:
            if old.id not in fresh_ids and old.status == "pending":
                merged.append(replace(old, status="obsolete"))
    base = previous or Manifest(scan_token=token)
    return base.with_proposals(tuple(merged), scan_token=token)


def now() -> str:
    """Return the current UTC timestamp used for manifest and decision records."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def scan_manifest(
    store: QueueStore,
    fresh: tuple[Proposal, ...],
    *,
    token: str,
    dry_run: bool = False,
) -> Manifest:
    """Merge *fresh* proposals with the persisted manifest and save under a precondition."""
    loaded = store.load_with_hash()
    previous = loaded[0] if loaded is not None else None
    manifest = merge_manifest(previous, fresh, token=token)
    if not dry_run:
        store.save(
            manifest,
            expected=loaded[1] if loaded is not None else None,
            expected_absent=loaded is None,
        )
    return manifest


def content_scan_token(vault: str | Path, entities: Iterable[EntityBase]) -> str:
    """Return a stable scan token over the content of *entities* (caller filters)."""
    vault_root = Path(vault).expanduser().resolve()
    payload = sorted((entity.path, sha256_file(vault_root / entity.path)) for entity in entities)
    return hashlib.sha256("|".join(f"{path}:{digest}" for path, digest in payload).encode("utf-8")).hexdigest()


def op_dict(op: FileOp) -> dict:
    """Return the display mapping for one planned file operation."""
    return {
        "kind": op.kind,
        "zone": op.zone,
        "path": str(op.path),
        "destination": str(op.destination) if op.destination else None,
        "before": None,
        "after": None,
    }


def apply_proposals(
    store: QueueStore,
    *,
    vault_root: Path,
    reviewer: str,
    reason: str,
    ids: tuple[str, ...] | None,
    overrides: dict[str, dict] | None,
    confirmed: bool,
    dry_run: bool,
    error: type[QueueError],
    no_manifest: str,
    empty_selection: str,
    build_ops: Callable[[Proposal, dict], tuple[list[FileOp], str]],
    verb: Callable[[tuple[str, ...]], str],
) -> ApplyResult:
    """Apply the selected pending proposals as one transaction through the gateway.

    The caller supplies the per-proposal op builder and the batch verb; this function
    owns selection, manifest marking, the manifest-update op in the same ``ChangeSet``,
    dry-run reporting, and the single commit.
    """
    if not str(reviewer).strip():
        raise error("missing_reviewer", "An apply requires a named reviewer.")
    if not str(reason).strip():
        raise error("missing_reason", "An apply requires a human-readable reason.")
    loaded = store.load_with_hash()
    if loaded is None:
        raise error("no_manifest", no_manifest)
    manifest, manifest_hash = loaded
    wanted = set(ids) if ids is not None else None
    selected = tuple(
        proposal
        for proposal in manifest.proposals
        if proposal.status == "pending" and (wanted is None or proposal.id in wanted)
    )
    if not selected:
        raise error("no_proposals", empty_selection)

    ops: list[FileOp] = []
    resolutions: list[str] = []
    for proposal in selected:
        override = (overrides or {}).get(proposal.id) or {}
        if not isinstance(override, dict):
            raise error("invalid_override", f"Override for {proposal.id} must be an object.", affected=(proposal.id,))
        proposal_ops, resolution = build_ops(proposal, override)
        ops.extend(proposal_ops)
        resolutions.append(resolution)

    selected_ids = {proposal.id for proposal in selected}
    updated = tuple(
        replace(proposal, status="applied", reviewer=reviewer, reason=reason, decided_at=now())
        if proposal.id in selected_ids
        else proposal
        for proposal in manifest.proposals
    )
    ops.append(store.manifest_op(manifest.with_proposals(updated), expected=manifest_hash))

    if dry_run:
        return ApplyResult(
            committed=False,
            journal=Path(),
            changes=tuple(op_dict(op) for op in ops),
            applied=tuple(proposal.id for proposal in selected),
        )

    changeset = ChangeSet(
        verb(tuple(resolutions)), tuple(ops), reviewer=str(reviewer).strip(), reason=str(reason).strip()
    )
    result: CommitResult = commit(changeset, write_zones(vault_root, store.runtime_root), confirmed=confirmed)
    return ApplyResult(
        committed=result.committed,
        journal=result.journal,
        changes=result.changes,
        applied=tuple(proposal.id for proposal in selected),
    )
