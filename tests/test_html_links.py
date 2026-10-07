"""Ticket 02: the one link contract for generated pages."""

from __future__ import annotations

from worksync.html.links import attr, external_url, note_url, page_url, text


def test_note_url_strips_markdown_extension_and_encodes_spaces() -> None:
    assert note_url("WorkSync", "0. System/Work Todo.md") == (
        "obsidian://open?vault=WorkSync&file=0.%20System/Work%20Todo"
    )


def test_page_url_keeps_html_extension() -> None:
    assert page_url("WorkSync", "0. System/Interface/projects.html") == (
        "obsidian://open?vault=WorkSync&file=0.%20System/Interface/projects.html"
    )


def test_vault_name_is_encoded() -> None:
    assert page_url("My Vault", "index.html") == "obsidian://open?vault=My%20Vault&file=index.html"


def test_backslashes_are_normalized() -> None:
    assert note_url("WorkSync", "9. Project\\Project - Eleos.md") == (
        "obsidian://open?vault=WorkSync&file=9.%20Project/Project%20-%20Eleos"
    )


def test_external_url_passes_through_unchanged() -> None:
    url = "https://example.com/a?b=c&d=e"
    assert external_url(url) == url


def test_attr_escapes_quotes_ampersand_and_angle_brackets() -> None:
    assert attr('a&b"c<d') == "a&amp;b&quot;c&lt;d"


def test_text_escapes_without_touching_quotes() -> None:
    assert text('a&b<c "d"') == 'a&amp;b&lt;c "d"'
