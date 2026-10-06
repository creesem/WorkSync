"""ISO 8601 date parsing shared by validation, review, and attention logic."""

from __future__ import annotations

from datetime import datetime


def parse_iso_date(value: object | None) -> datetime | None:
    """Parse an ISO 8601 date or timestamp, returning ``None`` when unparseable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
