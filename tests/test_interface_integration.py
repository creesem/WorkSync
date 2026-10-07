"""Ticket 04: full-interface integration and the no-index proof.

The generated HTML layer is derived presentation state. Building it must write only
into ``0. System/Interface`` and must never make the interface itself part of the
domain model: the single scanner walks only ``*.md``, so no generated ``.html`` may
appear as an indexed note, an FTS row, or a work entity.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main
from worksync.core.paths import GENERATED_INTERFACE_REL
from worksync.inventory.index import connect_readonly, index_vault
from worksync.inventory.parse import scan_vault
from worksync.work.repository import WorkIndex

GENERATED_AT = "2026-01-15T09:00:00+00:00"
GENERATED_ROOT = GENERATED_INTERFACE_REL


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "9. Project/Project - Eleos.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n---\n# Project Eleos\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def _base(vault: Path, runtime: Path) -> list[str]:
    return [
        "interface",
        "build",
        "--vault",
        str(vault),
        "--runtime",
        str(runtime),
        "--vault-name",
        "WorkSync",
        "--today",
        "2026-01-15",
        "--generated-at",
        GENERATED_AT,
    ]


def _pages(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*.html")}


def test_full_interface_build_is_deterministic(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    assert main(_base(vault, runtime)) == 0
    root = vault / GENERATED_ROOT
    first = _pages(root)
    assert {"index.html", "today.html", "projects.html", "team.html"} <= set(first)
    assert any(name.startswith("project/") for name in first)
    assert any(name.startswith("person/") for name in first)

    assert main([*_base(vault, runtime), "--confirm", "--force"]) == 0
    assert _pages(root) == first


def test_generated_html_is_not_indexed_or_scanned(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    scanned_before = {record.path for record in scan_vault(vault)}
    before = WorkIndex.from_vault(vault)
    assert main(_base(vault, runtime)) == 0
    assert list((vault / GENERATED_ROOT).rglob("*.html"))

    after = WorkIndex.from_vault(vault)
    assert after.entities == before.entities
    assert after.counts() == before.counts()

    scanned_after = {record.path for record in scan_vault(vault)}
    assert scanned_after == scanned_before
    assert scanned_after
    assert all(path.endswith(".md") for path in scanned_after)

    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    con = connect_readonly(db)
    try:
        note_ids = {row[0] for row in con.execute("SELECT id FROM notes")}
        note_paths = [row[0] for row in con.execute("SELECT path FROM notes")]
        fts_ids = {row[0] for row in con.execute("SELECT rowid FROM notes_fts")}
        html_fts = con.execute(
            "SELECT COUNT(*) FROM notes_fts f JOIN notes n ON n.id = f.rowid WHERE n.path LIKE '%.html'"
        ).fetchone()[0]
    finally:
        con.close()
    assert note_ids
    assert all(path.endswith(".md") for path in note_paths)
    assert fts_ids == note_ids
    assert html_fts == 0


def test_interface_build_does_not_touch_canonical_notes(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}

    assert main([*_base(vault, runtime), "--dry-run"]) == 0
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before

    assert main(_base(vault, runtime)) == 0
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before
