"""Path and filename sanitization helpers."""

from __future__ import annotations

import re

BAD_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_name(value: str, *, limit: int = 110, fallback: str = "") -> str:
    """Sanitize *value* for use as a filename or vault note name.

    Replaces forbidden characters with ``-``, collapses whitespace, and truncates
    to *limit* characters.
    """
    value = BAD_CHARS.sub("-", value).strip(" .-")
    value = re.sub(r"\s+", " ", value)
    return value[:limit].rstrip() or fallback
