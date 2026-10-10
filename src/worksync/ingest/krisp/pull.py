"""Pull Krisp meetings into the runtime inbox.

Each new meeting becomes a transcript plus a sidecar; a pull ledger keyed by meeting id
makes a second pull idempotent and records failures for retry. The ledger is source state,
not a decision ledger: the review manifest remains the single decision record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from worksync.core.config import DEFAULT_KRISP_INBOX
from worksync.core.paths import PathSafetyError, ensure_under, unique_target
from worksync.ingest.discover import IngestError
from worksync.ingest.krisp.client import KrispClient
from worksync.ingest.krisp.sidecar import (
    format_transcript,
    load_json,
    sidecar_payload,
    transcript_filename,
    write_sidecar,
)
from worksync.safety import derived
from worksync.safety.files import sha256_bytes

LEDGER_REL = Path("krisp") / "pull-ledger.json"
SYNC_REL = Path("krisp") / "sync-status.json"
LEDGER_VERSION = 1


@dataclass(frozen=True)
class PullResult:
    """The visible outcome of one pull."""

    inbox: str
    pulled: tuple[str, ...]
    skipped: tuple[str, ...]
    empty_transcripts: tuple[str, ...]
    notes_unavailable: tuple[str, ...]
    failed: tuple[dict[str, Any], ...]
    last_success_at: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe summary."""
        return {
            "inbox": self.inbox,
            "pulled": list(self.pulled),
            "skipped": list(self.skipped),
            "empty_transcripts": list(self.empty_transcripts),
            "notes_unavailable": list(self.notes_unavailable),
            "failed": [dict(item) for item in self.failed],
            "last_success_at": self.last_success_at,
        }


def pull(
    runtime: str | Path,
    *,
    client: KrispClient,
    since_days: int,
    inbox: str | Path | None = None,
    today: date | None = None,
    now: datetime | None = None,
) -> PullResult:
    """Fetch recent meetings and write new transcripts + sidecars into the inbox."""
    runtime_root = Path(runtime).expanduser().resolve()
    inbox_root = Path(inbox).expanduser().resolve() if inbox is not None else (runtime_root / DEFAULT_KRISP_INBOX)
    try:
        inbox_root = ensure_under(runtime_root, inbox_root)
    except PathSafetyError as exc:
        raise IngestError("invalid_root", f"Krisp inbox must be inside the runtime root: {inbox_root}") from exc
    inbox_root.mkdir(parents=True, exist_ok=True)
    when = now or datetime.now(UTC)
    ledger = _load_ledger(runtime_root)
    known = ledger["meetings"]

    pulled: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    notes_unavailable: list[str] = []
    failed: list[dict[str, Any]] = []

    for stub in client.list_meetings(since_days=since_days):
        if stub.meeting_id in known:
            skipped.append(stub.meeting_id)
            continue
        try:
            meeting = client.get_meeting(stub.meeting_id)
        except Exception as exc:  # noqa: BLE001 - any adapter failure is recorded, not raised
            failed.append({"meeting_id": stub.meeting_id, "title": stub.title, "error": str(exc)})
            continue

        text = format_transcript(meeting.segments)
        target = unique_target(inbox_root, transcript_filename(meeting, today=today))
        derived.write_text(inbox_root, target, text, expected_absent=True)
        write_sidecar(inbox_root, target, sidecar_payload(meeting))

        status = "pulled"
        if not text.strip():
            empty.append(stub.meeting_id)
            status = "empty"
        elif not _has_notes(meeting.notes):
            notes_unavailable.append(stub.meeting_id)
            status = "notes_unavailable"

        known[stub.meeting_id] = {
            "title": meeting.title,
            "meeting_date": transcript_filename(meeting, today=today)[:10],
            "digest": sha256_bytes(text.encode("utf-8")),
            "transcript": str(target),
            "sidecar": str(target.with_suffix(".krisp.json")),
            "pulled_at": when.isoformat(timespec="seconds"),
            "status": status,
        }
        pulled.append(stub.meeting_id)

    _save_ledger(runtime_root, ledger)
    previous_sync = _load_sync(runtime_root)
    last_success = when.isoformat(timespec="seconds") if not failed else previous_sync.get("last_success_at")
    _save_sync(
        runtime_root,
        {
            "last_attempt_at": when.isoformat(timespec="seconds"),
            "last_success_at": last_success,
            "failed": failed,
        },
    )

    return PullResult(
        inbox=str(inbox_root),
        pulled=tuple(pulled),
        skipped=tuple(skipped),
        empty_transcripts=tuple(empty),
        notes_unavailable=tuple(notes_unavailable),
        failed=tuple(failed),
        last_success_at=last_success,
    )


def _has_notes(notes: dict[str, Any]) -> bool:
    blocks = notes.get("blocks") if isinstance(notes, dict) else None
    return bool(blocks)


def _load_ledger(runtime_root: Path) -> dict[str, Any]:
    data = load_json(runtime_root / LEDGER_REL)
    if not isinstance(data, dict) or not isinstance(data.get("meetings"), dict):
        return {"version": LEDGER_VERSION, "meetings": {}}
    return {"version": int(data.get("version") or LEDGER_VERSION), "meetings": dict(data["meetings"])}


def _save_ledger(runtime_root: Path, ledger: dict[str, Any]) -> None:
    derived.write_json(runtime_root, LEDGER_REL, ledger)


def _load_sync(runtime_root: Path) -> dict[str, Any]:
    data = load_json(runtime_root / SYNC_REL)
    return data if isinstance(data, dict) else {}


def sync_status(runtime: str | Path) -> dict[str, Any]:
    """Return the recorded Krisp sync status, or an empty mapping when none exists."""
    return _load_sync(Path(runtime).expanduser().resolve())


def _save_sync(runtime_root: Path, payload: dict[str, Any]) -> None:
    derived.write_json(runtime_root, SYNC_REL, payload)
