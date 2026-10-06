"""Read a project's generated context projection and report whether it is fresh.

The projection lives at ``<declared repo>/.project/WORKSYNC_CONTEXT.md``. It is a
derived artifact: this module only reads it and the read-only index. It never
accepts a caller-supplied path and never imports a write helper.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from worksync.context.registry import (
    CONTEXT_DIR,
    CONTEXT_FILENAME,
    ProjectRecord,
    load_projects,
)
from worksync.inventory.index import connect_readonly, file_sha256
from worksync.inventory.parse import read_frontmatter
from worksync.work.repository import WorkIndex

PROJECT_YAML = "project.yaml"
CONTENT_MAX_BYTES = 200_000
SOURCES_RE = re.compile(r"<!-- worksync-sources: (.*?) -->", re.DOTALL)
GENERATED_RE = re.compile(r"^Generated:\s*(.+?)\s*$", re.MULTILINE)


def _same_path(left: object, right: object) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return False


def _contained(root: Path, target: Path) -> bool:
    """True when *target* resolves to *root* or a descendant, rejecting escapes."""
    try:
        resolved = target.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def _require_project(index: WorkIndex, project_id: str) -> tuple[ProjectRecord | None, str | None]:
    matches = [record for record in load_projects(index) if record.project_id == project_id]
    if not matches:
        return None, "not_found"
    if len(matches) > 1:
        return None, "ambiguous"
    return matches[0], None


def _resolve_repo(record: ProjectRecord, repo: object) -> tuple[Path | None, str | None]:
    if not record.repos:
        return None, "no_repo"
    if repo is not None:
        declared = next((Path(value) for value in record.repos if _same_path(value, repo)), None)
        if declared is None:
            return None, "repo_not_declared"
        return declared, None
    if len(record.repos) == 1:
        return Path(record.repos[0]), None
    return None, "ambiguous_repo"


def _generated_at(resolved: Path, content: str) -> str | None:
    project_yaml = resolved / CONTEXT_DIR / PROJECT_YAML
    if project_yaml.is_file():
        frontmatter = read_frontmatter(project_yaml.read_text(encoding="utf-8-sig"))
        if frontmatter.present and frontmatter.closed:
            value = str(frontmatter.data.get("generated_at") or "").strip()
            if value:
                return value
    match = GENERATED_RE.search(content)
    return match.group(1) if match else None


def _staleness_of(
    vault: Path,
    context_path: Path,
    db_path: Path | None = None,
    project_id: str | None = None,
) -> dict:
    """Compare a projection's recorded sources against current vault and index state."""
    text = Path(context_path).read_text(encoding="utf-8")
    match = SOURCES_RE.search(text)
    recorded: dict[str, str] = json.loads(match.group(1)) if match else {}
    root = Path(vault).expanduser().resolve()
    changed: list[str] = []
    missing: list[str] = []
    for rel, expected in recorded.items():
        path = root / rel
        if not _contained(root, path) or not path.is_file():
            missing.append(rel)
        elif file_sha256(path) != expected:
            changed.append(rel)
    newer: list[str] = []
    index_incomplete = False
    if db_path is not None and project_id:
        con = connect_readonly(db_path)
        try:
            current = {
                row[0]
                for row in con.execute(
                    "SELECT path FROM note_project_links WHERE project_id=? AND evidence_authority='authoritative'",
                    (project_id,),
                )
            }
            index_incomplete = bool(
                con.execute(
                    "SELECT 1 FROM note_project_links l"
                    " WHERE l.project_id=? AND NOT EXISTS (SELECT 1 FROM notes_fts f WHERE f.rowid=l.note_id)"
                    " LIMIT 1",
                    (project_id,),
                ).fetchone()
            )
        finally:
            con.close()
        newer = sorted(path for path in current if path not in recorded)
    return {
        "stale": bool(changed or missing or newer or index_incomplete),
        "changed": changed,
        "missing": missing,
        "newer": newer,
        "index_outdated": index_incomplete,
    }


def staleness_for_record(
    index: WorkIndex,
    db_path: str | Path,
    record: ProjectRecord,
    repo: object = None,
) -> dict:
    """Report freshness for an already-resolved project record, avoiding a re-list."""
    project_id = record.project_id
    resolved, state = _resolve_repo(record, repo)
    if state:
        return {"project_id": project_id, "fresh": False, "reasons": [state]}
    context_path = resolved / CONTEXT_DIR / CONTEXT_FILENAME
    if not _contained(resolved.resolve(), context_path):
        return {"project_id": project_id, "fresh": False, "reasons": ["containment_violation"]}
    if not context_path.is_file():
        return {"project_id": project_id, "fresh": False, "reasons": ["context_not_built"]}
    raw = _staleness_of(index.root, context_path, db_path=Path(db_path), project_id=project_id)
    reasons: list[str] = []
    if raw["changed"]:
        reasons.append("source_hash_changed")
    if raw["missing"]:
        reasons.append("source_missing")
    if raw["newer"]:
        reasons.append("newer_authoritative_evidence")
    if raw["index_outdated"]:
        reasons.append("index_outdated")
    return {"project_id": project_id, "fresh": not reasons, "reasons": reasons}


def get_staleness(
    index: WorkIndex,
    db_path: str | Path,
    project_id: str,
    repo: object = None,
) -> dict:
    """Report whether a project's generated context is fresh, and why not."""
    record, state = _require_project(index, project_id)
    if state:
        return {"project_id": project_id, "fresh": False, "reasons": [state]}
    return staleness_for_record(index, db_path, record, repo)


def read_context(
    index: WorkIndex,
    db_path: str | Path,
    project_id: str,
    repo: object = None,
) -> dict:
    """Read the WorkSync-managed context projection for a project, never an arbitrary path."""
    record, state = _require_project(index, project_id)
    payload = {
        "project_id": project_id,
        "repo": None,
        "context_path": None,
        "generated_at": None,
        "stale": None,
        "content": None,
        "truncated": False,
        "state": state or "ok",
    }
    if state:
        return payload
    resolved, state = _resolve_repo(record, repo)
    payload["repo"] = str(resolved) if resolved is not None else (str(repo) if repo is not None else None)
    if state:
        payload["state"] = state
        return payload
    context_path = resolved / CONTEXT_DIR / CONTEXT_FILENAME
    payload["context_path"] = str(context_path)
    if not _contained(resolved.resolve(), context_path):
        payload["state"] = "containment_violation"
        return payload
    if not context_path.is_file():
        payload["state"] = "context_not_built"
        return payload
    data = context_path.read_bytes()
    payload["truncated"] = len(data) > CONTENT_MAX_BYTES
    if payload["truncated"]:
        data = data[:CONTENT_MAX_BYTES]
    payload["content"] = data.decode("utf-8", errors="replace")
    payload["generated_at"] = _generated_at(resolved, payload["content"])
    payload["stale"] = not get_staleness(index, db_path, project_id, repo=str(resolved))["fresh"]
    payload["state"] = "ok"
    return payload
