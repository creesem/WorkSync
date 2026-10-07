"""Resolve and persist the current reviewer for canonical writes.

The reviewer is never hardcoded: an explicit ``--reviewer`` wins and is remembered, else
the runtime store is used, else the configured ``reviewer``. With none of the three the
resolution fails loudly so a canonical write can never invent an identity.
"""

from __future__ import annotations

import json
from pathlib import Path

from worksync.safety.derived import write_json

REVIEWER_FILENAME = "reviewer.json"


class ReviewerError(ValueError):
    """Raised when no current reviewer can be resolved."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def reviewer_store_path(runtime_root: str | Path) -> Path:
    """Return the runtime path holding the remembered reviewer."""
    return Path(runtime_root).expanduser().resolve() / REVIEWER_FILENAME


def load_reviewer(runtime_root: str | Path) -> str | None:
    """Return the remembered reviewer, or ``None`` when none is stored."""
    path = reviewer_store_path(runtime_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        value = str(data.get("reviewer") or "").strip()
        return value or None
    return None


def store_reviewer(runtime_root: str | Path, reviewer: str) -> str:
    """Persist *reviewer* and return it, refusing an empty name."""
    name = str(reviewer).strip()
    if not name:
        raise ReviewerError("missing_reviewer", "A reviewer name is required.")
    write_json(runtime_root, REVIEWER_FILENAME, {"reviewer": name})
    return name


def resolve_reviewer(
    runtime_root: str | Path,
    *,
    explicit: str | None = None,
    configured: str | None = None,
    remember: bool = True,
) -> str:
    """Resolve the current reviewer: explicit (and optionally remembered) > runtime > configured."""
    if explicit is not None and str(explicit).strip():
        return store_reviewer(runtime_root, explicit) if remember else str(explicit).strip()
    stored = load_reviewer(runtime_root)
    if stored:
        return stored
    if configured is not None and str(configured).strip():
        return str(configured).strip()
    raise ReviewerError(
        "missing_reviewer",
        "No current reviewer is set; pass --reviewer or set 'reviewer' in the machine config.",
    )
