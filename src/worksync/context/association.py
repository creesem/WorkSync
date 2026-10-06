"""Project membership: materialize explicit/alias links into ``note_project_links``.

``note_project_links`` is the sole membership table. ``explicit`` and ``alias``
associations are authoritative (Tier A); an FTS match is relevance only and is
never stored as membership.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from worksync.context.registry import ProjectRecord, canonical_project_name, load_projects
from worksync.inventory.index import read_note_properties, replace_membership
from worksync.work.repository import WorkIndex

EXPLICIT = "explicit"
ALIAS = "alias"
AUTHORITATIVE = "authoritative"
CANDIDATE = "candidate"
EXCLUDED_PREFIXES = ("1. Rough Notes/Krisp Proposals/", "7. Task Notes/Dropped/")
SUPERSEDED_STATUSES = {"archived", "superseded", "dropped"}


def _is_excluded(path: object) -> bool:
    posix = str(path or "").replace("\\", "/").casefold()
    return posix.startswith(tuple(prefix.casefold() for prefix in EXCLUDED_PREFIXES))


def _is_superseded(frontmatter: dict) -> bool:
    status = str(frontmatter.get("status") or "").strip().casefold()
    note_type = str(frontmatter.get("type") or "").strip().casefold()
    return status in SUPERSEDED_STATUSES or note_type == "redirect"


@dataclass(frozen=True)
class Association:
    """One authoritative project membership for a note."""

    project_id: str
    method: str
    authority: str = AUTHORITATIVE
    matched: tuple[str, ...] = ()


def _normalize(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.split("|", 1)[0].split("#", 1)[0]
    return " ".join(canonical_project_name(text).split()).casefold()


def _project_values(frontmatter: dict) -> list[str]:
    values: list[str] = []
    scalar = frontmatter.get("project")
    if isinstance(scalar, str) and scalar.strip():
        values.append(scalar)
    listed = frontmatter.get("projects")
    if isinstance(listed, list):
        values.extend(str(item) for item in listed if str(item).strip())
    elif isinstance(listed, str) and listed.strip():
        values.append(listed)
    return values


def _match_project(value: object, projects: list[ProjectRecord]) -> tuple[str, str] | None:
    target = _normalize(value)
    if not target:
        return None
    for project in projects:
        if target == _normalize(project.name):
            return project.project_id, EXPLICIT
    for project in projects:
        if any(target == _normalize(alias) for alias in project.aliases):
            return project.project_id, ALIAS
    return None


def associate_note(frontmatter: dict, projects: list[ProjectRecord], path: str = "") -> list[Association]:
    """Return the authoritative project memberships for one note's frontmatter.

    A note under an excluded prefix (unreviewed Krisp proposals, dropped tasks) or
    in a superseded/redirect state keeps its memberships but downgrades them to
    candidate, so unreviewed or retired content is never presented as project truth.
    """
    if str(frontmatter.get("type") or "").strip().casefold() == "project":
        return []
    links: dict[str, Association] = {}
    for value in _project_values(frontmatter):
        match = _match_project(value, projects)
        if match is None:
            continue
        project_id, method = match
        links.setdefault(project_id, Association(project_id, method, AUTHORITATIVE, (value,)))
    associations = list(links.values())
    if _is_excluded(path) or _is_superseded(frontmatter):
        associations = [Association(link.project_id, link.method, CANDIDATE, link.matched) for link in associations]
    return associations


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
