"""Persistence for the ingest proposal manifest.

The manifest lives in the staging derived zone and is written with a stale-state
precondition, so a first-create race and a concurrent update both fail closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from worksync.ingest.proposal import Proposal
from worksync.safety import derived
from worksync.safety.files import sha256_file
from worksync.safety.zones import staging_root

MANIFEST_REL = Path("ingest") / "manifest.json"
MANIFEST_VERSION = 1


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


def manifest_path(runtime_root: str | Path) -> Path:
    """Return the manifest path under the staging derived zone."""
    return staging_root(runtime_root) / MANIFEST_REL


def manifest_sha256(runtime_root: str | Path) -> str | None:
    """Return the manifest's current content hash, or ``None`` when absent."""
    path = manifest_path(runtime_root)
    return sha256_file(path) if path.is_file() else None


def load_manifest(runtime_root: str | Path) -> Manifest | None:
    """Load the manifest, or ``None`` when it is absent or unreadable."""
    path = manifest_path(runtime_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Manifest.from_dict(data) if isinstance(data, dict) else None


def save_manifest(
    runtime_root: str | Path,
    manifest: Manifest,
    *,
    expected: str | None = None,
    expected_absent: bool = False,
) -> Path:
    """Write the manifest with a stale-state precondition; a mismatch fails closed."""
    return derived.write_text(
        staging_root(runtime_root),
        MANIFEST_REL,
        render_manifest(manifest),
        expected=expected,
        expected_absent=expected_absent,
    )


def render_manifest(manifest: Manifest) -> str:
    """Return the exact manifest bytes as text, shared by scan and apply."""
    return json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
