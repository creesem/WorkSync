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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from worksync.safety import derived
from worksync.safety.files import sha256_file
from worksync.safety.models import FileOp
from worksync.safety.zones import staging_root

PROPOSAL_STATUSES = ("pending", "applied", "dismissed", "obsolete", "blocked")
DECISION_STATUSES = ("dismissed",)
MANIFEST_VERSION = 1


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
            updated_at=_now(),
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
        return Manifest.from_dict(data), digest

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
                entry = DecisionEntry(outcome=old.status, reason="basis changed", at=_now())
                merged.append(replace(proposal, status="pending", decision_history=(*old.decision_history, entry)))
        else:
            merged.append(proposal)
    if previous:
        for old in previous.proposals:
            if old.id not in fresh_ids and old.status == "pending":
                merged.append(replace(old, status="obsolete"))
    base = previous or Manifest(scan_token=token)
    return base.with_proposals(tuple(merged), scan_token=token)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
