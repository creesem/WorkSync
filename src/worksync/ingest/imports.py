"""Import a rough note into the inbox so capture and triage stay separate.

The import is one gateway transaction: the inbox draft is created first, then the source
is disposition-moved to a dated archive under the rough-notes root. A source is never
unlinked, a same-named inbox note is never overwritten, and a failed create rolls the
whole change back.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from worksync.core.names import safe_name
from worksync.core.paths import PathSafetyError, ensure_under, unique_target
from worksync.ingest.discover import IngestError, resolve_roots
from worksync.inventory.parse import parse_note, split_frontmatter
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones

TITLE_RE = re.compile(r"(?m)^#\s+(.+?)\s*$")


@dataclass(frozen=True)
class ImportResult:
    """The visible outcome of importing one rough note."""

    committed: bool
    journal: Path
    changes: tuple[dict, ...]
    target: str
    archived: str


def import_note(
    vault: str | Path,
    runtime: str | Path,
    *,
    source: str | Path,
    reviewer: str,
    reason: str,
    inbox_path: str | None = None,
    rough_notes_path: str | None = None,
    today: date | None = None,
) -> ImportResult:
    """Import one rough note into the inbox as an untriaged action draft."""
    if not str(reviewer).strip():
        raise IngestError("missing_reviewer", "An import requires a named reviewer.")
    if not str(reason).strip():
        raise IngestError("missing_reason", "An import requires a human-readable reason.")

    when = today or date.today()
    vault_root = Path(vault).expanduser().resolve()
    roots = resolve_roots(vault_root, inbox_path=inbox_path, rough_notes_path=rough_notes_path)
    if roots.rough_notes is None:
        raise IngestError("missing_root", "A rough-notes root is required to import from.")

    source_path = _resolve_source(vault_root, roots.rough_notes, source)
    record = parse_note(source_path, vault_root)
    title = record.headings[0][1] if record.headings else source_path.stem

    target = unique_target(roots.inbox, f"Inbox - {safe_name(title, fallback='untitled')}.md")
    archived = unique_target(roots.rough_notes / "Archive" / when.isoformat(), source_path.name)
    content = _draft(title, record.content, source_path.stem, when=when, reviewer=reviewer, reason=reason)

    changeset = ChangeSet(
        "import",
        (
            FileOp("create", _relative(vault_root, target), "trusted", content=content),
            FileOp(
                "move",
                _relative(vault_root, source_path),
                "trusted",
                destination=_relative(vault_root, archived),
                expected=record.content_hash,
            ),
        ),
        reviewer=str(reviewer).strip(),
        reason=str(reason).strip(),
    )
    result: CommitResult = commit(changeset, write_zones(vault_root, runtime))
    return ImportResult(
        committed=result.committed,
        journal=result.journal,
        changes=result.changes,
        target=_relative(vault_root, target).as_posix(),
        archived=_relative(vault_root, archived).as_posix(),
    )


def _resolve_source(vault_root: Path, rough_root: Path, source: str | Path) -> Path:
    raw = str(source or "").strip()
    if not raw:
        raise IngestError("missing_source", "An import requires a source note.")
    try:
        resolved = ensure_under(vault_root, vault_root / raw)
    except PathSafetyError as exc:
        raise IngestError("invalid_source", str(exc), affected=(raw,)) from exc
    if not resolved.is_file():
        raise IngestError("missing_source", f"Source not found: {raw}", affected=(raw,))
    if not resolved.is_relative_to(rough_root):
        raise IngestError("invalid_source", f"Source is outside the rough-notes root: {raw}", affected=(raw,))
    return resolved


def _draft(title: str, content: str, source_stem: str, *, when: date, reviewer: str, reason: str) -> str:
    body = split_frontmatter(content)[1].strip()
    if not TITLE_RE.search(body):
        body = f"# {title}\n\n{body}".rstrip()
    lines = [
        "---",
        "capture: rough-note",
        f"origin: {json.dumps(f'[[{source_stem}]]')}",
        f"created: {when.isoformat()}",
        f"updated: {when.isoformat()}",
        "revision: 1",
        f"created_by: {json.dumps(str(reviewer).strip())}",
        f"last_action: {json.dumps(str(reason).strip())}",
        "---",
    ]
    return "\n".join(lines) + "\n\n" + body + "\n"


def _relative(vault_root: Path, path: Path) -> Path:
    return path.resolve().relative_to(vault_root)
