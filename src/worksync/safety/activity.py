"""Derived, append-only activity log (JSONL) in the runtime zone.

Best-effort by contract: a log write never fails or masks the underlying action, and
nothing reads the log as authority.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ACTIVITY_DIRNAME = "activity"


def activity_path(runtime_root: str | Path, when: datetime | None = None) -> Path:
    """Return the monthly activity file for *when* (default: now)."""
    when = when or datetime.now(UTC)
    return Path(runtime_root) / ACTIVITY_DIRNAME / f"{when:%Y-%m}.jsonl"


def append_event(runtime_root: str | Path, event: dict, *, when: datetime | None = None) -> bool:
    """Append one event, returning success; never raises."""
    try:
        when = when or datetime.now(UTC)
        path = activity_path(runtime_root, when)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": when.isoformat(timespec="seconds"), **event}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        return False


def list_events(runtime_root: str | Path, *, limit: int | None = None) -> list[dict]:
    """Return recorded events in chronological order, optionally trailing *limit*."""
    root = Path(runtime_root) / ACTIVITY_DIRNAME
    if not root.is_dir():
        return []
    events: list[dict] = []
    for path in sorted(root.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events[-limit:] if limit else events
