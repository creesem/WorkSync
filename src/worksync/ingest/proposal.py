"""The ingest proposal model: one reviewable candidate derived from a raw source.

The generic proposal shape and status vocabulary live in :mod:`worksync.work.queue`;
ingest re-exports them so its public API is unchanged. ``ACTION_KINDS`` is the
ingest-specific set of canonical actions an ingest proposal may take.
"""

from __future__ import annotations

from worksync.work.queue import PROPOSAL_STATUSES, Proposal

ACTION_KINDS = ("action", "link-existing", "merge", "drop")

__all__ = ["ACTION_KINDS", "PROPOSAL_STATUSES", "Proposal"]
