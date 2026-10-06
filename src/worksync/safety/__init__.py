"""safety — the single mutation gateway: preconditions, backups, rollback, journal."""

from __future__ import annotations

from worksync.safety.activity import activity_path, append_event, list_events
from worksync.safety.gateway import commit, recover
from worksync.safety.models import ChangeSet, CommitResult, FileOp, MutationError

__all__ = [
    "ChangeSet",
    "CommitResult",
    "FileOp",
    "MutationError",
    "activity_path",
    "append_event",
    "commit",
    "list_events",
    "recover",
]
