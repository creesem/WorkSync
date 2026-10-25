"""Canonical project identity and membership at the work layer.

Project identity lives in canonical project notes (``project_id``, ``aliases``,
``repos``); there is no separate registry file. This module is the lower-level
implementation used by both ``work`` and ``context``; it must not import
``context``, ``ingest``, or ``html``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from worksync.work.repository import WorkIndex

VAULT_PROJECTS_DIR = "9. Project"
EXPLICIT = "explicit"
ALIAS = "alias"
AUTHORITATIVE = "authoritative"
CANDIDATE = "candidate"
EXCLUDED_PREFIXES = ("1. Rough Notes/Krisp Proposals/", "7. Task Notes/Dropped/")
SUPERSEDED_STATUSES = {"archived", "superseded", "dropped"}


def canonical_project_name(value: object) -> str:
    """Strip a wikilink wrapper and any ``Project - ``/``Project: `` prefix."""
    clean = re.sub(r"^\[\[|\]\]$", "", str(value or "").strip()).strip()
    return re.sub(r"(?i)^Project\s*[-:]\s*", "", clean).strip()


@dataclass(frozen=True)
class ProjectIdentity:
    """One canonical project identity."""

    project_id: str
    name: str
    path: str
    aliases: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    status: str = ""


@dataclass(frozen=True)
class Association:
    """One authoritative project membership for a note."""

    project_id: str
    method: str
    authority: str = AUTHORITATIVE
    matched: tuple[str, ...] = ()


def load_project_identities(index: WorkIndex, *, view: bool = False) -> list[ProjectIdentity]:
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
    records: list[ProjectIdentity] = []
    for entity in entities:
        if not entity.project_id or not _in_projects_folder(entity.path):
            continue
        records.append(
            ProjectIdentity(
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


def _is_excluded(path: object) -> bool:
    posix = str(path or "").replace("\\", "/").casefold()
    return posix.startswith(tuple(prefix.casefold() for prefix in EXCLUDED_PREFIXES))


def _is_superseded(frontmatter: dict) -> bool:
    status = str(frontmatter.get("status") or "").strip().casefold()
    note_type = str(frontmatter.get("type") or "").strip().casefold()
    return status in SUPERSEDED_STATUSES or note_type == "redirect"


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


def _match_project(value: object, projects: list[ProjectIdentity]) -> tuple[str, str] | None:
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


def associate_note(frontmatter: dict, projects: list[ProjectIdentity], path: str = "") -> list[Association]:
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
