"""Ingest orchestration: scan sources into a manifest, then apply a reviewed batch.

Scan is read-only over the vault and writes only the derived manifest. Apply (ticket 03)
commits through the single mutation gateway.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from worksync.ingest.discover import Source, discover_sources, resolve_roots
from worksync.ingest.enrich import enrich
from worksync.ingest.manifest import (
    Manifest,
    load_manifest_with_hash,
    save_manifest,
)
from worksync.ingest.proposal import Proposal
from worksync.work.repository import WorkIndex


def scan(
    vault: str | Path,
    runtime: str | Path,
    *,
    today: date | None = None,
    inbox_path: str | None = None,
    rough_notes_path: str | None = None,
) -> Manifest:
    """Discover and enrich sources, then persist the merged manifest with a precondition."""
    when = today or date.today()
    roots = resolve_roots(vault, inbox_path=inbox_path, rough_notes_path=rough_notes_path)
    sources = discover_sources(vault, roots)
    index = WorkIndex.from_vault(vault)
    fresh = tuple(proposal for source in sources if (proposal := enrich(source, index, today=when)) is not None)
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


def merge_manifest(previous: Manifest | None, fresh: tuple[Proposal, ...], *, token: str) -> Manifest:
    """Merge fresh proposals with the previous manifest.

    A dismissed proposal is retained while its source hash is unchanged; a pending
    proposal that was not rediscovered is retired as ``obsolete``.
    """
    previous_by_id = {proposal.id: proposal for proposal in previous.proposals} if previous else {}
    fresh_ids = {proposal.id for proposal in fresh}
    merged: list[Proposal] = []
    for proposal in fresh:
        old = previous_by_id.get(proposal.id)
        if old is not None and old.status == "dismissed" and old.source_sha256 == proposal.source_sha256:
            merged.append(old)
        else:
            merged.append(proposal)
    if previous:
        for old in previous.proposals:
            if old.id not in fresh_ids and old.status == "pending":
                merged.append(replace(old, status="obsolete"))
    base = previous or Manifest(scan_token=token)
    return base.with_proposals(tuple(merged), scan_token=token)
