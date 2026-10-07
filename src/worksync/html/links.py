"""The one link contract for generated pages.

Every internal link is an ``obsidian://open`` URI carrying the vault name and the
vault-relative target path; the form was proven by the G4 prototype in HTML Reader.
The ``.html`` extension is required for generated-page targets and optional for
Markdown notes. External links are plain absolute URLs. All dynamic text that becomes
an attribute or a text node is HTML-escaped here, so no page builder re-implements it.
"""

from __future__ import annotations

import html
from urllib.parse import quote

OBSIDIAN_OPEN = "obsidian://open"


def note_url(vault_name: str, note_path: str) -> str:
    """Return an ``obsidian://`` URL for a Markdown note, stripping the ``.md`` extension."""
    path = _normalize(note_path)
    if path.lower().endswith(".md"):
        path = path[:-3]
    return _obsidian(vault_name, path)


def page_url(vault_name: str, page_path: str) -> str:
    """Return an ``obsidian://`` URL for a generated ``.html`` page, keeping its extension."""
    return _obsidian(vault_name, _normalize(page_path))


def external_url(url: str) -> str:
    """Return an absolute external URL unchanged."""
    return url


def attr(value: object) -> str:
    """Escape a value for use inside an HTML attribute (quoted)."""
    return html.escape(str(value), quote=True)


def text(value: object) -> str:
    """Escape a value for use as HTML text content."""
    return html.escape(str(value), quote=False)


def _normalize(path: str) -> str:
    return str(path).replace("\\", "/")


def _obsidian(vault_name: str, file_param: str) -> str:
    return f"{OBSIDIAN_OPEN}?vault={quote(str(vault_name))}&file={quote(file_param, safe='/')}"
