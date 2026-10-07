"""V2 spec 02: schema normalization migration."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.inventory.index import connect, index_path
from worksync.inventory.parse import read_frontmatter
from worksync.migrate.schema import REASON, REVIEWER, apply_normalization, detect
from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.repository import WorkIndex

WHEN = date(2026, 10, 6)

TASK = (
    "---\n"
    'type: "task"\n'
    "status: complete\n"
    "priority: 2\n"
    "owners:\n"
    '  - "[[Myles Creese]]"\n'
    'project: "[[Project - Alpha]]"\n'
    "due: 2026-01-01\n"
    "completed: 2026-01-01\n"
    "revision: 3\n"
    "---\n# Task One\nBody line\n"
)
TASK_AFTER = (
    TASK.replace('type: "task"', 'type: "action"')
    .replace("status: complete", "status: done")
    .replace("priority: 2", "priority: P2")
)

MEETING = (
    "---\n"
    "type: meeting\n"
    "date: 2026-09-01\n"
    "people:\n"
    '  - "[[Myles Creese]]"\n'
    "projects:\n"
    '  - "[[Project - Alpha]]"\n'
    "---\n# Meeting\n"
)
MEETING_AFTER = (
    "---\n"
    "type: meeting\n"
    "date: 2026-09-01\n"
    "attendees:\n"
    '  - "[[Myles Creese]]"\n'
    "projects:\n"
    '  - "[[Project - Alpha]]"\n'
    "status: held\n"
    "---\n# Meeting\n"
)

PROJECT = (
    '---\ntype: project\nstatus: complete\nowners:\n  - "[[Myles Creese]]"\nproject_id: alpha\n---\n# Project - Alpha\n'
)
PROJECT_AFTER = PROJECT.replace("status: complete", "status: done")

PERSON = "---\ntype: person\nrole: PM\n---\n# Myles\n"
PERSON_AFTER = "---\ntype: person\nrole: PM\nstatus: active\n---\n# Myles\n"

UNDATED = "---\ntype: meeting\ntags: []\n---\n# Undated\n"
UNDATED_AFTER = "---\ntype: meeting\ntags: []\ndate: 1970-01-01\ndate_status: undated\nstatus: held\n---\n# Undated\n"
DRAFT = "---\ntype: meeting\ndate: 2026-09-01\nstatus: draft\n---\n# Draft\n"
TEMPLATE = '---\ntype: meeting\ndate: "{{date}}"\npeople: []\n---\n# Template\n'
DERIVED = "---\ntype: meeting\npeople: []\n---\n# Derived\n"


def _write(vault: Path, name: str, text: str, *, crlf: bool = False) -> Path:
    data = text.replace("\n", "\r\n") if crlf else text
    path = vault / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8"))
    return path


def _seed(vault: Path) -> None:
    _write(vault, "7. Task Notes/Active/Task One.md", TASK)
    _write(vault, "10. Meetings/Meeting - Held.md", MEETING)
    _write(vault, "9. Project/Project - Alpha.md", PROJECT)
    _write(vault, "People/Myles.md", PERSON)


def _backups(runtime: Path) -> list[Path]:
    return sorted((runtime / "backups").glob("backup-*/file-*"))


def test_detect_maps_each_entity_and_touches_only_mapped_fields(vault: Path) -> None:
    _seed(vault)
    changes = {change.path: change for change in detect(vault, when=WHEN).changes}
    assert changes["7. Task Notes/Active/Task One.md"].content == TASK_AFTER
    assert changes["10. Meetings/Meeting - Held.md"].content == MEETING_AFTER
    assert changes["9. Project/Project - Alpha.md"].content == PROJECT_AFTER
    assert changes["People/Myles.md"].content == PERSON_AFTER
    for change in changes.values():
        assert read_frontmatter(change.content).malformed is False


def test_detect_reports_unmappable_notes_without_guessing(vault: Path) -> None:
    _write(vault, "10. Meetings/Meeting - Draft.md", DRAFT)
    _write(vault, "6. Templates/Meeting Template.md", TEMPLATE)
    report = detect(vault, when=WHEN)
    assert report.changes == ()
    skipped = {note.path: note.reason for note in report.skipped}
    assert "unmappable meeting status" in skipped["10. Meetings/Meeting - Draft.md"]
    assert "not a parseable ISO date" in skipped["6. Templates/Meeting Template.md"]


def test_detect_marks_undated_meeting_with_sentinel_and_marker(vault: Path) -> None:
    _write(vault, "10. Meetings/Meeting - Undated.md", UNDATED)
    change = next(iter(detect(vault, when=WHEN).changes))
    assert "date: undated -> 1970-01-01" in change.changes
    assert "date_status: -> undated" in change.changes
    assert "status: -> held" in change.changes
    assert change.content == UNDATED_AFTER


def test_detect_derives_meeting_date_from_filename(vault: Path) -> None:
    _write(vault, "10. Meetings/Meeting - Foo 2026-09-10.md", DERIVED)
    change = next(iter(detect(vault, when=WHEN).changes))
    assert "date: derived 2026-09-10" in change.changes
    assert "status: -> held" in change.changes
    assert change.content == ("---\ntype: meeting\nattendees: []\ndate: 2026-09-10\nstatus: held\n---\n# Derived\n")


def test_detect_preserves_crlf_notes(vault: Path) -> None:
    _write(vault, "People/Carlos.md", PERSON, crlf=True)
    change = next(iter(detect(vault, when=WHEN).changes))
    expected = "---\r\ntype: person\r\nrole: PM\r\nstatus: active\r\n---\r\n# Myles\r\n"
    assert change.content == expected


def test_apply_normalizes_backs_up_and_journals(vault: Path, tmp_path: Path) -> None:
    _seed(vault)
    runtime = tmp_path / "var"
    result = apply_normalization(vault, runtime, when=WHEN)
    assert result is not None and result.committed is True
    assert (vault / "7. Task Notes/Active/Task One.md").read_text(encoding="utf-8") == TASK_AFTER
    assert (vault / "10. Meetings/Meeting - Held.md").read_text(encoding="utf-8") == MEETING_AFTER
    assert (vault / "9. Project/Project - Alpha.md").read_text(encoding="utf-8") == PROJECT_AFTER
    assert (vault / "People/Myles.md").read_text(encoding="utf-8") == PERSON_AFTER
    assert len(_backups(runtime)) == 4
    assert result.changes[0]["reviewer"] == REVIEWER
    assert result.changes[0]["reason"] == REASON
    assert json.loads(result.journal.read_text(encoding="utf-8"))["committed"] is True


def test_apply_is_idempotent(vault: Path, tmp_path: Path) -> None:
    _seed(vault)
    runtime = tmp_path / "var"
    assert apply_normalization(vault, runtime, when=WHEN) is not None
    journals = sorted((runtime / "journal").glob("*.json"))
    assert len(journals) == 1
    assert detect(vault, when=WHEN).changes == ()
    assert apply_normalization(vault, runtime, when=WHEN) is None
    assert sorted((runtime / "journal").glob("*.json")) == journals


def test_apply_leaves_unmappable_notes_byte_identical(vault: Path, tmp_path: Path) -> None:
    _write(vault, "10. Meetings/Meeting - Draft.md", DRAFT)
    _write(vault, "6. Templates/Meeting Template.md", TEMPLATE)
    runtime = tmp_path / "var"
    assert apply_normalization(vault, runtime, when=WHEN) is None
    assert (vault / "10. Meetings/Meeting - Draft.md").read_text(encoding="utf-8") == DRAFT
    assert (vault / "6. Templates/Meeting Template.md").read_text(encoding="utf-8") == TEMPLATE
    assert not (runtime / "journal").exists()
    assert not (runtime / "backups").exists()


def test_undated_meeting_migration_is_idempotent(vault: Path, tmp_path: Path) -> None:
    _write(vault, "10. Meetings/Meeting - Undated.md", UNDATED)
    runtime = tmp_path / "var"
    assert apply_normalization(vault, runtime, when=WHEN) is not None
    assert (vault / "10. Meetings/Meeting - Undated.md").read_text(encoding="utf-8") == UNDATED_AFTER
    assert detect(vault, when=WHEN).changes == ()
    assert apply_normalization(vault, runtime, when=WHEN) is None


def test_undated_meeting_warns_after_migration(vault: Path, tmp_path: Path) -> None:
    _write(vault, "10. Meetings/Meeting - Undated.md", UNDATED)
    assert apply_normalization(vault, tmp_path / "var", when=WHEN) is not None
    index = WorkIndex.from_vault(vault)
    assert index.errors == ()
    warnings = {(issue.path, issue.rule) for issue in index.warnings}
    assert ("10. Meetings/Meeting - Undated.md", "undated") in warnings


def test_changed_source_sha_fails_closed(vault: Path, tmp_path: Path) -> None:
    _seed(vault)
    report = detect(vault, when=WHEN)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    target = vault / "9. Project/Project - Alpha.md"
    target.write_bytes(target.read_bytes() + b"\n")
    before[target] = target.read_bytes()
    with pytest.raises(MutationError) as excinfo:
        apply_normalization(vault, tmp_path / "var", report=report)
    assert excinfo.value.code == "stale_hash"
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before


def test_missing_target_fails_closed(vault: Path, tmp_path: Path) -> None:
    _seed(vault)
    report = detect(vault, when=WHEN)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    missing = vault / "9. Project/Project - Alpha.md"
    missing.unlink()
    before.pop(missing)
    with pytest.raises(MutationError) as excinfo:
        apply_normalization(vault, tmp_path / "var", report=report)
    assert excinfo.value.code == "missing_target"
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before


def test_detect_derives_date_when_the_key_is_blank(vault: Path) -> None:
    _write(
        vault,
        "10. Meetings/Meeting - Blank 2026-09-10.md",
        '---\ntype: meeting\ndate: ""\npeople: []\n---\n# Blank\n',
    )
    change = next(iter(detect(vault, when=WHEN).changes))
    assert "date: derived 2026-09-10" in change.changes


def test_mid_transaction_failure_rolls_back_every_note(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(vault)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    runtime = tmp_path / "var"
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("Project - Alpha.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply_normalization(vault, runtime, when=WHEN)
    assert excinfo.value.code == "rolled_back"
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before
    journal = next(iter((runtime / "journal").glob("*.json")))
    record = json.loads(journal.read_text(encoding="utf-8"))
    assert record["committed"] is False
    assert record["rolled_back"] is True


def test_reader_integration_after_migration(vault: Path, tmp_path: Path) -> None:
    _seed(vault)
    before = WorkIndex.from_vault(vault)
    assert len({issue.path for issue in before.errors}) == 3

    assert apply_normalization(vault, tmp_path / "var", when=WHEN) is not None

    after = WorkIndex.from_vault(vault)
    assert len({issue.path for issue in after.errors}) == 0
    task_text = (vault / "7. Task Notes/Active/Task One.md").read_text(encoding="utf-8")
    assert "task" not in read_frontmatter(task_text).data["type"]
    task = after.get("action", "Task One")
    assert task is not None and task.status == "done" and task.priority == "P2"
    meeting = after.get("meeting", "Meeting - Held")
    assert meeting is not None and meeting.status == "held" and meeting.attendees == ("[[Myles Creese]]",)


def test_cli_dry_run_writes_nothing(vault: Path, tmp_path: Path, capsys) -> None:
    _seed(vault)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    runtime = tmp_path / "var"
    code = main(["migrate", "schema", "--dry-run", "--vault", str(vault), "--runtime", str(runtime), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert len(payload["planned"]) == 4
    assert payload["committed"] is False
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before
    assert not (runtime / "journal").exists()


def test_cli_apply_normalizes_and_reports_counts(vault: Path, tmp_path: Path, capsys) -> None:
    _seed(vault)
    runtime = tmp_path / "var"
    code = main(["migrate", "schema", "--vault", str(vault), "--runtime", str(runtime), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert payload["schema_invalid_before"] == 3
    assert payload["schema_invalid_after"] == 0
    assert sorted(payload["normalized"]) == [
        "10. Meetings/Meeting - Held.md",
        "7. Task Notes/Active/Task One.md",
        "9. Project/Project - Alpha.md",
        "People/Myles.md",
    ]
    assert (
        read_frontmatter((vault / "7. Task Notes/Active/Task One.md").read_text(encoding="utf-8")).data["type"]
        == "action"
    )
    assert index_path(runtime).is_file()
    con = connect(index_path(runtime))
    try:
        rows = con.execute(
            "SELECT path, project_id, evidence_authority FROM note_project_links WHERE project_id='alpha'"
        ).fetchall()
    finally:
        con.close()
    assert ("7. Task Notes/Active/Task One.md", "alpha", "authoritative") in rows
