"""Load and validate one canonical action note for a review apply.

The review-queue primitive (:mod:`worksync.work.queue`) owns review and remembering and
holds no domain detection. This module owns the one domain-coupled read a queue apply
needs: loading a note by relative path, verifying the source-hash precondition, and
confirming the note is an ``action`` before any canonical operation is built. The failure
vocabulary stays with the caller via the injected ``error`` type.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import parse_note
from worksync.safety.files import sha256_file
from worksync.work.models import EntityType
from worksync.work.queue import QueueError
from worksync.work.schema import detect_type


@dataclass(frozen=True)
class Note:
    """One loaded, hash-verified action note ready for a resolution."""

    relative: str
    content: str
    title: str
    frontmatter: dict
    sha: str


def load_action_note(
    vault_root: Path,
    relative: str,
    expected: str | None,
    *,
    proposal_id: str,
    error: type[QueueError] = QueueError,
    missing_message: str | None = None,
) -> Note:
    """Load, hash-check, and type-check one action note, failing closed at every step."""
    if not relative:
        message = missing_message or f"Note is missing a path: {proposal_id}"
        raise error("missing_target", message, affected=(proposal_id,))
    try:
        target = ensure_under(vault_root, vault_root / relative)
    except PathSafetyError as exc:
        raise error("invalid_source", str(exc), affected=(relative,)) from exc
    if not target.is_file():
        raise error("missing_source", f"Note not found: {relative}", affected=(relative,))
    current = sha256_file(target)
    if expected and current != expected:
        raise error("stale_source", f"Note changed since the scan: {relative}", affected=(relative,))
    record = parse_note(target, vault_root)
    if detect_type(record.frontmatter.get("type")) != EntityType.ACTION.value:
        raise error("not_action", f"Target is not an action note: {relative}", affected=(relative,))
    return Note(
        relative=relative, content=record.content, title=record.title, frontmatter=record.frontmatter, sha=current
    )
