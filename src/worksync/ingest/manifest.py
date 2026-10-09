"""Persistence for the ingest proposal manifest.

The guarded, stale-safe store lives in :mod:`worksync.work.queue`; ingest pins its
manifest to ``ingest/manifest.json`` under the staging derived zone and re-exports the
store's behavior unchanged.
"""

from __future__ import annotations

from pathlib import Path

from worksync.work.queue import (
    MANIFEST_VERSION,
    Manifest,
    QueueStore,
    render_manifest,
)

MANIFEST_REL = Path("ingest") / "manifest.json"

__all__ = [
    "MANIFEST_REL",
    "MANIFEST_VERSION",
    "Manifest",
    "load_manifest",
    "load_manifest_with_hash",
    "manifest_path",
    "manifest_sha256",
    "render_manifest",
    "save_manifest",
]


def _store(runtime_root: str | Path) -> QueueStore:
    return QueueStore(runtime_root, MANIFEST_REL)


def manifest_path(runtime_root: str | Path) -> Path:
    """Return the manifest path under the staging derived zone."""
    return _store(runtime_root).path()


def manifest_sha256(runtime_root: str | Path) -> str | None:
    """Return the manifest's current content hash, or ``None`` when absent."""
    return _store(runtime_root).sha256()


def load_manifest(runtime_root: str | Path) -> Manifest | None:
    """Load the manifest, or ``None`` when it is absent or unreadable."""
    return _store(runtime_root).load()


def load_manifest_with_hash(runtime_root: str | Path) -> tuple[Manifest, str] | None:
    """Load the manifest and the hash of the exact bytes read."""
    return _store(runtime_root).load_with_hash()


def save_manifest(
    runtime_root: str | Path,
    manifest: Manifest,
    *,
    expected: str | None = None,
    expected_absent: bool = False,
) -> Path:
    """Write the manifest with a stale-state precondition; a mismatch fails closed."""
    return _store(runtime_root).save(manifest, expected=expected, expected_absent=expected_absent)
