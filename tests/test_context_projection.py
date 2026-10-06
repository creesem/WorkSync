"""Ticket 07: generated context projection read and staleness."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from worksync.context import projection
from worksync.context.association import index_associations
from worksync.context.projection import get_staleness, read_context
from worksync.inventory.index import connect, index_vault
from worksync.work.repository import WorkIndex

PROJECT_NOTE = "9. Project/Project - Eleos.md"
MEETING_NOTE = "10. Meetings/2026-01-01 Kickoff.md"
GENERATED_AT = "2026-09-20T10:00:00+00:00"


def _project(repo: Path | None) -> str:
    repos = f'repos:\n  - "{repo.as_posix()}"\n' if repo is not None else ""
    return (
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        f"project_id: eleos\naliases:\n  - Eleos Automation\n{repos}---\n# Project - Eleos\n"
    )


def _seed(vault: Path, write_note: Callable[..., Path], repo: Path | None) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(vault, PROJECT_NOTE, _project(repo))
    write_note(
        vault,
        MEETING_NOTE,
        '---\ntype: meeting\ndate: 2026-01-01\nproject: "[[Project - Eleos]]"\n---\n# Kickoff\n',
    )


def _build(vault: Path, write_note: Callable[..., Path], tmp_path: Path, repo: Path | None) -> Path:
    _seed(vault, write_note, repo)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    return db


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_projection(
    repo: Path, sources: dict[str, str], *, body: str = "Working.", generated: str = GENERATED_AT
) -> Path:
    output = repo / ".project"
    output.mkdir(parents=True, exist_ok=True)
    lines = [
        "# WorkSync Project Context — Eleos",
        "",
        f"Generated: {generated}",
        "",
        "## Current State",
        "",
        body,
        "",
        "## Sources",
        "",
        *[f"- {path} (sha256: {digest})" for path, digest in sources.items()],
        "",
        f"<!-- worksync-sources: {json.dumps(sources)} -->",
        "",
    ]
    context = output / "WORKSYNC_CONTEXT.md"
    context.write_text("\n".join(lines), encoding="utf-8")
    return context


def _fresh_sources(vault: Path) -> dict[str, str]:
    return {MEETING_NOTE: _sha(vault / MEETING_NOTE)}


def test_read_context_returns_projection_generation_and_truncation(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    _write_projection(repo, _fresh_sources(vault))

    result = read_context(WorkIndex.from_vault(vault), db, "eleos")

    assert result["state"] == "ok"
    assert result["generated_at"] == GENERATED_AT
    assert result["truncated"] is False
    assert result["stale"] is False
    assert "Working." in result["content"]
    assert result["context_path"] == str(repo / ".project" / "WORKSYNC_CONTEXT.md")


def test_read_context_truncates_oversized_projection(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    _write_projection(repo, _fresh_sources(vault), body="A" * (projection.CONTENT_MAX_BYTES + 1))

    result = read_context(WorkIndex.from_vault(vault), db, "eleos")

    assert result["state"] == "ok"
    assert result["truncated"] is True
    assert len(result["content"].encode("utf-8")) == projection.CONTENT_MAX_BYTES


def test_read_context_reports_missing_projection(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    result = read_context(WorkIndex.from_vault(vault), db, "eleos")
    assert result["state"] == "context_not_built"
    assert result["content"] is None


def test_read_context_reports_project_and_repo_states(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - NoRepo.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: norepo\n---\n# NoRepo\n',
    )
    write_note(
        vault,
        "9. Project/Project - OneRepo.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: onerepo\n'
        'repos:\n  - "C:/repos/only"\n---\n# OneRepo\n',
    )
    write_note(
        vault,
        "9. Project/Project - TwoRepos.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: tworepos\n'
        'repos:\n  - "C:/repos/a"\n  - "C:/repos/b"\n---\n# TwoRepos\n',
    )
    index = WorkIndex.from_vault(vault)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)

    assert read_context(index, db, "norepo")["state"] == "no_repo"
    assert read_context(index, db, "tworepos")["state"] == "ambiguous_repo"
    assert read_context(index, db, "onerepo", repo="C:/repos/other")["state"] == "repo_not_declared"
    assert read_context(index, db, "missing")["state"] == "not_found"


def test_get_staleness_reports_fresh(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    _write_projection(repo, _fresh_sources(vault))
    assert get_staleness(WorkIndex.from_vault(vault), db, "eleos") == {
        "project_id": "eleos",
        "fresh": True,
        "reasons": [],
    }


def test_staleness_detects_changed_source(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    _write_projection(repo, _fresh_sources(vault))
    meeting = vault / MEETING_NOTE
    meeting.write_text(meeting.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")

    result = get_staleness(WorkIndex.from_vault(vault), db, "eleos")
    assert result["fresh"] is False
    assert result["reasons"] == ["source_hash_changed"]


def test_staleness_detects_missing_source(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    sources = _fresh_sources(vault)
    sources["10. Meetings/Deleted.md"] = "0" * 64
    _write_projection(repo, sources)

    result = get_staleness(WorkIndex.from_vault(vault), db, "eleos")
    assert result["reasons"] == ["source_missing"]


def test_staleness_detects_newer_authoritative_evidence(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    _write_projection(repo, {PROJECT_NOTE: _sha(vault / PROJECT_NOTE)})

    result = get_staleness(WorkIndex.from_vault(vault), db, "eleos")
    assert result["reasons"] == ["newer_authoritative_evidence"]


def test_staleness_detects_outdated_index(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    _write_projection(repo, _fresh_sources(vault))
    con = connect(db)
    try:
        with con:
            con.execute(
                "DELETE FROM notes_fts WHERE rowid=(SELECT id FROM notes WHERE path=?)",
                (MEETING_NOTE,),
            )
    finally:
        con.close()

    result = get_staleness(WorkIndex.from_vault(vault), db, "eleos")
    assert result["reasons"] == ["index_outdated"]


def test_staleness_reports_context_not_built(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    result = get_staleness(WorkIndex.from_vault(vault), db, "eleos")
    assert result["fresh"] is False
    assert result["reasons"] == ["context_not_built"]


def test_staleness_does_not_read_sources_outside_the_vault(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    db = _build(vault, write_note, tmp_path, repo)
    outside = tmp_path / "outside.md"
    outside.write_text("not a vault note", encoding="utf-8")
    sources = _fresh_sources(vault)
    sources["../outside.md"] = _sha(outside)
    _write_projection(repo, sources)

    result = get_staleness(WorkIndex.from_vault(vault), db, "eleos")
    assert result["reasons"] == ["source_missing"]
