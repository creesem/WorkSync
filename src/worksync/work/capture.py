"""Turn typed text into a pending review-queue proposal.

Capture is the one GUI write: it appends a proposal to the capture manifest under the
derived staging zone. It never touches a canonical note and has no apply path yet, so a
captured thought is reviewed through the shared queue like any other proposal.
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
    return manifest
