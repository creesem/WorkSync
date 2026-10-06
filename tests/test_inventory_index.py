"""Ticket 02: incremental SQLite/FTS index with derived-state repair."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from worksync.inventory.index import connect, detect_index_outdated, index_vault
from worksync.inventory.parse import parse_note


def meeting_note(body: str, title: str = "Note") -> str:
    return f"---\ntype: meeting\ndate: 2026-01-01\n---\n# {title}\n{body}\n"


def fts_paths(con: sqlite3.Connection, term: str) -> list[str]:
    return sorted(
        row[0]
        for row in con.execute(
            "SELECT notes.path FROM notes_fts JOIN notes ON notes.id = notes_fts.rowid WHERE notes_fts MATCH ?",
            (term,),
        )
    )


def test_indexes_new_notes_into_fts(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "10. Meetings/Alpha.md", meeting_note("MYPAC ProgramIds", "Alpha"))
    db = tmp_path / "index.sqlite3"
    stats = index_vault(db, vault)
    assert stats["inserted"] == 1
    con = connect(db)
    try:
        assert fts_paths(con, "MYPAC") == ["10. Meetings/Alpha.md"]
    finally:
        con.close()


def test_rerun_is_idempotent(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "10. Meetings/Alpha.md", meeting_note("MYPAC", "Alpha"))
    write_note(vault, "10. Meetings/Beta.md", meeting_note("CARES", "Beta"))
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    second = index_vault(db, vault)
    assert (second["inserted"], second["updated"], second["deleted"], second["fts_repaired"]) == (0, 0, 0, 0)
    assert second["unchanged"] == 2


def test_backfills_a_pre_fts_index(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "10. Meetings/Alpha.md", meeting_note("MYPAC", "Alpha"))
    write_note(vault, "10. Meetings/Beta.md", meeting_note("CARES", "Beta"))
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    con = connect(db)
    try:
        con.execute("DELETE FROM notes_fts")
        con.commit()
    finally:
        con.close()
    stats = index_vault(db, vault)
    assert stats["unchanged"] == 2
    assert stats["fts_repaired"] == 2
    con = connect(db)
    try:
        assert fts_paths(con, "MYPAC") == ["10. Meetings/Alpha.md"]
        assert fts_paths(con, "CARES") == ["10. Meetings/Beta.md"]
    finally:
        con.close()


def test_repairs_only_missing_fts_rows(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "10. Meetings/Alpha.md", meeting_note("MYPAC", "Alpha"))
    write_note(vault, "10. Meetings/Beta.md", meeting_note("CARES", "Beta"))
    write_note(vault, "10. Meetings/Gamma.md", meeting_note("ODBC", "Gamma"))
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    con = connect(db)
    try:
        con.execute(
            "DELETE FROM notes_fts WHERE rowid=(SELECT id FROM notes WHERE path=?)",
            ("10. Meetings/Beta.md",),
        )
        con.commit()
    finally:
        con.close()
    stats = index_vault(db, vault)
    assert stats["fts_repaired"] == 1
    assert stats["unchanged"] == 3


def test_changed_note_updates_primary_and_fts(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    path = write_note(vault, "10. Meetings/Alpha.md", meeting_note("MYPAC", "Alpha"))
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    path.write_text(meeting_note("QualifactsSnowflake", "Alpha"), encoding="utf-8")
    stats = index_vault(db, vault)
    assert stats["updated"] == 1
    con = connect(db)
    try:
        assert fts_paths(con, "QualifactsSnowflake") == ["10. Meetings/Alpha.md"]
        assert fts_paths(con, "MYPAC") == []
    finally:
        con.close()


def test_removed_note_is_deleted(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "10. Meetings/Alpha.md", meeting_note("MYPAC", "Alpha"))
    remove = write_note(vault, "10. Meetings/Beta.md", meeting_note("CARES", "Beta"))
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    remove.unlink()
    stats = index_vault(db, vault)
    assert stats["deleted"] == 1
    con = connect(db)
    try:
        assert fts_paths(con, "CARES") == []
        assert fts_paths(con, "MYPAC") == ["10. Meetings/Alpha.md"]
    finally:
        con.close()


def test_rebuild_recreates_the_index(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "10. Meetings/Alpha.md", meeting_note("MYPAC", "Alpha"))
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    stats = index_vault(db, vault, rebuild=True)
    assert stats["inserted"] == 1


def test_malformed_frontmatter_is_reported(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "bad.md", "---\nfoo: [1, 2\n---\n# Bad")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    con = connect(db)
    try:
        codes = {row[0] for row in con.execute("SELECT code FROM issues")}
        assert "malformed_frontmatter" in codes
        assert len(con.execute("SELECT 1 FROM notes").fetchall()) == 1
    finally:
        con.close()


def test_index_outdated_detected_when_fts_row_missing(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    write_note(vault, "a.md", meeting_note("MYPAC", "A"))
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    con = connect(db)
    try:
        assert detect_index_outdated(con) is False
        con.execute("DELETE FROM notes_fts")
        con.commit()
        assert detect_index_outdated(con) is True
    finally:
        con.close()


def test_duplicate_resolved_paths_are_indexed_once(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    path = write_note(vault, "a.md", meeting_note("MYPAC", "A"))
    record = parse_note(path, vault)
    db = tmp_path / "index.sqlite3"
    stats = index_vault(db, vault, records=[record, record])
    assert stats["inserted"] == 1
    con = connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
    finally:
        con.close()
