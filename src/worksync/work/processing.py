"""Read-only operational status for the GUI: review queues, Krisp sync, recent activity.

This module is imported by the GUI's read seam, so it must not import ``worksync.safety`` or
any write helper. It reads the runtime manifests and activity log directly and returns only
sanitized operational metadata (no note bodies, no filesystem escalation).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

# Kept in parity with ``work.queue.PROPOSAL_STATUSES`` by a test; importing that module would
# pull the write seam into the read closure.
PROPOSAL_STATUSES = ("pending", "applied", "dismissed", "obsolete", "blocked")

QUEUES: tuple[tuple[str, str], ...] = (
    ("capture", "Capture"),
    ("ingest", "Ingest"),
    ("duplicates", "Duplicates"),
    ("identity", "Identity"),
    ("clarification", "Clarification"),
)

ACTIVITY_KEYS = ("timestamp", "verb", "class", "reviewer", "reason", "result")


def _read_json(path: Path) -> tuple[dict | None, str | None]:
    """Read a runtime JSON record, returning ``(data, error)`` without raising."""
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "unreadable"
    if not isinstance(data, dict):
        return None, "unreadable"
    return data, None


def _queue(runtime: Path, queue_id: str, label: str) -> dict:
    path = runtime / "staging" / queue_id / "manifest.json"
    data, error = _read_json(path)
    counts = {status: 0 for status in PROPOSAL_STATUSES}
    updated_at = None
    if data is not None:
        proposals = data.get("proposals")
        if isinstance(proposals, list):
            for proposal in proposals:
                status = str(proposal.get("status") or "unknown") if isinstance(proposal, dict) else "unknown"
                counts[status] = counts.get(status, 0) + 1
        raw_updated = data.get("updated_at")
        updated_at = raw_updated if isinstance(raw_updated, str) and raw_updated else None
    return {
        "id": queue_id,
        "label": label,
        "pending": counts.get("pending", 0),
        "total": sum(counts.values()),
        "by_status": counts,
        "updated_at": updated_at,
        "error": error,
    }


def _krisp(runtime: Path) -> dict:
    data, error = _read_json(runtime / "krisp" / "sync-status.json")
    if data is None:
        return {
            "last_attempt_at": None,
            "last_success_at": None,
            "failed_count": 0,
            "error": error,
        }
    failed = data.get("failed")
    return {
        "last_attempt_at": data.get("last_attempt_at") if isinstance(data.get("last_attempt_at"), str) else None,
        "last_success_at": data.get("last_success_at") if isinstance(data.get("last_success_at"), str) else None,
        "failed_count": len(failed) if isinstance(failed, list) else 0,
        "error": error,
    }


def _activity(runtime: Path, limit: int) -> list[dict]:
    root = runtime / "activity"
    if not root.is_dir():
        return []
    files = sorted(root.glob("*.jsonl"))
    if not files:
        return []
    try:
        lines = files[-1].read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append({key: event[key] for key in ACTIVITY_KEYS if event.get(key)})
        if len(events) >= limit:
            break
    return events


def processing_status(runtime_root: str | Path, *, activity_limit: int = 8) -> dict:
    """Return the operational status payload for the read seam (never writes)."""
    runtime = Path(runtime_root).expanduser().resolve()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "queues": [_queue(runtime, queue_id, label) for queue_id, label in QUEUES],
        "krisp": _krisp(runtime),
        "activity": _activity(runtime, activity_limit),
    }
