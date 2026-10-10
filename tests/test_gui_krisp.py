"""Ticket 06: the GUI Krisp review surface over the write seam."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.gui.actions import ActionError, dispatch_action
from worksync.gui.controller import GuiService
from worksync.ingest.krisp import KrispMeeting, MeetingStub, write_sidecar

TODAY = date(2026, 10, 7)
PERSON = "---\ntype: person\nstatus: active\n---\n# Myles Creese\n"
PROJECT = "---\ntype: project\nstatus: active\nproject_id: eleos\n---\n# Project - Eleos\n"
TRANSCRIPT_NAME = "2026-10-07 - Q3 Sync [a1b2c3d4].txt"


class FakeKrispClient:
    def __init__(self, meeting: KrispMeeting) -> None:
        self._meeting = meeting

    def list_meetings(self, *, since_days: int, limit: int | None = None) -> tuple[MeetingStub, ...]:
        return (MeetingStub(self._meeting.meeting_id, self._meeting.title, self._meeting.started_at),)

    def get_meeting(self, meeting_id: str) -> KrispMeeting:
        return self._meeting


def _meeting() -> KrispMeeting:
    return KrispMeeting(
        meeting_id="a1b2c3d4e5f6",
        title="Q3 Sync",
        started_at="2026-10-07T14:00:00Z",
        duration_seconds=60,
        source="krisp",
        tags=("sync",),
        speakers=({"first_name": "Myles", "last_name": "Creese"},),
        segments=({"speaker": "Myles Creese", "start": 0, "end": 4, "text": "Project - Eleos is on track"},),
        notes={
            "blocks": [
                {"type": "key_points", "children": [{"type": "key_point", "text": "Ship v2"}]},
                {"type": "action_items", "children": [{"type": "action_item", "text": "Send deck"}]},
            ]
        },
    )


def _sidecar() -> dict:
    return {
        "meeting_id": "a1b2c3d4e5f6",
        "title": "Q3 Sync",
        "started_at": "2026-10-07T14:00:00Z",
        "duration_seconds": 60,
        "source": "krisp",
        "tags": ["sync"],
        "speakers": [{"first_name": "Myles", "last_name": "Creese"}],
        "segments": [{"speaker": "Myles Creese", "start": 0, "end": 4, "text": "Project - Eleos is on track"}],
        "notes": {
            "blocks": [
                {"type": "key_points", "children": [{"type": "key_point", "text": "Ship v2"}]},
                {"type": "action_items", "children": [{"type": "action_item", "text": "Send deck"}]},
            ]
        },
    }


def _service(vault: Path, runtime: Path, inbox: Path, *, api_key: str | None = "test-key") -> GuiService:
    return GuiService(
        vault=vault,
        db_path=runtime / "index.sqlite3",
        runtime_root=runtime,
        vault_name="vault",
        reviewer="Myles",
        krisp_inbox_path=inbox,
        krisp_since_days=14,
        krisp_api_key=api_key,
    )


def _seed_vault(vault: Path, write_note: Callable[..., Path]) -> None:
    (vault / "7. Task Notes" / "Inbox").mkdir(parents=True, exist_ok=True)
    (vault / "10. Meetings").mkdir(parents=True, exist_ok=True)
    write_note(vault, "People/Myles Creese.md", PERSON)
    write_note(vault, "9. Project/Project - Eleos.md", PROJECT)


def _seed_inbox(inbox: Path) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    transcript = inbox / TRANSCRIPT_NAME
    transcript.write_text("Myles Creese | 0:00\nProject - Eleos is on track\n", encoding="utf-8")
    write_sidecar(inbox, transcript, _sidecar())
    return transcript


def test_scan_includes_a_meeting_candidate(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(vault, write_note)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    _seed_inbox(inbox)
    service = _service(vault, runtime, inbox)
    result = dispatch_action(service, "ingest-scan", {}, today=TODAY)
    meetings = [p for p in result["proposals"] if p["action"] == "meeting"]
    assert len(meetings) == 1
    assert meetings[0]["id"] == "krisp:a1b2c3d4e5f6"


def test_pull_reports_a_summary(vault: Path, write_note: Callable[..., Path], tmp_path: Path, monkeypatch) -> None:
    _seed_vault(vault, write_note)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    service = _service(vault, runtime, inbox)
    monkeypatch.setattr("worksync.gui.actions.build_krisp_client", lambda key, **kw: FakeKrispClient(_meeting()))
    result = dispatch_action(service, "krisp-pull", {}, today=TODAY)
    assert result["action"] == "krisp-pull"
    assert result["summary"]["pulled"] == ["a1b2c3d4e5f6"]
    assert result["equivalent_cli"].startswith("worksync krisp pull")


def test_pull_without_a_key_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(vault, write_note)
    runtime = tmp_path / "var"
    service = _service(vault, runtime, runtime / "krisp" / "inbox", api_key=None)
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "krisp-pull", {}, today=TODAY)
    assert excinfo.value.code == "missing_key"
    assert excinfo.value.status == 400


def test_status_reports_sync_and_window(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(vault, write_note)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    service = _service(vault, runtime, inbox)
    result = dispatch_action(service, "krisp-status", {}, today=TODAY)
    assert result["action"] == "krisp-status"
    assert result["since_days"] == 14
    assert "sync" in result


def test_apply_promotes_a_meeting_candidate(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(vault, write_note)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    _seed_inbox(inbox)
    service = _service(vault, runtime, inbox)
    dispatch_action(service, "ingest-scan", {}, today=TODAY)
    result = dispatch_action(service, "ingest-apply", {"reason": "Promote"}, today=TODAY)
    assert result["committed"] is True
    assert (vault / "10. Meetings" / "Meeting - Q3 Sync.md").is_file()
    assert not (inbox / TRANSCRIPT_NAME).exists()


def test_static_shell_exposes_the_krisp_surface() -> None:
    script = (Path(__file__).resolve().parents[1] / "src" / "worksync" / "gui" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "krisp-pull" in script
    assert "Krisp" in script
