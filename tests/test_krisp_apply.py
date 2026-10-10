"""Ticket 05: promote a meeting candidate and consume the transcript."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.ingest import apply, scan
from worksync.ingest.discover import IngestError
from worksync.ingest.krisp import write_sidecar

TODAY = date(2026, 10, 7)
PERSON = "---\ntype: person\nstatus: active\n---\n# Myles Creese\n"
PROJECT = "---\ntype: project\nstatus: active\nproject_id: eleos\n---\n# Project - Eleos\n"
TRANSCRIPT_NAME = "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
PROPOSAL_ID = "krisp:a1b2c3d4e5f6"


def _sidecar(meeting_id: str = "a1b2c3d4e5f6") -> dict:
    return {
        "meeting_id": meeting_id,
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


def _seed(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, *, meeting_ids: tuple[str, ...] = ("a1b2c3d4e5f6",)
) -> tuple[Path, Path]:
    (vault / "7. Task Notes" / "Inbox").mkdir(parents=True, exist_ok=True)
    (vault / "10. Meetings").mkdir(parents=True, exist_ok=True)
    write_note(vault, "People/Myles Creese.md", PERSON)
    write_note(vault, "9. Project/Project - Eleos.md", PROJECT)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    inbox.mkdir(parents=True)
    for meeting_id in meeting_ids:
        transcript = inbox / TRANSCRIPT_NAME
        transcript.write_text("Myles Creese | 0:00\nProject - Eleos is on track\n", encoding="utf-8")
        write_sidecar(inbox, transcript, _sidecar(meeting_id))
    return runtime, inbox


def test_promote_creates_the_note_and_consumes_the_transcript(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    result = apply(
        vault,
        runtime,
        reviewer="myles",
        reason="Promote the meeting",
        ids=(PROPOSAL_ID,),
        today=TODAY,
        krisp_inbox_path=inbox,
    )
    assert result.committed is True
    note = vault / "10. Meetings" / "Meeting - Q3 Sync.md"
    content = note.read_text(encoding="utf-8")
    assert "type: meeting" in content
    assert "status: held" in content
    assert "date: 2026-10-07" in content
    assert "[[Myles Creese]]" in content
    assert "[[Project - Eleos]]" in content
    assert "## Notes" in content and "Ship v2" in content
    assert "## Actions" in content and "Send deck" in content
    assert "people:" not in content and "record_types:" not in content and "staged:" not in content

    assert not (inbox / TRANSCRIPT_NAME).exists()
    processed = inbox / "Processed" / "2026-10-07"
    assert (processed / TRANSCRIPT_NAME).is_file()
    assert (processed / "2026-10-07 - Q3 Sync [a1b2c3d4].krisp.json").is_file()


def test_promote_is_not_a_confirmation_verb(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    result = apply(
        vault,
        runtime,
        reviewer="myles",
        reason="Promote the meeting",
        ids=(PROPOSAL_ID,),
        confirmed=False,
        today=TODAY,
        krisp_inbox_path=inbox,
    )
    assert result.committed is True


def test_override_renames_the_note(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    apply(
        vault,
        runtime,
        reviewer="myles",
        reason="Promote the meeting",
        ids=(PROPOSAL_ID,),
        overrides={PROPOSAL_ID: {"title": "Renamed Sync"}},
        today=TODAY,
        krisp_inbox_path=inbox,
    )
    assert (vault / "10. Meetings" / "Meeting - Renamed Sync.md").is_file()


def test_stale_transcript_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    (inbox / TRANSCRIPT_NAME).write_text("changed\n", encoding="utf-8")
    with pytest.raises(IngestError):
        apply(
            vault,
            runtime,
            reviewer="myles",
            reason="Promote the meeting",
            ids=(PROPOSAL_ID,),
            today=TODAY,
            krisp_inbox_path=inbox,
        )
    assert not (vault / "10. Meetings" / "Meeting - Q3 Sync.md").exists()


def test_missing_transcript_leaves_the_vault_byte_identical(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    (inbox / TRANSCRIPT_NAME).unlink()
    with pytest.raises(IngestError):
        apply(
            vault,
            runtime,
            reviewer="myles",
            reason="Promote the meeting",
            ids=(PROPOSAL_ID,),
            today=TODAY,
            krisp_inbox_path=inbox,
        )
    assert list((vault / "10. Meetings").glob("*.md")) == []


def test_dry_run_lists_ops_without_writing(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    result = apply(
        vault,
        runtime,
        reviewer="myles",
        reason="Promote the meeting",
        ids=(PROPOSAL_ID,),
        today=TODAY,
        krisp_inbox_path=inbox,
        dry_run=True,
    )
    assert result.committed is False
    assert any(change["kind"] == "create" for change in result.changes)
    assert not (vault / "10. Meetings" / "Meeting - Q3 Sync.md").exists()
    assert (inbox / TRANSCRIPT_NAME).is_file()
