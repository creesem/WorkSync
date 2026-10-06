"""Ticket 06: evidence search with provenance tiers and evidence read."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from worksync.context.association import index_associations
from worksync.context.retrieval import ServiceError, read_evidence, search_evidence
from worksync.inventory.index import connect, index_vault

PROJECT_NOTE = "9. Project/Project - Eleos.md"
MEMBER_NOTE = "10. Meetings/2026-01-01 Kickoff.md"
NON_MEMBER_NOTE = "Notes/unlinked ProgramIds note.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: eleos\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        MEMBER_NOTE,
        '---\ntype: meeting\ndate: 2026-01-01\nproject: "[[Project - Eleos]]"\n'
        "---\n# Kickoff\n\n## Summary\nThe ProgramIds migration completed.\n",
    )
    write_note(
        vault,
        NON_MEMBER_NOTE,
        "---\ntype: reference\n---\n# Unlinked\nSome ProgramIds reference material.\n",
    )


def _build(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Path:
    _seed(vault, write_note)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    return db


def test_project_scoped_search_annotates_authoritative_membership(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    db = _build(vault, write_note, tmp_path)
    result = search_evidence(db, "ProgramIds", project_id="eleos", vault=vault)
    assert [item["path"] for item in result["results"]] == [MEMBER_NOTE]
    hit = result["results"][0]
    assert hit["association"] == {"method": "explicit", "authority": "authoritative", "tier": "A"}
    assert hit["match_scope"] == "body"
    assert hit["stale"] is False
    assert result["index_outdated"] is False


def test_unlinked_fts_hit_is_only_a_candidate(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    result = search_evidence(db, "ProgramIds", vault=vault)
    by_path = {item["path"]: item for item in result["results"]}

    assert by_path[MEMBER_NOTE]["association"]["tier"] == "A"

    candidate = by_path[NON_MEMBER_NOTE]
    assert candidate["association"] == {"method": None, "authority": "candidate", "tier": "B"}


def test_authoritative_only_filter_excludes_candidates(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    db = _build(vault, write_note, tmp_path)
    result = search_evidence(db, "ProgramIds", filters={"authoritative_only": True}, vault=vault)
    assert [item["path"] for item in result["results"]] == [MEMBER_NOTE]


def test_type_filter(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    result = search_evidence(db, "ProgramIds", filters={"types": ["reference"]}, vault=vault)
    assert [item["path"] for item in result["results"]] == [NON_MEMBER_NOTE]


def test_search_reports_per_result_staleness(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    member = vault / MEMBER_NOTE
    member.write_text(member.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")
    result = search_evidence(db, "ProgramIds", project_id="eleos", vault=vault)
    assert result["results"][0]["stale"] is True


def test_empty_query_returns_no_results(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    assert search_evidence(db, "   ", vault=vault)["results"] == []


def test_read_evidence_returns_content_and_provenance(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    db = _build(vault, write_note, tmp_path)
    result = read_evidence(db, "eleos", MEMBER_NOTE, vault=vault)
    assert result["state"] == "ok"
    assert result["source_path"] == MEMBER_NOTE
    assert result["association"] == {"method": "explicit", "authority": "authoritative", "tier": "A"}
    assert result["source_timestamp"] == "2026-01-01"
    assert "ProgramIds migration completed" in result["content"]
    assert result["truncated"] is False


def test_read_evidence_rejects_unknown_unlinked_or_absolute_source(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    db = _build(vault, write_note, tmp_path)
    assert read_evidence(db, "eleos", "Notes/does-not-exist.md", vault=vault)["state"] == "not_found"
    assert read_evidence(db, "eleos", NON_MEMBER_NOTE, vault=vault)["state"] == "not_found"
    assert read_evidence(db, "eleos", str((vault / MEMBER_NOTE).resolve()), vault=vault)["state"] == "not_found"


def test_read_evidence_reports_missing_source(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    (vault / MEMBER_NOTE).unlink()
    result = read_evidence(db, "eleos", MEMBER_NOTE, vault=vault)
    assert result["state"] == "source_missing"
    assert result["content"] is None
    assert result["stale"] is True


def test_read_evidence_enforces_vault_containment(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    con = connect(db)
    try:
        with con:
            con.execute(
                "INSERT INTO notes(path,title,type,status,project,stable_id,priority,content_hash,size,"
                "modified_utc,frontmatter_present,content) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "../outside.md",
                    "Outside",
                    "meeting",
                    "",
                    "",
                    None,
                    "",
                    "0" * 64,
                    1,
                    "2026-01-01T00:00:00+00:00",
                    1,
                    "x",
                ),
            )
            note_id = con.execute("SELECT id FROM notes WHERE path='../outside.md'").fetchone()[0]
            con.execute(
                "INSERT INTO note_project_links VALUES (?,?,?,?,?,?)",
                (note_id, "../outside.md", "eleos", "explicit", "authoritative", ""),
            )
    finally:
        con.close()
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")

    with pytest.raises(ServiceError):
        read_evidence(db, "eleos", "../outside.md", vault=vault)
