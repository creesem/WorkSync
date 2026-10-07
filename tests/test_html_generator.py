"""Ticket 02: deterministic, self-contained home page rendering."""

from __future__ import annotations

from datetime import UTC, date, datetime

from worksync.html.generator import EntityLink, build_home, build_pages

TODAY = date(2026, 1, 15)
GENERATED_AT = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
PROJECT = EntityLink(title="Project Eleos", note_path="9. Project/Project - Eleos.md", status="active")
PERSON = EntityLink(title="Myles", note_path="People/Myles.md", status="active")


def _home(**overrides):
    data = dict(vault_name="WorkSync", today=TODAY, generated_at=GENERATED_AT)
    data.update(overrides)
    return build_home(**data)


def test_home_page_identity() -> None:
    page = _home()
    assert page.name == "home"
    assert page.filename == "index.html"
    assert page.content.startswith("<!DOCTYPE html>")


def test_home_is_deterministic() -> None:
    assert _home(projects=(PROJECT,)).content == _home(projects=(PROJECT,)).content


def test_home_changes_with_generated_at() -> None:
    later = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    assert _home(generated_at=later).content != _home().content
    assert "2026-01-15T10:00:00+00:00" in _home(generated_at=later).content


def test_home_carries_visible_generated_marker() -> None:
    assert "do not edit" in _home().content


def test_home_carries_provenance_metadata() -> None:
    content = _home(projects=(PROJECT,)).content
    assert '<meta name="generator" content="worksync">' in content
    assert '<meta name="worksync-reference-date" content="2026-01-15">' in content
    assert "2026-01-15T09:00:00+00:00" in content
    assert "9. Project/Project - Eleos.md" in content


def test_home_links_to_canonical_note_via_obsidian_uri() -> None:
    content = _home(projects=(PROJECT,)).content
    assert "obsidian://open?vault=WorkSync&amp;file=9.%20Project/Project%20-%20Eleos" in content


def test_home_renders_external_links_as_absolute_urls() -> None:
    content = _home(external_links=(("Obsidian help", "https://help.obsidian.md"),)).content
    assert 'href="https://help.obsidian.md"' in content
    assert "Obsidian help" in content


def test_home_escapes_entity_titles() -> None:
    evil = EntityLink(title="<script>alert(1)</script>", note_path="X.md")
    content = _home(projects=(evil,)).content
    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content


def test_home_has_no_script_or_form() -> None:
    content = _home(projects=(PROJECT,), people=(PERSON,)).content
    assert "<script" not in content.lower()
    assert "<form" not in content.lower()


def test_home_sources_are_sorted_and_unique() -> None:
    page = _home(projects=(PROJECT,), people=(PERSON,))
    assert page.sources == ("9. Project/Project - Eleos.md", "People/Myles.md")


def test_home_renders_with_empty_inputs() -> None:
    page = _home()
    assert page.sources == ()
    assert page.content.rstrip().endswith("</html>")


def test_build_pages_returns_the_home_page() -> None:
    pages = build_pages(vault_name="WorkSync", today=TODAY, generated_at=GENERATED_AT)
    assert [page.filename for page in pages] == ["index.html"]
