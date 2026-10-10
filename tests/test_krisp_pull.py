"""Ticket 02: Krisp transcript pull — inbox, sidecar, ledger, and sidecar safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from krisp_fakes import FakeKrispClient
from krisp_fakes import meeting as _meeting
from worksync.ingest.discover import IngestError
from worksync.ingest.krisp import (
    PullResult,
    format_transcript,
    pull,
    read_sidecar,
    sidecar_path,
    transcript_filename,
    write_sidecar,
)


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


def test_pull_refuses_an_inbox_outside_the_runtime_root(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    outside = tmp_path / "elsewhere"
    with pytest.raises(IngestError) as excinfo:
        pull(runtime, client=FakeKrispClient((_meeting(),)), since_days=14, inbox=outside)
    assert excinfo.value.code == "invalid_root"
    assert not (outside / "2026-10-07 - Q3 Sync [a1b2c3d4].txt").exists()


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
