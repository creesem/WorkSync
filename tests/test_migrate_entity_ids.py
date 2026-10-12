"""Milestone 11 / ticket 01: assign canonical ticket, meeting, and action ids."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.migrate.entity_ids import (
    REASON,
    REVIEWER,
    apply_entity_ids,
    detect_entity_ids,
    plan_entity_id_revert,
    revert_entity_ids,
)
from worksync.safety.models import MutationError


def _write(vault: Path, name: str, text: str) -> Path:
    path = vault / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _assigned(vault: Path) -> dict[str, str]:
    return {item.path: item.value for item in detect_entity_ids(vault)}


def test_detect_assigns_a_kebab_id_per_type(vault: Path) -> None:
    _write(vault, "Tickets/Login bug.md", "---\ntype: ticket\nstatus: open\n---\n# Login bug\n")
    _write(vault, "Meetings/Weekly sync.md", "---\ntype: meeting\nstatus: held\n---\n# Weekly sync\n")
    _write(vault, "Actions/Send notes.md", "---\ntype: action\nstatus: open\n---\n# Send notes\n")
    fields = {item.path: item.field for item in detect_entity_ids(vault)}
    assert fields == {
        "Tickets/Login bug.md": "ticket_id",
        "Meetings/Weekly sync.md": "meeting_id",
        "Actions/Send notes.md": "action_id",
    }
    assert _assigned(vault) == {
        "Tickets/Login bug.md": "login-bug",
        "Meetings/Weekly sync.md": "weekly-sync",
        "Actions/Send notes.md": "send-notes",
    }


def test_detect_dedupes_within_each_field(vault: Path) -> None:
    _write(vault, "Actions/Follow up.md", "---\ntype: action\nstatus: open\n---\n# Follow up\n")
    _write(vault, "Archive/Follow up.md", "---\ntype: action\nstatus: open\n---\n# Follow up\n")
    assert sorted(_assigned(vault).values()) == ["follow-up", "follow-up-2"]


def test_detect_uses_the_filename_not_a_section_heading(vault: Path) -> None:
    _write(
        vault,
        "10. Meetings/Meeting - Canopy Anywhere Updates.md",
        "---\ntype: meeting\nstatus: held\n---\n## Attendees\n- Eddie D\n",
    )
    assert _assigned(vault) == {"10. Meetings/Meeting - Canopy Anywhere Updates.md": "meeting-canopy-anywhere-updates"}


def test_detect_caps_long_titles_at_a_word_boundary(vault: Path) -> None:
    name = "Confirm whether the Key Pair authentication is the preferred approach for ODBC Connector"
    _write(vault, f"Actions/{name}.md", "---\ntype: action\nstatus: open\n---\n# Heading\n")
    value = _assigned(vault)[f"Actions/{name}.md"]
    assert value == "confirm-whether-the-key-pair-authentication-is-the-preferred"
    assert len(value) <= 60


def test_detect_avoids_an_existing_id_of_the_same_field(vault: Path) -> None:
    _write(vault, "Tickets/Login bug.md", "---\ntype: ticket\nstatus: open\nticket_id: login-bug\n---\n# Login bug\n")
    _write(vault, "Archive/Login bug.md", "---\ntype: ticket\nstatus: open\n---\n# Login bug\n")
    assert _assigned(vault) == {"Archive/Login bug.md": "login-bug-2"}


def test_detect_ignores_notes_that_already_have_an_id(vault: Path) -> None:
    _write(vault, "Meetings/A.md", "---\ntype: meeting\nstatus: held\nmeeting_id: weekly-sync\n---\n# Weekly sync\n")
    assert detect_entity_ids(vault) == ()


def test_detect_ignores_person_and_project_notes(vault: Path) -> None:
    _write(vault, "People/Carlos.md", "---\ntype: person\nstatus: active\n---\n# Carlos\n")
    _write(vault, "Projects/Alpha.md", "---\ntype: project\nstatus: active\n---\n# Alpha\n")
    assert detect_entity_ids(vault) == ()


def test_apply_writes_ids_with_backups_and_is_idempotent(vault: Path, tmp_path: Path) -> None:
    _write(vault, "Tickets/Login bug.md", "---\ntype: ticket\nstatus: open\n---\n# Login bug\n")
    runtime = tmp_path / "var"
    result = apply_entity_ids(vault, runtime)
    assert result is not None and result.committed is True
    assert (vault / "Tickets/Login bug.md").read_text(encoding="utf-8") == (
        "---\ntype: ticket\nstatus: open\nticket_id: login-bug\n---\n# Login bug\n"
    )
    assert result.changes[0]["reviewer"] == REVIEWER
    assert result.changes[0]["reason"] == REASON
    assert list((runtime / "backups").glob("backup-*/file-*"))
    assert detect_entity_ids(vault) == ()
    assert apply_entity_ids(vault, runtime) is None


def test_revert_restores_the_original_bytes_and_the_ids_are_missing_again(vault: Path, tmp_path: Path) -> None:
    original = _write(vault, "Tickets/Login bug.md", "---\ntype: ticket\nstatus: open\n---\n# Login bug\n").read_bytes()
    runtime = tmp_path / "var"
    applied = apply_entity_ids(vault, runtime)
    reverted = revert_entity_ids(vault, runtime, applied.journal)
    assert reverted is not None and reverted.committed is True
    assert (vault / "Tickets/Login bug.md").read_bytes() == original
    assert _assigned(vault) == {"Tickets/Login bug.md": "login-bug"}


def test_revert_refuses_a_note_changed_since_apply_and_touches_nothing(vault: Path, tmp_path: Path) -> None:
    _write(vault, "Tickets/Login bug.md", "---\ntype: ticket\nstatus: open\n---\n# Login bug\n")
    _write(vault, "Tickets/Other.md", "---\ntype: ticket\nstatus: open\n---\n# Other\n")
    runtime = tmp_path / "var"
    applied = apply_entity_ids(vault, runtime)
    edited = vault / "Tickets/Login bug.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nNew line.\n", encoding="utf-8")
    other_before = (vault / "Tickets/Other.md").read_bytes()
    edited_before = edited.read_bytes()
    with pytest.raises(MutationError) as excinfo:
        revert_entity_ids(vault, runtime, applied.journal)
    assert excinfo.value.code == "stale_hash"
    assert (vault / "Tickets/Other.md").read_bytes() == other_before
    assert edited.read_bytes() == edited_before


def test_plan_revert_lists_every_journaled_note_without_writing(vault: Path, tmp_path: Path) -> None:
    _write(vault, "Tickets/Login bug.md", "---\ntype: ticket\nstatus: open\n---\n# Login bug\n")
    runtime = tmp_path / "var"
    applied = apply_entity_ids(vault, runtime)
    before = (vault / "Tickets/Login bug.md").read_bytes()
    ops = plan_entity_id_revert(vault, runtime, applied.journal)
    assert [op.path for op in ops] == [Path("Tickets/Login bug.md")]
    assert (vault / "Tickets/Login bug.md").read_bytes() == before


def test_changed_source_fails_closed(vault: Path, tmp_path: Path) -> None:
    _write(vault, "Actions/Send notes.md", "---\ntype: action\nstatus: open\n---\n# Send notes\n")
    assignments = detect_entity_ids(vault)
    target = vault / "Actions/Send notes.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(MutationError) as excinfo:
        apply_entity_ids(vault, tmp_path / "var", assignments=assignments)
    assert excinfo.value.code == "stale_hash"


def test_cli_entity_ids_assigns_and_reports(vault: Path, tmp_path: Path, capsys) -> None:
    _write(vault, "Meetings/Weekly sync.md", "---\ntype: meeting\nstatus: held\n---\n# Weekly sync\n")
    code = main(["migrate", "entity-ids", "--vault", str(vault), "--runtime", str(tmp_path / "var"), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert payload["assigned"] == [{"path": "Meetings/Weekly sync.md", "field": "meeting_id", "value": "weekly-sync"}]
    assert "meeting_id: weekly-sync" in (vault / "Meetings/Weekly sync.md").read_text(encoding="utf-8")


def test_cli_entity_ids_revert_restores_the_notes(vault: Path, tmp_path: Path, capsys) -> None:
    original = _write(
        vault, "Actions/Send notes.md", "---\ntype: action\nstatus: open\n---\n# Send notes\n"
    ).read_bytes()
    runtime = tmp_path / "var"
    applied = apply_entity_ids(vault, runtime)
    code = main(
        [
            "migrate",
            "entity-ids",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
            "--revert",
            str(applied.journal),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True and payload["reverted"] == 1
    assert (vault / "Actions/Send notes.md").read_bytes() == original


def test_cli_entity_ids_dry_run_writes_nothing(vault: Path, tmp_path: Path, capsys) -> None:
    _write(vault, "Actions/Send notes.md", "---\ntype: action\nstatus: open\n---\n# Send notes\n")
    before = (vault / "Actions/Send notes.md").read_bytes()
    code = main(
        ["migrate", "entity-ids", "--vault", str(vault), "--runtime", str(tmp_path / "var"), "--dry-run", "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True and payload["committed"] is False
    assert (vault / "Actions/Send notes.md").read_bytes() == before
