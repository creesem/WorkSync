"""Ticket 02: the generated interface writes only into the contained generated zone."""

from __future__ import annotations

from pathlib import Path

import pytest

from worksync.html.generator import GeneratedPage
from worksync.html.writer import generated_zones, write_pages
from worksync.safety.models import MutationError


def _page(name: str = "home", filename: str = "index.html", content: str = "<html>hi</html>") -> GeneratedPage:
    return GeneratedPage(name=name, filename=filename, content=content, sources=())


def _code(excinfo: pytest.ExceptionInfo[MutationError]) -> str:
    return excinfo.value.code


def test_generated_zones_point_inside_the_vault(vault: Path, tmp_path: Path) -> None:
    zones = generated_zones(vault, tmp_path / "var")
    assert zones["generated"] == (vault / "0. System" / "Interface").resolve()
    assert "runtime" in zones


def test_write_pages_creates_page_in_the_generated_zone(vault: Path, tmp_path: Path) -> None:
    zones = generated_zones(vault, tmp_path / "var")
    result = write_pages((_page(),), zones)
    assert result.committed is True
    written = zones["generated"] / "index.html"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == "<html>hi</html>"
    assert result.changes[0]["zone"] == "generated"


def test_write_pages_requires_confirmation_before_overwrite(vault: Path, tmp_path: Path) -> None:
    zones = generated_zones(vault, tmp_path / "var")
    write_pages((_page(content="old"),), zones)
    with pytest.raises(MutationError) as excinfo:
        write_pages((_page(content="new"),), zones)
    assert _code(excinfo) == "needs_confirmation"
    assert (zones["generated"] / "index.html").read_text(encoding="utf-8") == "old"


def test_write_pages_requires_force_after_confirmation(vault: Path, tmp_path: Path) -> None:
    zones = generated_zones(vault, tmp_path / "var")
    write_pages((_page(content="old"),), zones)
    with pytest.raises(MutationError) as excinfo:
        write_pages((_page(content="new"),), zones, confirmed=True)
    assert _code(excinfo) == "needs_force"
    assert (zones["generated"] / "index.html").read_text(encoding="utf-8") == "old"


def test_write_pages_overwrites_with_confirmation_and_force(vault: Path, tmp_path: Path) -> None:
    zones = generated_zones(vault, tmp_path / "var")
    write_pages((_page(content="old"),), zones)
    assert write_pages((_page(content="new"),), zones, confirmed=True, force=True).committed is True
    assert (zones["generated"] / "index.html").read_text(encoding="utf-8") == "new"


def test_write_pages_leaves_no_partial_set_on_containment_escape(vault: Path, tmp_path: Path) -> None:
    zones = generated_zones(vault, tmp_path / "var")
    pages = (_page(filename="index.html", content="ok"), _page(filename="../../escape.html", content="bad"))
    with pytest.raises(MutationError) as excinfo:
        write_pages(pages, zones)
    assert _code(excinfo) == "containment_escape"
    assert not (zones["generated"] / "index.html").exists()


def test_write_pages_never_touches_canonical_notes(vault: Path, tmp_path: Path) -> None:
    note = vault / "9. Project/Project - Eleos.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntype: project\nstatus: active\n---\n# Eleos\n", encoding="utf-8")
    before = note.read_bytes()
    zones = generated_zones(vault, tmp_path / "var")
    write_pages((_page(),), zones)
    assert note.read_bytes() == before
