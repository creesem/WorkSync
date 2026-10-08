"""Ingest: turn raw sources into reviewable proposals and apply them safely.

One pipeline per concern: discover sources, enrich proposals, review the manifest, and
apply a reviewed batch through the single mutation gateway. Imports no ``context``.
"""

from __future__ import annotations

from worksync.ingest.apply import ApplyResult, apply, dismiss
from worksync.ingest.discover import (
    DEFAULT_INBOX,
    DEFAULT_ROUGH_NOTES,
    IngestError,
    IngestRoots,
    Source,
    discover_sources,
    resolve_roots,
)
from worksync.ingest.enrich import Suggester, enrich
from worksync.ingest.imports import ImportResult, import_note
from worksync.ingest.manifest import (
    Manifest,
    load_manifest,
    manifest_path,
    manifest_sha256,
    save_manifest,
)
from worksync.ingest.proposal import ACTION_KINDS, PROPOSAL_STATUSES, Proposal
from worksync.ingest.service import merge_manifest, scan, scan_token

__all__ = [
    "ACTION_KINDS",
    "DEFAULT_INBOX",
    "DEFAULT_ROUGH_NOTES",
    "PROPOSAL_STATUSES",
    "ApplyResult",
    "ImportResult",
    "IngestError",
    "IngestRoots",
    "Manifest",
    "Proposal",
    "Source",
    "Suggester",
    "apply",
    "discover_sources",
    "dismiss",
    "enrich",
    "import_note",
    "load_manifest",
    "manifest_path",
    "manifest_sha256",
    "merge_manifest",
    "resolve_roots",
    "save_manifest",
    "scan",
    "scan_token",
]
