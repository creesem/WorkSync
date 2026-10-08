"""Ingest: turn raw sources into reviewable proposals and apply them safely.

One pipeline per concern: discover sources, enrich proposals, review the manifest, and
apply a reviewed batch through the single mutation gateway. Imports no ``context``.
"""

from __future__ import annotations

from worksync.ingest.manifest import Manifest, load_manifest, manifest_path, save_manifest
from worksync.ingest.proposal import ACTION_KINDS, PROPOSAL_STATUSES, Proposal

__all__ = [
    "ACTION_KINDS",
    "PROPOSAL_STATUSES",
    "Manifest",
    "Proposal",
    "load_manifest",
    "manifest_path",
    "save_manifest",
]
