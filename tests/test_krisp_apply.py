"""Ticket 05: promote a meeting candidate and consume the transcript."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from krisp_fakes import sidecar as _sidecar
from worksync.ingest import apply, load_manifest, save_manifest, scan
from worksync.ingest.apply import render_meeting_note
from worksync.ingest.discover import IngestError
from worksync.ingest.krisp import write_sidecar
from worksync.ingest.manifest import load_manifest_with_hash
from worksync.inventory.parse import parse_note
from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.models import Meeting
from worksync.work.schema import entity_from_record
from worksync.work.validate import validate_entity

TODAY = date(2026, 10, 7)
PERSON = "---\ntype: person\nstatus: active\n---\n# Myles Creese\n"
PROJECT = "---\ntype: project\nstatus: active\nproject_id: eleos\n---\n# Project - Eleos\n"
TRANSCRIPT_NAME = "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
PROPOSAL_ID = "krisp:a1b2c3d4e5f6"


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
    assert 'sync_mode: "managed-locally"' in content

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


def _tamper_meeting(runtime: Path, *, fields: dict | None = None, source_path: str | None = None) -> None:
    loaded = load_manifest_with_hash(runtime)
    assert loaded is not None
    manifest, expected = loaded
    updated = tuple(
        replace(
            proposal,
            fields={**proposal.fields, **(fields or {})},
            source_path=source_path if source_path is not None else proposal.source_path,
        )
        if proposal.id == PROPOSAL_ID
        else proposal
        for proposal in manifest.proposals
    )
    save_manifest(runtime, manifest.with_proposals(updated), expected=expected, expected_absent=False)


def test_render_meeting_note_rejects_unknown_status() -> None:
    with pytest.raises(IngestError) as excinfo:
        render_meeting_note({"status": "archived", "date": "2026-10-07"})
    assert excinfo.value.code == "invalid_meeting_status"


def test_render_meeting_note_rejects_a_missing_date() -> None:
    with pytest.raises(IngestError) as excinfo:
        render_meeting_note({"status": "held"})
    assert excinfo.value.code == "invalid_meeting_date"


def test_render_meeting_note_rejects_an_unparseable_date() -> None:
    with pytest.raises(IngestError) as excinfo:
        render_meeting_note({"status": "held", "date": "next Tuesday"})
    assert excinfo.value.code == "invalid_meeting_date"


def test_render_meeting_note_accepts_a_valid_draft() -> None:
    content = render_meeting_note({"status": "held", "date": "2026-10-07", "date_status": "undated"})
    assert "status: held" in content
    assert "date: 2026-10-07" in content
    assert 'date_status: "undated"' in content
    assert "sync_mode" not in content


def test_render_meeting_note_writes_sync_mode_for_a_sourced_note() -> None:
    content = render_meeting_note(
        {"status": "held", "date": "2026-10-07", "source_system": "krisp", "external_id": "a1b2c3d4e5f6"}
    )
    assert 'source_system: "krisp"' in content
    assert 'external_id: "a1b2c3d4e5f6"' in content
    assert 'sync_mode: "managed-locally"' in content


def test_promoted_meeting_note_declares_sync_mode(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    apply(
        vault,
        runtime,
        reviewer="myles",
        reason="Promote the meeting",
        ids=(PROPOSAL_ID,),
        today=TODAY,
        krisp_inbox_path=inbox,
    )
    note = vault / "10. Meetings" / "Meeting - Q3 Sync.md"
    entity = entity_from_record(parse_note(note, vault))
    assert isinstance(entity, Meeting)
    assert entity.sync_mode == "managed-locally"
    issues = validate_entity(entity)
    assert not any("source_system present without sync_mode" in issue.message for issue in issues)
    assert not any(issue.rule == "conditional" for issue in issues)


@pytest.mark.parametrize("fields", [{"status": "archived"}, {"date": "next Tuesday"}])
def test_invalid_meeting_draft_fails_before_any_write(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, fields: dict
) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    _tamper_meeting(runtime, fields=fields)
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
    assert (inbox / TRANSCRIPT_NAME).is_file()
    assert (inbox / TRANSCRIPT_NAME).with_suffix(".krisp.json").is_file()
    loaded = load_manifest(runtime)
    assert loaded is not None
    assert all(proposal.status == "pending" for proposal in loaded.proposals)


def test_promote_refuses_an_inbox_outside_the_runtime_root(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(IngestError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="myles",
            reason="Promote the meeting",
            ids=(PROPOSAL_ID,),
            today=TODAY,
            krisp_inbox_path=outside,
        )
    assert excinfo.value.code == "invalid_root"
    assert not (vault / "10. Meetings" / "Meeting - Q3 Sync.md").exists()
    assert (inbox / TRANSCRIPT_NAME).is_file()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_meeting_promote_mid_batch_failure_restores_the_vault_and_inbox(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    vault_before = _snapshot(vault)
    inbox_before = _snapshot(inbox)
    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if Path(path).name == "manifest.json":
            raise OSError("disk full")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="myles",
            reason="Promote the meeting",
            ids=(PROPOSAL_ID,),
            today=TODAY,
            krisp_inbox_path=inbox,
        )
    assert excinfo.value.code == "rolled_back"
    assert _snapshot(vault) == vault_before
    assert _snapshot(inbox) == inbox_before
    assert (inbox / TRANSCRIPT_NAME).is_file()
    assert (inbox / TRANSCRIPT_NAME).with_suffix(".krisp.json").is_file()
    assert not (vault / "10. Meetings" / "Meeting - Q3 Sync.md").exists()
    loaded = load_manifest(runtime)
    assert loaded is not None
    assert all(proposal.status == "pending" for proposal in loaded.proposals)

    journals = list((runtime / "journal").glob("*.json"))
    assert len(journals) == 1
    record = json.loads(journals[0].read_text(encoding="utf-8"))
    assert record["rolled_back"] is True
    assert any(op["kind"] == "create" for op in record["ops"])


def test_render_meeting_note_rejects_a_non_canonical_iso_date() -> None:
    with pytest.raises(IngestError) as excinfo:
        render_meeting_note({"status": "held", "date": "20261007"})
    assert excinfo.value.code == "invalid_meeting_date"


def test_promote_refuses_a_transcript_outside_the_inbox(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)
    (inbox.parent / "escape.txt").write_text("not the transcript\n", encoding="utf-8")
    _tamper_meeting(runtime, source_path="../escape.txt")
    with pytest.raises(IngestError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="myles",
            reason="Promote the meeting",
            ids=(PROPOSAL_ID,),
            today=TODAY,
            krisp_inbox_path=inbox,
        )
    assert excinfo.value.code == "invalid_source"
    assert not (vault / "10. Meetings" / "Meeting - Q3 Sync.md").exists()
    assert (inbox / TRANSCRIPT_NAME).is_file()
