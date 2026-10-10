"""Ticket 03: Krisp discovery turns a transcript into a meeting-note candidate."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from krisp_fakes import sidecar as _sidecar
from worksync.ingest import dismiss, scan
from worksync.ingest.discover import IngestError
from worksync.ingest.krisp import read_sidecar, write_sidecar
from worksync.ingest.proposal import ACTION_KINDS

PERSON = "---\ntype: person\nstatus: active\n---\n# Myles Creese\n"
PROJECT = "---\ntype: project\nstatus: active\nproject_id: eleos\n---\n# Project - Eleos\n"


def _seed_inbox(inbox: Path, *, text: str = "Myles Creese | 0:00\nProject - Eleos is on track\n", **sidecar) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    transcript = inbox / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    transcript.write_text(text, encoding="utf-8")
    write_sidecar(inbox, transcript, _sidecar(**sidecar) if sidecar else _sidecar())
    return transcript


def _seed_vault(write_note: Callable[..., Path], vault: Path) -> None:
    (vault / "7. Task Notes" / "Inbox").mkdir(parents=True, exist_ok=True)
    write_note(vault, "People/Myles Creese.md", PERSON)
    write_note(vault, "9. Project/Project - Eleos.md", PROJECT)


def test_action_kinds_include_meeting() -> None:
    assert "meeting" in ACTION_KINDS


def test_scan_includes_a_meeting_candidate(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    _seed_inbox(inbox)
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    meetings = [p for p in manifest.proposals if p.action == "meeting"]
    assert len(meetings) == 1
    proposal = meetings[0]
    assert proposal.id == "krisp:a1b2c3d4e5f6"
    assert proposal.fields["title"] == "Q3 Sync"
    assert proposal.fields["date"] == "2026-10-07"
    assert proposal.fields["status"] == "held"
    assert proposal.fields["attendees"] == ["[[Myles Creese]]"]
    assert proposal.fields["projects"] == ["[[Project - Eleos]]"]
    assert proposal.fields["key_points"] == ["Ship v2"]
    assert proposal.fields["action_items"] == [{"assignee": "Myles Creese", "text": "Send deck"}]
    assert proposal.fields["source_system"] == "krisp"
    assert proposal.fields["external_id"] == "a1b2c3d4e5f6"
    assert proposal.provenance


def test_unchanged_transcript_keeps_a_dismissal(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    _seed_inbox(inbox)
    scan(vault, runtime, krisp_inbox_path=inbox)
    dismiss(runtime, "krisp:a1b2c3d4e5f6", reviewer="myles", reason="Handled elsewhere")
    again = scan(vault, runtime, krisp_inbox_path=inbox)
    proposal = next(p for p in again.proposals if p.id == "krisp:a1b2c3d4e5f6")
    assert proposal.status == "dismissed"


def test_changed_transcript_voids_a_dismissal(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    transcript = _seed_inbox(inbox)
    scan(vault, runtime, krisp_inbox_path=inbox)
    dismiss(runtime, "krisp:a1b2c3d4e5f6", reviewer="myles", reason="Handled elsewhere")
    transcript.write_text("Myles Creese | 0:00\nUpdated content\n", encoding="utf-8")
    again = scan(vault, runtime, krisp_inbox_path=inbox)
    proposal = next(p for p in again.proposals if p.id == "krisp:a1b2c3d4e5f6")
    assert proposal.status == "pending"
    assert proposal.decision_history


def test_processed_transcript_is_skipped(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    processed = inbox / "Processed" / "2026-10-07"
    processed.mkdir(parents=True)
    transcript = processed / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    transcript.write_text("Myles Creese | 0:00\nHello\n", encoding="utf-8")
    write_sidecar(processed, transcript, _sidecar())
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    assert not [p for p in manifest.proposals if p.action == "meeting"]


def test_missing_sidecar_is_skipped(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "2026-10-07 - Orphan [deadbeef].txt").write_text("hi\n", encoding="utf-8")
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    assert not [p for p in manifest.proposals if p.action == "meeting"]


def test_ambiguous_person_name_is_not_linked(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(vault, "Team/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    (vault / "7. Task Notes" / "Inbox").mkdir(parents=True, exist_ok=True)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    sidecar = _sidecar()
    sidecar["speakers"] = [{"first_name": "Myles", "last_name": ""}]
    inbox.mkdir(parents=True, exist_ok=True)
    transcript = inbox / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    transcript.write_text("Myles | 0:00\nHello\n", encoding="utf-8")
    write_sidecar(inbox, transcript, sidecar)
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    proposal = next(p for p in manifest.proposals if p.action == "meeting")
    assert proposal.fields["attendees"] == []
    assert "ambiguous speakers: Myles" in proposal.provenance
    assert not any(reason.startswith("unmatched speakers:") for reason in proposal.provenance)


def test_unmatched_speaker_records_the_unmatched_reason(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    sidecar = _sidecar()
    sidecar["speakers"] = [{"first_name": "Nobody", "last_name": "Here"}]
    inbox.mkdir(parents=True, exist_ok=True)
    transcript = inbox / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    transcript.write_text("Nobody Here | 0:00\nHello\n", encoding="utf-8")
    write_sidecar(inbox, transcript, sidecar)
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    proposal = next(p for p in manifest.proposals if p.action == "meeting")
    assert proposal.fields["attendees"] == []
    assert "unmatched speakers: Nobody Here" in proposal.provenance
    assert not any(reason.startswith("ambiguous speakers:") for reason in proposal.provenance)


def test_ambiguous_project_title_is_not_linked(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(
        vault, "9. Project/Alpha.md", "---\ntype: project\nstatus: active\nproject_id: alpha\n---\n# Project - Eleos\n"
    )
    write_note(
        vault, "9. Project/Beta.md", "---\ntype: project\nstatus: active\nproject_id: beta\n---\n# Project - Eleos\n"
    )
    (vault / "7. Task Notes" / "Inbox").mkdir(parents=True, exist_ok=True)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    _seed_inbox(inbox)
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    proposal = next(p for p in manifest.proposals if p.action == "meeting")
    assert proposal.fields["projects"] == []
    assert "ambiguous projects: Project - Eleos" in proposal.provenance


def test_ambiguous_project_id_is_not_linked(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(
        vault,
        "9. Project/Alpha.md",
        "---\ntype: project\nstatus: active\nproject_id: shared\n---\n# Project - Alpha\n",
    )
    write_note(
        vault,
        "9. Project/Beta.md",
        "---\ntype: project\nstatus: active\nproject_id: shared\n---\n# Project - Beta\n",
    )
    (vault / "7. Task Notes" / "Inbox").mkdir(parents=True, exist_ok=True)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    inbox.mkdir(parents=True)
    transcript = inbox / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    transcript.write_text("We discussed the shared effort.\n", encoding="utf-8")
    write_sidecar(inbox, transcript, _sidecar())
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    proposal = next(p for p in manifest.proposals if p.action == "meeting")
    assert proposal.fields["projects"] == []
    assert any(reason.startswith("ambiguous projects:") for reason in proposal.provenance)


def test_project_reference_matching_is_index_driven(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    inbox.mkdir(parents=True)
    transcript = inbox / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    transcript.write_text("Project - Eleos is on track, but Project - Nonexistent is not.\n", encoding="utf-8")
    write_sidecar(inbox, transcript, _sidecar())
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    proposal = next(p for p in manifest.proposals if p.action == "meeting")
    assert proposal.fields["projects"] == ["[[Project - Eleos]]"]
    assert "projects matched 1" in proposal.provenance
    assert not any(reason.startswith("unmatched projects:") for reason in proposal.provenance)
    assert not any(reason.startswith("ambiguous projects:") for reason in proposal.provenance)


def test_empty_inbox_yields_no_meeting_proposals(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    inbox.mkdir(parents=True)
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    assert not [p for p in manifest.proposals if p.action == "meeting"]


def test_undated_recording_uses_the_placeholder(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_vault(write_note, vault)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    _seed_inbox(inbox, started_at="not-a-date")
    manifest = scan(vault, runtime, krisp_inbox_path=inbox)
    proposal = next(p for p in manifest.proposals if p.action == "meeting")
    assert proposal.fields["date"] == "1970-01-01"
    assert proposal.fields["date_status"] == "undated"


def test_sidecar_helper_fails_closed_for_a_moved_transcript(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    with pytest.raises(IngestError):
        read_sidecar(inbox, inbox / "2026-10-07 - Moved [abcd1234].txt")
