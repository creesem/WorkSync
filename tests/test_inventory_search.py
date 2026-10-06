"""Ticket 02: relevance search with per-result staleness and index-outdated detection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.inventory.index import build_match, connect, index_vault, search


def test_search_returns_ranked_results_with_provenance(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    write_note(
        vault,
        "10. Meetings/ProgramIds.md",
        "---\ntype: meeting\ndate: 2026-02-03\n---\n# ProgramIds migration\nWe finished the ProgramIds migration.\n",
    )
    write_note(vault, "notes/Other.md", "---\ntype: reference\n---\n# Other\nNothing relevant here.\n")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    result = search(db, "ProgramIds", vault=vault)
    assert result["index_outdated"] is False
    assert [item["path"] for item in result["results"]] == ["10. Meetings/ProgramIds.md"]
    hit = result["results"][0]
    assert hit["stale"] is False
    assert hit["source_type"] == "meeting"
    assert hit["source_timestamp"] == "2026-02-03"
    assert hit["indexed_timestamp"]
    assert "ProgramIds" in hit["snippet"]


def test_changed_source_is_stale(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    path = write_note(vault, "a.md", "---\ntype: reference\n---\n# A\nMYPAC body\n")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    path.write_text("---\ntype: reference\n---\n# A\nMYPAC changed body\n", encoding="utf-8")
    result = search(db, "MYPAC", vault=vault)
    assert result["results"][0]["stale"] is True


def test_missing_source_is_stale(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    path = write_note(vault, "a.md", "---\ntype: reference\n---\n# A\nMYPAC body\n")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    path.unlink()
    result = search(db, "MYPAC", vault=vault)
    assert result["results"][0]["stale"] is True


def test_index_outdated_is_surfaced(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "a.md", "---\ntype: reference\n---\n# A\nMYPAC body\n")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    con = connect(db)
    try:
        con.execute("DELETE FROM notes_fts")
        con.commit()
    finally:
        con.close()
    result = search(db, "MYPAC", vault=vault)
    assert result["index_outdated"] is True


def test_limit_sets_truncated_flag(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    for index in range(3):
        write_note(vault, f"n{index}.md", f"---\ntype: reference\n---\n# N{index}\nMYPAC body {index}\n")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    result = search(db, "MYPAC", limit=2, vault=vault)
    assert len(result["results"]) == 2
    assert result["truncated"] is True


def test_source_timestamp_falls_back_to_filename(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "2026-03-04 review.md", "---\ntype: reference\n---\n# Review\nMYPAC recap\n")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    result = search(db, "MYPAC", vault=vault)
    assert result["results"][0]["source_timestamp"] == "2026-03-04"


def test_non_meeting_type_maps_to_document(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "a.md", "---\ntype: reference\n---\n# A\nMYPAC body\n")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    assert search(db, "MYPAC", vault=vault)["results"][0]["source_type"] == "document"


def test_empty_query_returns_no_results(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "a.md", "---\ntype: reference\n---\n# A\nMYPAC body\n")
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    result = search(db, "   ", vault=vault)
    assert result["results"] == []
    assert result["index_outdated"] is False


def test_build_match_neutralizes_fts_syntax() -> None:
    assert build_match("C#") == '"C"'
    assert build_match("treatment-plan") == '"treatment" OR "plan"'
    assert build_match("alpha beta", match_all=True) == '"alpha" AND "beta"'
    assert build_match("") == ""
