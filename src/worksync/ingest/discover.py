"""Discovery of raw sources for triage.

Sources are read through the single scanner. Roots are configured and validated inside
the vault; a missing required root fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import IndexRecord, parse_note

DEFAULT_INBOX = "7. Task Notes/Inbox"
DEFAULT_ROUGH_NOTES = "1. Rough Notes"


class IngestError(ValueError):
    """Raised when a source root is missing, unsafe, or unusable."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class Source:
    """One discovered raw note, with the root it came from."""

    record: IndexRecord
    origin: str


@dataclass(frozen=True)
class IngestRoots:
    """The resolved inbox and optional rough-notes roots."""

    inbox: Path
    rough_notes: Path | None = None


def resolve_roots(
    vault: str | Path,
    *,
    inbox_path: str | None = None,
    rough_notes_path: str | None = None,
) -> IngestRoots:
    """Resolve the configured roots, requiring the inbox and validating containment."""
    vault_root = Path(vault).expanduser().resolve()
    inbox = _resolve_root(vault_root, inbox_path or DEFAULT_INBOX, required=True)
    assert inbox is not None
    rough = _resolve_root(vault_root, rough_notes_path or DEFAULT_ROUGH_NOTES, required=False)
    return IngestRoots(inbox=inbox, rough_notes=rough)


def _resolve_root(vault_root: Path, relative: str, *, required: bool) -> Path | None:
    try:
        root = ensure_under(vault_root, vault_root / relative)
    except PathSafetyError as exc:
        raise IngestError("invalid_root", str(exc), affected=(relative,)) from exc
    if not root.is_dir():
        if required:
            raise IngestError("missing_root", f"Ingest root not found: {relative}", affected=(relative,))
        return None
    return root


def discover_sources(vault: str | Path, roots: IngestRoots) -> tuple[Source, ...]:
    """Return every markdown source under the configured roots, in deterministic order.

    Files inside an ``Archive`` subfolder are imported originals, not live sources, so
    they are skipped.
    """
    vault_root = Path(vault).expanduser().resolve()
    sources: list[Source] = []
    for origin, root in (("inbox", roots.inbox), ("rough-notes", roots.rough_notes)):
        if root is None:
            continue
        for path in sorted(root.rglob("*.md")):
            if not path.is_file() or _is_archived(path, root):
                continue
            sources.append(Source(record=parse_note(path, vault_root), origin=origin))
    return tuple(sources)


def _is_archived(path: Path, root: Path) -> bool:
    return any(part.casefold() == "archive" for part in path.relative_to(root).parts[:-1])
