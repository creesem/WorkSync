"""Apply reviewed captures as ordinary notes in the ingest inbox.

Capture staging lives in :mod:`worksync.work.capture`; this module owns the apply because it
resolves the ingest roots and writes the same kind of raw source note the ingest scan consumes.
Keeping it in ``ingest`` preserves the package layer direction: ``work`` never imports
``ingest``.
"""

from __future__ import annotations

from pathlib import Path

from worksync.core.paths import ensure_under, unique_target
from worksync.ingest.discover import resolve_roots
from worksync.safety.models import FileOp
from worksync.work.capture import CAPTURE_REL
from worksync.work.queue import ApplyResult, Proposal, QueueError, QueueStore, apply_proposals


def _note_title(text: str) -> str:
    """Derive a note title from the first non-empty line, without changing the text."""
    for line in text.splitlines():
        candidate = line.strip().lstrip("#").strip()
        if candidate:
            return candidate[:80]
    return "Captured note"


def capture_apply(
    vault_root: str | Path,
    runtime_root: str | Path,
    *,
    reviewer: str,
    reason: str,
    ids: tuple[str, ...] | None = None,
    confirmed: bool = False,
    inbox_path: str | None = None,
    dry_run: bool = False,
) -> ApplyResult:
    """Apply reviewed captures as raw notes in the configured ingest inbox.

    The capture text becomes a plain note under the same inbox root the ingest scan reads, so
    the existing enrichment/classification runs on the next scan. The note create and the
    manifest decision commit together through the canonical gateway; an existing file is never
    overwritten.
    """
    vault = Path(vault_root).expanduser().resolve()
    roots = resolve_roots(vault, inbox_path=inbox_path)
    inbox = ensure_under(vault, roots.inbox)

    def build_ops(proposal: Proposal, override: dict) -> tuple[list[FileOp], str]:
        text = str(override.get("text") or proposal.fields.get("text") or "").strip()
        if not text:
            raise QueueError("invalid_source", f"Capture {proposal.id} has no text.", affected=(proposal.id,))
        title = _note_title(text)
        target = unique_target(inbox, f"{title}.md")
        content = text if text.endswith("\n") else text + "\n"
        return (
            [FileOp("create", target.relative_to(vault), "trusted", content=content)],
            "capture",
        )

    return apply_proposals(
        QueueStore(runtime_root, CAPTURE_REL),
        vault_root=vault,
        reviewer=reviewer,
        reason=reason,
        ids=ids,
        overrides=None,
        confirmed=confirmed,
        dry_run=dry_run,
        error=QueueError,
        no_manifest="No capture queue; capture something first.",
        empty_selection="No pending captures were selected.",
        build_ops=build_ops,
        verb=lambda resolutions: "apply_capture",
    )
