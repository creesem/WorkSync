"""The mutation gateway's public data model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CANONICAL_ZONES = frozenset({"trusted"})
DERIVED_ZONES = frozenset({"staging", "ingest", "views", "generated", "runtime"})
CONFIRM_VERBS = frozenset({"drop", "merge", "redirect", "archive", "supersede", "reassign", "reclassify"})


class MutationError(RuntimeError):
    """Raised when a change set cannot be applied coherently; nothing partial survives."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class FileOp:
    """One ordered file operation in a change set."""

    kind: str
    path: Path
    zone: str
    content: str | None = None
    destination: Path | None = None
    expected: str | None = None


@dataclass(frozen=True)
class ChangeSet:
    """A named group of file operations the gateway applies as one transaction."""

    verb: str
    ops: tuple[FileOp, ...]
    reviewer: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CommitResult:
    """The visible outcome of a committed transaction."""

    committed: bool
    journal: Path
    changes: tuple[dict, ...]
