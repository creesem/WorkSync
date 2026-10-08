"""The ingest proposal model: one reviewable candidate derived from a raw source.

A proposal is a plain dataclass with stable JSON serialization so the manifest
round-trips. It carries the source path and hash, the proposed canonical fields, the
confidence and human-readable provenance, and its lifecycle status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ACTION_KINDS = ("action", "link-existing", "merge", "drop")
PROPOSAL_STATUSES = ("pending", "applied", "dismissed", "obsolete", "blocked")


@dataclass(frozen=True)
class Proposal:
    """One reviewable candidate for a canonical write."""

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

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a stable, JSON-safe mapping."""
        return {
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Proposal:
        """Rebuild a proposal from its serialized mapping."""
        fields = data.get("fields")
        provenance = data.get("provenance")
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
        )
