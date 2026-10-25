"""Turn typed text into a pending review-queue proposal.

Capture staging: append a proposal to the capture manifest under the derived staging zone; it
never touches a canonical note. The review/apply path lives in ``worksync.ingest.capture`` and
writes an inbox note for the ingest pipeline to classify.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from worksync.safety.files import sha256_bytes
from worksync.work.queue import Manifest, Proposal, QueueError, QueueStore, merge_manifest

CAPTURE_REL = Path("capture") / "manifest.json"


def capture_text(runtime_root: str | Path, text: str, *, now: str | None = None) -> Manifest:
    """Turn typed text into a pending review-queue proposal (staging zone only)."""
    digest = sha256_bytes(text.encode("utf-8"))
    proposal = Proposal(
        id=digest[:12],
        action="capture",
        source_path="",
        source_sha256=digest,
        fields={"text": text},
        provenance=("capture",),
        status="pending",
    )
    store = QueueStore(runtime_root, CAPTURE_REL)
    # One read, one merge, one guarded write: a capture scan discovers exactly one new
    # proposal, so the existing queue is carried forward (merge_manifest would otherwise
    # retire earlier pending captures as obsolete). A concurrent capture changes the
    # manifest hash and makes this save fail closed rather than drop its proposal.
    loaded = store.load_with_hash()
    if loaded is None and store.path().is_file():
        # The manifest exists but cannot be read or parsed. Treating that as "absent" would
        # fail closed inside the guarded create with a misleading stale-hash retry loop, so
        # report it as its own failure (the GUI transport answers 500, not a retryable 409).
        raise QueueError(
            "corrupt_manifest",
            "The capture queue manifest is unreadable; repair or remove it before capturing.",
            affected=(str(store.path()),),
        )
    previous = loaded[0] if loaded is not None else None
    carried = tuple(item for item in (previous.proposals if previous else ()) if item.id != proposal.id)
    manifest = merge_manifest(previous, (*carried, proposal), token=digest)
    if now is not None:
        manifest = replace(manifest, updated_at=now)
    try:
        store.save(
            manifest,
            expected=loaded[1] if loaded is not None else None,
            expected_absent=loaded is None,
        )
    except RuntimeError as exc:
        # The guarded write fails closed when the manifest changed under us (another tab
        # captured first). Surface it as the queue's own stale-hash failure so the GUI
        # transport can answer 409 instead of leaking a bare RuntimeError.
        raise QueueError(
            "stale_hash",
            "The review queue changed; capture again.",
            affected=(str(store.path()),),
        ) from exc
    except OSError as exc:
        # A staging write can fail on the filesystem itself (full disk, permissions, a locked
        # temp file). Without this the request would drop with a bare traceback; report it as
        # a queue failure so the transport answers 500 with a message.
        raise QueueError(
            "write_failed",
            "The capture queue could not be written; check the runtime root and try again.",
            affected=(str(store.path()),),
        ) from exc
    return manifest


def capture_dismiss(
    runtime_root: str | Path,
    proposal_id: str,
    *,
    reviewer: str,
    reason: str,
) -> Manifest:
    """Dismiss one capture proposal; the manifest is the only write."""
    return QueueStore(runtime_root, CAPTURE_REL).dismiss(
        proposal_id,
        reviewer=reviewer,
        reason=reason,
        error=QueueError,
        no_manifest="No capture queue; capture something first.",
    )
