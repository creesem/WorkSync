"""Ingest orchestration: scan sources into a manifest, then apply a reviewed batch.

Scan is read-only over the vault and writes only the derived manifest. Apply (ticket 03)
commits through the single mutation gateway.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from worksync.ingest.discover import Source, discover_sources, resolve_roots
from worksync.ingest.enrich import Suggester, enrich
from worksync.ingest.manifest import (
    Manifest,
    load_manifest_with_hash,
    save_manifest,
)
from worksync.work.queue import merge_manifest
from worksync.work.repository import WorkIndex


def scan(
    vault: str | Path,
    runtime: str | Path,
    *,
    today: date | None = None,
    inbox_path: str | None = None,
    rough_notes_path: str | None = None,
    model: Suggester | None = None,
) -> Manifest:
    """Discover and enrich sources, then persist the merged manifest with a precondition."""
    when = today or date.today()
    roots = resolve_roots(vault, inbox_path=inbox_path, rough_notes_path=rough_notes_path)
    sources = discover_sources(vault, roots)
    index = WorkIndex.from_vault(vault)
    fresh = tuple(
        proposal for source in sources if (proposal := enrich(source, index, today=when, model=model)) is not None
    )
    token = scan_token(sources)
    loaded = load_manifest_with_hash(runtime)
    previous = loaded[0] if loaded is not None else None
    manifest = merge_manifest(previous, fresh, token=token)
    save_manifest(
        runtime,
        manifest,
        expected=loaded[1] if loaded is not None else None,
        expected_absent=loaded is None,
    )
    return manifest


def scan_token(sources: tuple[Source, ...]) -> str:
    """Return a stable hash of the discovered source set (path + content hash)."""
    payload = sorted((source.record.path, source.record.content_hash) for source in sources)
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()
