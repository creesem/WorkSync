"""Ticket 02: Krisp transcript pull — inbox, sidecar, ledger, and sidecar safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.ingest.discover import IngestError
from worksync.ingest.krisp import (
    KrispMeeting,
    MeetingStub,
    PullResult,
    format_transcript,
    pull,
    read_sidecar,
    sidecar_path,
    transcript_filename,
    write_sidecar,
)


def _meeting(
    meeting_id: str = "a1b2c3d4e5f6",
    title: str = "Q3 Sync",
    started_at: str = "2026-10-07T14:00:00Z",
    segments: tuple[dict, ...] | None = None,
    notes: dict | None = None,
) -> KrispMeeting:
    return KrispMeeting(
        meeting_id=meeting_id,
        title=title,
        started_at=started_at,
        duration_seconds=2520,
        source="krisp",
        tags=("sync",),
        speakers=({"index": 0, "first_name": "Myles", "last_name": "Creese", "email": ""},),
        segments=segments
        if segments is not None
        else ({"speaker": "Myles Creese", "start": 0, "end": 5, "text": "Hello team"},),
        notes=notes
        if notes is not None
        else {"blocks": [{"type": "key_points", "children": [{"type": "key_point", "text": "Ship v2"}]}]},
    )


class FakeKrispClient:
    """Deterministic offline stand-in for the Krisp API adapter."""

    def __init__(self, meetings: tuple[KrispMeeting, ...] = (), failures: dict | None = None) -> None:
        self._meetings = {meeting.meeting_id: meeting for meeting in meetings}
        self._failures = dict(failures or {})
        self.list_calls = 0

    def list_meetings(self, *, since_days: int, limit: int | None = None) -> tuple[MeetingStub, ...]:
        self.list_calls += 1
        stubs = tuple(MeetingStub(m.meeting_id, m.title, m.started_at) for m in self._meetings.values())
        return stubs[:limit] if limit else stubs

    def get_meeting(self, meeting_id: str) -> KrispMeeting:
        if meeting_id in self._failures:
            raise self._failures[meeting_id]
        return self._meetings[meeting_id]


def _inbox(runtime: Path) -> Path:
    return runtime / "krisp" / "inbox"


def test_pull_writes_transcript_sidecar_and_ledger(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    client = FakeKrispClient((_meeting(),))
    result = pull(runtime, client=client, since_days=14)
    assert isinstance(result, PullResult)
    assert result.pulled == ("a1b2c3d4e5f6",)
    assert result.failed == ()

    transcript = _inbox(runtime) / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    assert transcript.is_file()
    assert "Myles Creese | 0:00" in transcript.read_text(encoding="utf-8")
    assert sidecar_path(transcript).is_file()

    ledger = json.loads((runtime / "krisp" / "pull-ledger.json").read_text(encoding="utf-8"))
    assert "a1b2c3d4e5f6" in ledger["meetings"]
    assert ledger["meetings"]["a1b2c3d4e5f6"]["status"] == "pulled"


def test_second_pull_skips_known_meeting(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    client = FakeKrispClient((_meeting(),))
    pull(runtime, client=client, since_days=14)
    again = pull(runtime, client=client, since_days=14)
    assert again.pulled == ()
    assert again.skipped == ("a1b2c3d4e5f6",)


def test_failed_meeting_is_recorded_and_retried(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    failing = FakeKrispClient((_meeting(),), failures={"a1b2c3d4e5f6": RuntimeError("boom")})
    result = pull(runtime, client=failing, since_days=14)
    assert result.failed and result.failed[0]["meeting_id"] == "a1b2c3d4e5f6"
    assert result.pulled == ()
    sync = json.loads((runtime / "krisp" / "sync-status.json").read_text(encoding="utf-8"))
    assert sync["failed"] and sync["failed"][0]["meeting_id"] == "a1b2c3d4e5f6"
    ledger = json.loads((runtime / "krisp" / "pull-ledger.json").read_text(encoding="utf-8"))
    assert "a1b2c3d4e5f6" not in ledger["meetings"]

    retry = pull(runtime, client=FakeKrispClient((_meeting(),)), since_days=14)
    assert retry.pulled == ("a1b2c3d4e5f6",)


def test_empty_transcript_is_reported_separately(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    client = FakeKrispClient((_meeting(segments=()),))
    result = pull(runtime, client=client, since_days=14)
    assert result.empty_transcripts == ("a1b2c3d4e5f6",)
    assert result.failed == ()


def test_notes_unavailable_is_reported_separately(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    client = FakeKrispClient((_meeting(notes={}),))
    result = pull(runtime, client=client, since_days=14)
    assert result.notes_unavailable == ("a1b2c3d4e5f6",)
    assert result.failed == ()


def test_sync_status_records_last_success(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    pull(runtime, client=FakeKrispClient((_meeting(),)), since_days=14)
    sync = json.loads((runtime / "krisp" / "sync-status.json").read_text(encoding="utf-8"))
    assert sync["last_success_at"]
    assert sync["failed"] == []


def test_write_sidecar_refuses_missing_transcript(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    with pytest.raises(IngestError):
        write_sidecar(inbox, inbox / "2026-10-07 - Missing [abcd1234].txt", {"meeting_id": "x"})


def test_sidecar_helpers_refuse_source_outside_inbox(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("hi", encoding="utf-8")
    with pytest.raises(IngestError):
        write_sidecar(inbox, outside, {"meeting_id": "x"})
    with pytest.raises(IngestError):
        read_sidecar(inbox, outside)


def test_read_sidecar_returns_payload(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    pull(runtime, client=FakeKrispClient((_meeting(),)), since_days=14)
    transcript = _inbox(runtime) / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    payload = read_sidecar(_inbox(runtime), transcript)
    assert payload is not None
    assert payload["meeting_id"] == "a1b2c3d4e5f6"


def test_format_transcript_and_filename() -> None:
    meeting = _meeting()
    text = format_transcript(meeting.segments)
    assert "Myles Creese | 0:00" in text
    assert "Hello team" in text
    assert transcript_filename(meeting) == "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
