"""Transcript and sidecar file helpers.

A transcript is a plain-text ``Speaker | mm:ss`` rendering of the Krisp segments; its
sidecar is the raw Krisp payload stored beside it as ``<stem>.krisp.json``. Both helpers
require the exact transcript file and containment inside the configured inbox, so a moved
or missing source is never written beside: the failure mode the legacy pull had.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from worksync.core.names import safe_name
from worksync.core.paths import PathSafetyError, ensure_under
from worksync.ingest.discover import IngestError
from worksync.ingest.krisp.client import KrispMeeting
from worksync.safety import derived

SIDECAR_SUFFIX = ".krisp.json"
PROCESSED_DIRNAME = "Processed"


def parse_iso_prefix(value: object) -> str | None:
    """Return the ISO date in the first ten characters of *value*, or ``None``."""
    text = str(value or "").strip()
    if len(text) >= 10:
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            pass
    return None


def load_json(path: str | Path) -> Any:
    """Read a UTF-8 (BOM-tolerant) JSON file, or ``None`` when it is absent or invalid."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def format_transcript(segments: tuple[dict[str, Any], ...]) -> str:
    """Render Krisp segments as a ``Speaker | mm:ss`` transcript."""
    lines: list[str] = []
    for segment in segments:
        speaker = str(segment.get("speaker") or "Speaker").strip() or "Speaker"
        lines.append(f"{speaker} | {_mmss(segment.get('start'))}")
        text = str(segment.get("text") or "").strip()
        if text:
            lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def transcript_filename(meeting: KrispMeeting, *, today: date | None = None) -> str:
    """Return the ISO-dated, id-suffixed transcript filename."""
    date_part = _date_part(meeting.started_at, today=today)
    title = safe_name(meeting.title, fallback="meeting")
    return f"{date_part} - {title} [{_id8(meeting.meeting_id)}].txt"


def sidecar_path(transcript_path: str | Path) -> Path:
    """Return the sidecar path for a transcript path."""
    return Path(transcript_path).with_suffix(SIDECAR_SUFFIX)


def sidecar_payload(meeting: KrispMeeting) -> dict[str, Any]:
    """Return the sidecar mapping for a meeting."""
    return {
        "meeting_id": meeting.meeting_id,
        "title": meeting.title,
        "started_at": meeting.started_at,
        "duration_seconds": meeting.duration_seconds,
        "source": meeting.source,
        "tags": list(meeting.tags),
        "speakers": [dict(item) for item in meeting.speakers],
        "segments": [dict(item) for item in meeting.segments],
        "notes": dict(meeting.notes),
    }


def write_sidecar(inbox: str | Path, transcript_path: str | Path, payload: dict[str, Any]) -> Path:
    """Write a sidecar beside an existing transcript, refusing a missing/foreign source."""
    resolved = require_transcript(inbox, transcript_path)
    sidecar = sidecar_path(resolved)
    content = json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n"
    return derived.write_text(_inbox_root(inbox), sidecar, content, expected_absent=True)


def read_sidecar(inbox: str | Path, transcript_path: str | Path) -> dict[str, Any] | None:
    """Read the sidecar beside an existing transcript, or ``None`` when it is absent."""
    resolved = require_transcript(inbox, transcript_path)
    data = load_json(sidecar_path(resolved))
    return data if isinstance(data, dict) else None


def _inbox_root(inbox: str | Path) -> Path:
    return Path(inbox).expanduser().resolve()


def require_transcript(inbox: str | Path, transcript_path: str | Path) -> Path:
    """Resolve a transcript inside *inbox*, requiring the exact file to exist."""
    root = _inbox_root(inbox)
    candidate = Path(transcript_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = ensure_under(root, candidate)
    except PathSafetyError as exc:
        raise IngestError("invalid_source", str(exc), affected=(str(transcript_path),)) from exc
    if not resolved.is_file():
        raise IngestError("missing_source", f"Transcript not found: {resolved}", affected=(str(resolved),))
    return resolved


def require_inbox_under(runtime: str | Path, inbox: str | Path) -> Path:
    """Resolve *inbox* and require it to stay inside the runtime root."""
    runtime_root = Path(runtime).expanduser().resolve()
    inbox_root = Path(inbox).expanduser().resolve()
    try:
        return ensure_under(runtime_root, inbox_root)
    except PathSafetyError as exc:
        raise IngestError("invalid_root", f"Krisp inbox must be inside the runtime root: {inbox_root}") from exc


def _date_part(started_at: str, *, today: date | None) -> str:
    return parse_iso_prefix(started_at) or (today or date.today()).isoformat()


def _id8(meeting_id: str) -> str:
    cleaned = "".join(char for char in str(meeting_id) if char.isalnum())
    return (cleaned or "unknown")[:8]


def _mmss(value: object) -> str:
    try:
        total = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        total = 0
    total = max(total, 0)
    return f"{total // 60}:{total % 60:02d}"
