"""Evidence search and read: relevance ranked, annotated with membership provenance.

FTS rank establishes retrieval relevance only; project membership comes solely from
``note_project_links``. A hit with no authoritative membership is a Tier B candidate and
is never project truth. The source of ``read_evidence`` is resolved through the index,
never a caller-supplied path, and is contained to the vault.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from worksync.inventory.index import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    SNIPPET_CHARS,
    build_match,
    connect_readonly,
    detect_index_outdated,
    file_sha256,
    per_result_stale,
)

AUTHORITY_ORDER = {"authoritative": 0, "candidate": 1}
METHOD_ORDER = {"explicit": 0, "alias": 1, "manual": 2, "fts": 3}
MEETING_TYPES = {"meeting", "meeting-prep"}
MARK_START = "\x01"
MARK_END = "\x02"
CONTENT_MAX_BYTES = 200_000
FILTER_KEYS = {"authoritative_only", "types"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class ServiceError(RuntimeError):
    """Raised when a read cannot be satisfied without violating the read-only boundary."""


def _normalize_filters(filters: dict | None) -> dict:
    filters = filters or {}
    unknown = set(filters) - FILTER_KEYS
    if unknown:
        raise ValueError(f"Unsupported search filter(s): {', '.join(sorted(unknown))}")
    types = filters.get("types")
    if types is not None:
        if not isinstance(types, list) or not all(isinstance(value, str) for value in types):
            raise ValueError("'types' filter must be a list of strings.")
        types = {value.strip().lower() for value in types if value.strip()}
    return {"authoritative_only": bool(filters.get("authoritative_only")), "types": types or set()}


def _cap_limit(limit: object, max_limit: int | None) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    value = max(1, value)
    return min(value, max_limit) if max_limit is not None else value


def _links(con: object, note_id: int) -> list[dict]:
    return [
        {
            "project_id": row[0],
            "association_method": row[1],
            "evidence_authority": row[2],
            "matched": row[3],
        }
        for row in con.execute(
            "SELECT project_id, association_method, evidence_authority, matched"
            " FROM note_project_links WHERE note_id=?",
            (note_id,),
        )
    ]


def _best_link(links: list[dict], project_id: str | None) -> dict | None:
    if project_id is not None:
        candidates = [link for link in links if link["project_id"] == project_id]
    else:
        projects = {link["project_id"] for link in links}
        if len(projects) != 1:
            return None
        candidates = [link for link in links if link["project_id"] == projects.pop()]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda link: (
            AUTHORITY_ORDER.get(link["evidence_authority"], 9),
            METHOD_ORDER.get(link["association_method"], 9),
        ),
    )


def _indexed_timestamp(con: object) -> str | None:
    row = con.execute("SELECT value FROM metadata WHERE key='generated_utc'").fetchone()
    return str(row[0]) if row else None


def _properties(con: object, note_id: int) -> dict:
    values: dict = {}
    for key, value_json in con.execute("SELECT key, value_json FROM properties WHERE note_id=?", (note_id,)):
        try:
            values[key] = json.loads(value_json)
        except ValueError:
            values[key] = value_json
    return values


def _source_timestamp(properties: dict, path: str) -> str | None:
    for key in ("date", "meeting_date", "source_date"):
        value = str(properties.get(key) or "").strip()
        if DATE_RE.match(value):
            return value
    match = FILENAME_DATE_RE.search(Path(path).stem)
    return match.group(1) if match else None


def _body_start(marked: str) -> int:
    lines = marked.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return sum(len(line) for line in lines[: index + 1])
    return 0


def _unmark(text: str) -> str:
    return text.replace(MARK_START, "").replace(MARK_END, "")


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _snippet_around(body_marked: str, mark_index: int) -> str:
    start = max(0, mark_index - SNIPPET_CHARS // 2)
    prefix = "… " if start > 0 else ""
    suffix = " …" if start + SNIPPET_CHARS < len(body_marked) else ""
    budget = SNIPPET_CHARS - len(prefix) - len(suffix)
    text = _collapse(_unmark(body_marked[start : start + budget]))
    return prefix + text + suffix


def _snippet_from_body_start(body_marked: str) -> str:
    lines = _unmark(body_marked).splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].lstrip().startswith("#"):
        lines.pop(0)
    text = _collapse(" ".join(lines))
    if len(text) > SNIPPET_CHARS:
        return text[: SNIPPET_CHARS - 2].rstrip() + " …"
    return text


def _snippet_and_scope(snippet: object, body_marked: str, title_marked: str) -> tuple[str, str]:
    fallback = str(snippet or "")[:SNIPPET_CHARS]
    body_start = _body_start(body_marked)
    body = body_marked[body_start:]
    if MARK_START in body:
        return _snippet_around(body, body.index(MARK_START)), "body"
    scope = "title" if MARK_START in title_marked else "frontmatter"
    body_text = _snippet_from_body_start(body) if body_start else ""
    return (body_text or fallback), scope


def _annotate(link: dict | None) -> dict:
    authority = link["evidence_authority"] if link else "candidate"
    return {
        "method": link["association_method"] if link else None,
        "authority": authority,
        "tier": "A" if authority == "authoritative" else "B",
    }


def search_evidence(
    db_path: str | Path,
    query: str,
    *,
    project_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    filters: dict | None = None,
    vault: str | Path | None = None,
    max_limit: int | None = MAX_LIMIT,
) -> dict:
    """Search indexed evidence, optionally project-scoped, preserving provenance."""
    active_filters = _normalize_filters(filters)
    active_limit = _cap_limit(limit, max_limit)
    result: dict = {
        "project_id": project_id,
        "query": query,
        "results": [],
        "truncated": False,
        "index_outdated": False,
    }
    match = build_match(query)
    con = connect_readonly(db_path)
    try:
        result["index_outdated"] = detect_index_outdated(con)
        if not match:
            return result
        indexed = _indexed_timestamp(con)
        params: list[object] = [MARK_START, MARK_END, MARK_START, MARK_END, match]
        scope = ""
        if project_id is not None:
            scope = " AND EXISTS (SELECT 1 FROM note_project_links l WHERE l.note_id=notes.id AND l.project_id=?)"
            params.append(project_id)
        params.append(active_limit + 1)
        rows = con.execute(
            "SELECT notes.id, notes.path, notes.title, notes.type, bm25(notes_fts),"
            " snippet(notes_fts, 1, '', '', ' … ', 20),"
            " highlight(notes_fts, 1, ?, ?), highlight(notes_fts, 0, ?, ?), notes.content_hash"
            " FROM notes_fts JOIN notes ON notes.id=notes_fts.rowid"
            " WHERE notes_fts MATCH ?" + scope + " ORDER BY bm25(notes_fts) LIMIT ?",
            params,
        ).fetchall()
        result["truncated"] = len(rows) > active_limit
        for note_id, path, title, note_type, score, snippet, body_marked, title_marked, content_hash in rows[
            :active_limit
        ]:
            link = _best_link(_links(con, note_id), project_id)
            provenance = _annotate(link)
            if active_filters["authoritative_only"] and provenance["authority"] != "authoritative":
                continue
            normalized_type = str(note_type or "").strip().lower()
            if active_filters["types"] and normalized_type not in active_filters["types"]:
                continue
            snippet_text, match_scope = _snippet_and_scope(snippet, body_marked, title_marked)
            result["results"].append(
                {
                    "source_id": path,
                    "source_path": path,
                    "path": path,
                    "title": title,
                    "type": note_type,
                    "source_type": "meeting" if normalized_type in MEETING_TYPES else "document",
                    "score": score,
                    "snippet": snippet_text,
                    "match_scope": match_scope,
                    "association": provenance,
                    "source_timestamp": _source_timestamp(_properties(con, note_id), path),
                    "indexed_timestamp": indexed,
                    "stale": per_result_stale(vault, path, content_hash),
                }
            )
        return result
    finally:
        con.close()


def _evidence_not_found(project_id: str, source_id: str) -> dict:
    return {
        "project_id": project_id,
        "source_id": source_id,
        "source_path": source_id,
        "title": None,
        "type": None,
        "source_type": None,
        "source_timestamp": None,
        "indexed_timestamp": None,
        "association": None,
        "stale": None,
        "content": None,
        "truncated": False,
        "state": "not_found",
    }


def read_evidence(
    db_path: str | Path,
    project_id: str,
    source_id: str,
    *,
    vault: str | Path,
) -> dict:
    """Read one project-linked source, resolved through the index, never a caller path."""
    vault = Path(vault)
    normalized = str(source_id or "").replace("\\", "/").lstrip("/")
    if not normalized or Path(normalized).is_absolute():
        return _evidence_not_found(project_id, normalized)
    con = connect_readonly(db_path)
    try:
        row = con.execute(
            "SELECT id, path, title, type, content_hash FROM notes WHERE path=?", (normalized,)
        ).fetchone()
        if row is None:
            return _evidence_not_found(project_id, normalized)
        note_id, path, title, note_type, content_hash = row
        link = _best_link(_links(con, note_id), project_id)
        if link is None:
            return _evidence_not_found(project_id, normalized)
        indexed = _indexed_timestamp(con)
        properties = _properties(con, note_id)
    finally:
        con.close()
    target = (vault / path).resolve()
    root = vault.resolve()
    if target != root and root not in target.parents:
        raise ServiceError(f"Indexed path escapes the configured vault: {path}")
    state = "source_missing"
    content = None
    truncated = False
    stale = True
    if target.is_file():
        data = target.read_bytes()
        truncated = len(data) > CONTENT_MAX_BYTES
        if truncated:
            data = data[:CONTENT_MAX_BYTES]
        content = data.decode("utf-8", errors="replace")
        stale = file_sha256(target) != content_hash
        state = "ok"
    return {
        "project_id": project_id,
        "source_id": path,
        "source_path": path,
        "title": title,
        "type": note_type,
        "source_type": "meeting" if str(note_type or "").strip().lower() in MEETING_TYPES else "document",
        "source_timestamp": _source_timestamp(properties, path),
        "indexed_timestamp": indexed,
        "association": _annotate(link),
        "stale": stale,
        "content": content,
        "truncated": truncated,
        "state": state,
    }
