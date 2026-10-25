"""Project membership: materialize explicit/alias links into ``note_project_links``.

``note_project_links`` is the sole membership table. ``explicit`` and ``alias``
associations are authoritative (Tier A); an FTS match is relevance only and is
never stored as membership.
"""

from __future__ import annotations

from pathlib import Path

from worksync.context.registry import ProjectRecord, load_projects
from worksync.inventory.index import read_note_properties, replace_membership
from worksync.work.projects import (
    ALIAS,
    AUTHORITATIVE,
    CANDIDATE,
    EXCLUDED_PREFIXES,
    EXPLICIT,
    SUPERSEDED_STATUSES,
    Association,
    associate_note,
)
from worksync.work.repository import WorkIndex

__all__ = [
    "ALIAS",
    "AUTHORITATIVE",
    "CANDIDATE",
    "EXCLUDED_PREFIXES",
    "EXPLICIT",
    "SUPERSEDED_STATUSES",
    "Association",
    "associate_note",
    "build_link_rows",
    "index_associations",
]


def build_link_rows(notes: list[dict], projects: list[ProjectRecord]) -> list[tuple]:
    """Build ``note_project_links`` rows from indexed notes and project identities."""
    rows: list[tuple] = []
    for item in notes:
        for link in associate_note(item["frontmatter"], projects, item["path"]):
            rows.append(
                (
                    item["id"],
                    item["path"],
                    link.project_id,
                    link.method,
                    link.authority,
                    ", ".join(link.matched),
                )
            )
    return rows


def index_associations(
    db_path: str | Path,
    vault: str | Path,
    projects: list[ProjectRecord] | None = None,
    *,
    index: WorkIndex | None = None,
) -> dict[str, int]:
    """Replace all project memberships from the indexed notes. Idempotent."""
    if projects is None:
        if index is None:
            index = WorkIndex.from_vault(vault)
        projects = load_projects(index)
    identified = [project for project in projects if project.project_id]
    notes = read_note_properties(db_path)
    rows = build_link_rows(notes, identified)
    return {"links": replace_membership(db_path, rows)}
