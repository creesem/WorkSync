"""Milestone 11 / ticket 01: assign canonical ticket, meeting, and action ids."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.migrate.entity_ids import REASON, REVIEWER, apply_entity_ids, detect_entity_ids
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
    _write(vault, "Actions/A.md", "---\ntype: action\nstatus: open\n---\n# Follow up\n")
    _write(vault, "Actions/B.md", "---\ntype: action\nstatus: open\n---\n# Follow up\n")
    assert sorted(_assigned(vault).values()) == ["follow-up", "follow-up-2"]


def test_detect_avoids_an_existing_id_of_the_same_field(vault: Path) -> None:
    _write(vault, "Tickets/A.md", "---\ntype: ticket\nstatus: open\nticket_id: login-bug\n---\n# Login bug\n")
    _write(vault, "Tickets/B.md", "---\ntype: ticket\nstatus: open\n---\n# Login bug\n")
    assert _assigned(vault) == {"Tickets/B.md": "login-bug-2"}


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
