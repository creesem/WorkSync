"""Spec 5 ticket 04: rough-note import into the inbox with a recoverable backup."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.ingest import IngestError, import_note, scan
from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 6)
ROUGH = "1. Rough Notes"
INBOX = "7. Task Notes/Inbox"
ARCHIVE = f"{ROUGH}/Archive/{TODAY.isoformat()}"
PROJECT = "9. Project/Project - Alpha.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    (vault / INBOX).mkdir(parents=True, exist_ok=True)
    (vault / ROUGH).mkdir(parents=True, exist_ok=True)
    write_note(
        vault,
        PROJECT,
        "---\ntype: project\nstatus: active\nproject_id: alpha\n"
        'owners:\n  - "[[Myles]]"\npriority: P1\n---\n# Project - Alpha\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def test_import_moves_a_rough_note_into_the_inbox(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    source = write_note(vault, f"{ROUGH}/Note.md", "---\ntags: [x]\n---\n# Buy stamps\n\nBody line.\n")
    original = source.read_text(encoding="utf-8")

    result = import_note(
        vault,
        tmp_path / "var",
        source=f"{ROUGH}/Note.md",
        inbox_path=INBOX,
        rough_notes_path=ROUGH,
        reviewer="Myles",
        reason="Capture",
        today=TODAY,
    )

    assert result.committed is True
    target = vault / INBOX / "Inbox - Buy stamps.md"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "capture: rough-note" in text
    assert "# Buy stamps" in text
    assert "Body line." in text
    assert not (vault / f"{ROUGH}/Note.md").exists()
    archived = list((vault / ARCHIVE).glob("*.md"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == original
    assert result.target == f"{INBOX}/Inbox - Buy stamps.md"


def test_import_does_not_overwrite_a_same_named_inbox_note(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    existing = write_note(vault, f"{INBOX}/Inbox - Buy stamps.md", "# Existing\n")
    write_note(vault, f"{ROUGH}/Note.md", "# Buy stamps\n\nNew body.\n")

    import_note(
        vault,
        tmp_path / "var",
        source=f"{ROUGH}/Note.md",
        inbox_path=INBOX,
        rough_notes_path=ROUGH,
        reviewer="Myles",
        reason="Capture",
        today=TODAY,
    )

    assert existing.read_text(encoding="utf-8") == "# Existing\n"
    assert (vault / INBOX / "Inbox - Buy stamps 1.md").is_file()


def test_import_requires_reviewer_and_reason(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{ROUGH}/Note.md", "# Buy stamps\n")
    with pytest.raises(IngestError) as excinfo:
        import_note(
            vault,
            tmp_path / "var",
            source=f"{ROUGH}/Note.md",
            inbox_path=INBOX,
            rough_notes_path=ROUGH,
            reviewer="",
            reason="Capture",
        )
    assert excinfo.value.code == "missing_reviewer"
    assert (vault / f"{ROUGH}/Note.md").is_file()


def test_import_rejects_a_source_outside_the_rough_notes_root(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    write_note(vault, "Elsewhere/Note.md", "# Nope\n")
    with pytest.raises(IngestError) as excinfo:
        import_note(
            vault,
            tmp_path / "var",
            source="Elsewhere/Note.md",
            inbox_path=INBOX,
            rough_notes_path=ROUGH,
            reviewer="Myles",
            reason="Capture",
        )
    assert excinfo.value.code == "invalid_source"


def test_import_rolls_back_when_the_inbox_create_fails(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{ROUGH}/Note.md", "# Buy stamps\n")
    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if path.name == "Inbox - Buy stamps.md":
            raise OSError("disk full")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError):
        import_note(
            vault,
            tmp_path / "var",
            source=f"{ROUGH}/Note.md",
            inbox_path=INBOX,
            rough_notes_path=ROUGH,
            reviewer="Myles",
            reason="Capture",
            today=TODAY,
        )
    assert (vault / f"{ROUGH}/Note.md").is_file()
    assert not (vault / INBOX / "Inbox - Buy stamps.md").exists()


def test_imported_note_scans_as_a_new_action(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{ROUGH}/Note.md", "# Buy stamps\n")
    runtime = tmp_path / "var"
    import_note(
        vault,
        runtime,
        source=f"{ROUGH}/Note.md",
        inbox_path=INBOX,
        rough_notes_path=ROUGH,
        reviewer="Myles",
        reason="Capture",
        today=TODAY,
    )

    manifest = scan(vault, runtime, today=TODAY, inbox_path=INBOX, rough_notes_path=ROUGH)
    proposals = [p for p in manifest.proposals if p.source_path == f"{INBOX}/Inbox - Buy stamps.md"]
    assert len(proposals) == 1
    assert proposals[0].action == "action"

    index = WorkIndex.from_vault(vault)
    errors = {issue.path for issue in index.errors}
    assert f"{INBOX}/Inbox - Buy stamps.md" not in errors


def test_rescan_ignores_archived_rough_notes(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{ROUGH}/Note.md", "# Buy stamps\n")
    write_note(vault, f"{ROUGH}/Archive/2026-01-01/Old.md", "# Archived\n")
    runtime = tmp_path / "var"
    manifest = scan(vault, runtime, today=TODAY, inbox_path=INBOX, rough_notes_path=ROUGH)
    paths = {proposal.source_path for proposal in manifest.proposals}
    assert paths == {f"{ROUGH}/Note.md"}


def test_cli_ingest_import(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{ROUGH}/Note.md", "# Buy stamps\n")
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]
    code = main(
        [
            "ingest",
            "import",
            f"{ROUGH}/Note.md",
            *base,
            "--inbox",
            INBOX,
            "--rough-notes",
            ROUGH,
            "--reviewer",
            "Myles",
            "--reason",
            "Capture",
            "--today",
            TODAY.isoformat(),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert (vault / INBOX / "Inbox - Buy stamps.md").is_file()
