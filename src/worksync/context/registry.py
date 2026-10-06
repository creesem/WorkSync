"""Canonical project identity and resolution.

Project identity lives in canonical project notes (``project_id``, ``aliases``,
``repos``); there is no separate registry file. Resolution never registers
anything and reports ``resolved`` / ``ambiguous`` / ``not_found`` explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from worksync.work.repository import WorkIndex

CONTEXT_DIR = ".project"
CONTEXT_FILENAME = "WORKSYNC_CONTEXT.md"
VAULT_PROJECTS_DIR = "9. Project"


def canonical_project_name(value: object) -> str:
    """Strip a wikilink wrapper and any ``Project - ``/``Project: `` prefix."""
    clean = re.sub(r"^\[\[|\]\]$", "", str(value or "").strip()).strip()
    return re.sub(r"(?i)^Project\s*[-:]\s*", "", clean).strip()


def _normalize(value: object) -> str:
    return " ".join(canonical_project_name(value).split()).casefold()


@dataclass(frozen=True)
class ProjectRecord:
    """One canonical project identity."""

    project_id: str
    name: str
    path: str
    aliases: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    status: str = ""


def load_projects(index: WorkIndex, *, view: bool = False) -> list[ProjectRecord]:
    """Return canonical project identities from the work index.

    ``view=True`` uses the error-free entities a view shows; the default includes
    every project entity so identity resolution is never blocked by an unrelated
    validation error.

    Only notes under the canonical projects folder that carry a ``project_id`` are
    project identities. Imported or exported copies elsewhere in the vault and
    ``type: project`` notes without an id are not identities, so resolution never
    reports a copy as ambiguous and never resolves an unidentified note.
    """
    entities = index.view_entities("project") if view else index.list_type("project")
    records: list[ProjectRecord] = []
    for entity in entities:
        if not entity.project_id or not _in_projects_folder(entity.path):
            continue
        records.append(
            ProjectRecord(
                project_id=entity.project_id or "",
                name=canonical_project_name(entity.title),
                path=entity.path,
                aliases=tuple(entity.aliases),
                search_terms=tuple(getattr(entity, "search_terms", ())),
                repos=tuple(getattr(entity, "repos", ())),
                status=entity.status,
            )
        )
    return records


def _in_projects_folder(path: str) -> bool:
    """True when a vault-relative path lives under the canonical projects folder."""
    parts = PurePosixPath(str(path).replace("\\", "/")).parts
    return bool(parts) and parts[0].casefold() == VAULT_PROJECTS_DIR.casefold()


def resolve_project(index: WorkIndex, hint: dict | None) -> dict:
    """Resolve a project hint to one canonical ``project_id`` without registering anything."""
    hint = hint or {}
    records = load_projects(index)

    project_id = str(hint.get("project_id") or "").strip()
    if project_id:
        matches = [record for record in records if record.project_id == project_id]
        if not matches:
            return {"status": "not_found"}
        if len(matches) > 1:
            return {"status": "ambiguous", "candidates": _candidates(matches)}
        return {"status": "resolved", "project_id": matches[0].project_id}

    matches: dict[str, ProjectRecord] = {}
    for key in ("name", "alias"):
        value = str(hint.get(key) or "").strip()
        if not value:
            continue
        for record in records:
            if _normalize(value) == _normalize(record.name) or any(
                _normalize(value) == _normalize(alias) for alias in record.aliases
            ):
                matches[record.path] = record
    for key in ("repo_path", "cwd"):
        value = str(hint.get(key) or "").strip()
        if not value:
            continue
        for record in records:
            if _within_repos(value, record.repos):
                matches[record.path] = record

    if not matches:
        return {"status": "not_found"}
    if len(matches) > 1:
        return {"status": "ambiguous", "candidates": _candidates(matches.values())}
    record = next(iter(matches.values()))
    return {"status": "resolved", "project_id": record.project_id or None}


def list_projects(index: WorkIndex, *, db_path: str | Path | None = None) -> list[dict]:
    """List projects as a view, with registered repo and context availability.

    When ``db_path`` names an existing index, ``context_stale`` reports whether a
    present projection is out of date; otherwise it stays ``None``.
    """
    listing: list[dict] = []
    for record in load_projects(index, view=True):
        repo = record.repos[0] if len(record.repos) == 1 else None
        context_available = False
        if repo is not None:
            context_available = (Path(repo) / CONTEXT_DIR / CONTEXT_FILENAME).is_file()
        context_stale = None
        if context_available and db_path is not None and Path(db_path).is_file():
            from worksync.context.projection import staleness_for_record

            context_stale = not staleness_for_record(index, db_path, record, repo=repo)["fresh"]
        listing.append(
            {
                "project_id": record.project_id or None,
                "name": record.name,
                "title": record.name,
                "aliases": list(record.aliases),
                "status": record.status,
                "registered_repo": repo,
                "context_available": context_available,
                "context_stale": context_stale,
                "path": record.path,
            }
        )
    return listing


def _candidates(records: object) -> list[dict]:
    seen: dict[str, dict] = {}
    for record in records:
        key = record.project_id or record.path
        seen.setdefault(key, {"project_id": record.project_id or None, "name": record.name})
    return list(seen.values())


def _within_repos(value: str, repos: tuple[str, ...]) -> bool:
    try:
        target = Path(value).expanduser().resolve()
    except OSError:
        return False
    for declared in repos:
        try:
            root = Path(declared).expanduser().resolve()
        except OSError:
            continue
        if target == root or root in target.parents:
            return True
    return False
