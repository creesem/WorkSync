"""SQLite/FTS index over :class:`IndexRecord`.

Consumes parsed records and preserves the sha256 content hash, per-note incremental
update, the ``fts_repaired`` backfill for an unchanged note missing its FTS row, and
``index_outdated`` detection. Build paths open the index read-write; consumers open
it ``mode=ro``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from worksync.inventory.parse import IndexRecord, scan_vault
from worksync.inventory.validate import structural_issues

INDEX_RELATIVE = Path("data") / "work-sync-index.sqlite3"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
SNIPPET_CHARS = 240
MEETING_TYPES = {"meeting", "meeting-prep"}
TOKEN_RE = re.compile(r"[0-9A-Za-z_]+")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notes(
 id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
 type TEXT, status TEXT, project TEXT, stable_id TEXT, priority TEXT,
 content_hash TEXT NOT NULL, size INTEGER NOT NULL, modified_utc TEXT NOT NULL,
 frontmatter_present INTEGER NOT NULL, content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS properties(
 note_id INTEGER NOT NULL REFERENCES notes(id), key TEXT NOT NULL, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS headings(
 note_id INTEGER NOT NULL REFERENCES notes(id), level INTEGER NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS links(
 note_id INTEGER NOT NULL REFERENCES notes(id), target TEXT NOT NULL, alias TEXT);
CREATE TABLE IF NOT EXISTS tasks(
 note_id INTEGER NOT NULL REFERENCES notes(id), line INTEGER NOT NULL,
 completed INTEGER NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS issues(
 note_id INTEGER REFERENCES notes(id), path TEXT NOT NULL, severity TEXT NOT NULL,
 code TEXT NOT NULL, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type);
CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
CREATE INDEX IF NOT EXISTS idx_properties_key ON properties(key);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target);
CREATE INDEX IF NOT EXISTS idx_issues_code ON issues(code);
CREATE TABLE IF NOT EXISTS note_project_links(
 note_id INTEGER NOT NULL REFERENCES notes(id), path TEXT NOT NULL, project_id TEXT NOT NULL,
 association_method TEXT NOT NULL, evidence_authority TEXT NOT NULL, matched TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_note_project_links_project ON note_project_links(project_id);
CREATE INDEX IF NOT EXISTS idx_note_project_links_note ON note_project_links(note_id);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, content, tokenize = 'porter unicode61');
"""


def index_path(runtime_root: str | Path) -> Path:
    """Return the derived index path under the runtime root."""
    return Path(runtime_root) / INDEX_RELATIVE


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the index read-write (build paths only)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """Open the index read-only so an accidental write fails instead of mutating state."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Index not found: {path}")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def read_note_properties(db_path: str | Path) -> list[dict]:
    """Read each note's ``id``, ``path``, and frontmatter properties, read-only."""
    con = connect_readonly(db_path)
    try:
        properties: dict[int, dict] = {}
        for note_id, key, value_json in con.execute("SELECT note_id, key, value_json FROM properties"):
            try:
                value = json.loads(value_json)
            except ValueError:
                value = value_json
            properties.setdefault(note_id, {})[key] = value
        return [
            {"id": note_id, "path": path, "frontmatter": properties.get(note_id, {})}
            for note_id, path in con.execute("SELECT id, path FROM notes")
        ]
    finally:
        con.close()


def replace_membership(db_path: str | Path, rows: list[tuple]) -> int:
    """Replace the derived ``note_project_links`` table and return its row count."""
    db_path = Path(db_path)
    con = connect(db_path)
    try:
        con.executescript(SCHEMA)
        with con:
            con.execute("DELETE FROM note_project_links")
            con.executemany("INSERT INTO note_project_links VALUES (?,?,?,?,?,?)", rows)
        return len(rows)
    finally:
        con.close()


def build_match(query: object, *, match_all: bool = False) -> str:
    """Build a safe FTS5 MATCH expression from free text.

    FTS5 treats characters such as ``#`` and ``-`` as query syntax, so raw user text
    can raise a syntax error. Terms are extracted and quoted so ``C#`` becomes
    ``"C"`` and ``treatment-plan`` becomes ``"treatment" OR "plan"``.
    """
    terms = [token for token in TOKEN_RE.findall(str(query or "")) if token]
    if not terms:
        return ""
    joiner = " AND " if match_all else " OR "
    return joiner.join(f'"{term}"' for term in terms)


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def per_result_stale(vault: str | Path | None, path: str, content_hash: str) -> bool:
    """True when the indexed source changed or disappeared since indexing."""
    if vault is None:
        return False
    target = Path(vault) / path
    if not target.is_file():
        return True
    return file_sha256(target) != content_hash


def detect_index_outdated(con: sqlite3.Connection) -> bool:
    """True when an indexed note has no ``notes_fts`` row, so search would miss it."""
    row = con.execute(
        "SELECT 1 FROM notes n WHERE NOT EXISTS (SELECT 1 FROM notes_fts f WHERE f.rowid = n.id) LIMIT 1"
    ).fetchone()
    return row is not None


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return json.dumps(value, ensure_ascii=False, default=str)


def _note_values(record: IndexRecord) -> tuple:
    frontmatter = record.frontmatter
    return (
        record.path,
        record.title,
        _as_text(frontmatter.get("type")),
        _as_text(frontmatter.get("status")),
        _as_text(frontmatter.get("project")) or "",
        _as_text(frontmatter.get("id")),
        _as_text(frontmatter.get("priority")) or "",
        record.content_hash,
        record.size,
        record.modified_utc,
        int(record.frontmatter_present),
        record.content,
    )


def _insert_children(con: sqlite3.Connection, note_id: int, record: IndexRecord) -> None:
    con.executemany(
        "INSERT INTO properties VALUES (?,?,?)",
        [
            (note_id, key, json.dumps(value, ensure_ascii=False, default=str))
            for key, value in record.frontmatter.items()
        ],
    )
    con.executemany(
        "INSERT INTO headings VALUES (?,?,?)",
        [(note_id, level, text) for level, text in record.headings],
    )
    con.executemany("INSERT INTO links VALUES (?,?,?)", [(note_id, target, alias) for target, alias in record.links])
    con.executemany(
        "INSERT INTO tasks VALUES (?,?,?,?)",
        [(note_id, line, int(done), text) for done, text, line in record.tasks],
    )


def _clear_children(con: sqlite3.Connection, note_id: int) -> None:
    for table in ("properties", "headings", "links", "tasks"):
        con.execute(f"DELETE FROM {table} WHERE note_id=?", (note_id,))


def _fts_store(con: sqlite3.Connection, note_id: int, record: IndexRecord) -> None:
    con.execute("DELETE FROM notes_fts WHERE rowid=?", (note_id,))
    con.execute("INSERT INTO notes_fts(rowid, title, content) VALUES (?,?,?)", (note_id, record.title, record.content))


def _insert_note(con: sqlite3.Connection, record: IndexRecord) -> int:
    cursor = con.execute(
        "INSERT INTO notes(path,title,type,status,project,stable_id,priority,content_hash,size,modified_utc,"
        "frontmatter_present,content) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        _note_values(record),
    )
    note_id = cursor.lastrowid
    assert note_id is not None
    _insert_children(con, note_id, record)
    _fts_store(con, note_id, record)
    return note_id


def _update_note(con: sqlite3.Connection, note_id: int, record: IndexRecord) -> None:
    _clear_children(con, note_id)
    con.execute(
        "UPDATE notes SET path=?,title=?,type=?,status=?,project=?,stable_id=?,priority=?,content_hash=?,size=?,"
        "modified_utc=?,frontmatter_present=?,content=? WHERE id=?",
        (*_note_values(record), note_id),
    )
    _insert_children(con, note_id, record)
    _fts_store(con, note_id, record)


def _delete_note(con: sqlite3.Connection, note_id: int) -> None:
    _clear_children(con, note_id)
    con.execute("DELETE FROM issues WHERE note_id=?", (note_id,))
    con.execute("DELETE FROM note_project_links WHERE note_id=?", (note_id,))
    con.execute("DELETE FROM notes WHERE id=?", (note_id,))
    con.execute("DELETE FROM notes_fts WHERE rowid=?", (note_id,))


def _replace_issues(con: sqlite3.Connection, issues: list[dict[str, str]]) -> None:
    con.execute("DELETE FROM issues")
    ids = {path: note_id for note_id, path in con.execute("SELECT id,path FROM notes")}
    con.executemany(
        "INSERT INTO issues VALUES (?,?,?,?,?)",
        [
            (ids.get(issue["path"]), issue["path"], issue["severity"], issue["code"], issue["message"])
            for issue in issues
        ],
    )


def _set_metadata(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO metadata(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _metadata(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return str(row[0]) if row else None


def index_vault(
    db_path: str | Path,
    vault: str | Path,
    records: list[IndexRecord] | None = None,
    issues: list[dict[str, str]] | None = None,
    *,
    rebuild: bool = False,
) -> dict[str, int]:
    """Build or incrementally update the index. Returns per-outcome counts."""
    db_path = Path(db_path)
    vault = Path(vault).expanduser().resolve()
    if records is None:
        records = scan_vault(vault)
    if issues is None:
        issues = structural_issues(records)
    if rebuild and db_path.exists():
        db_path.unlink()
    con = connect(db_path)
    try:
        con.executescript(SCHEMA)
        stats = {"inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0, "fts_repaired": 0}
        with con:
            existing = {
                path: (note_id, content_hash)
                for note_id, path, content_hash in con.execute("SELECT id,path,content_hash FROM notes")
            }
            fts_ids = {row[0] for row in con.execute("SELECT rowid FROM notes_fts")}
            seen = set()
            for record in records:
                if record.path in seen:
                    continue
                seen.add(record.path)
                row = existing.get(record.path)
                if row is None:
                    _insert_note(con, record)
                    stats["inserted"] += 1
                elif row[1] != record.content_hash:
                    _update_note(con, row[0], record)
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
                    if row[0] not in fts_ids:
                        _fts_store(con, row[0], record)
                        stats["fts_repaired"] += 1
            for path, (note_id, _) in existing.items():
                if path not in seen:
                    _delete_note(con, note_id)
                    stats["deleted"] += 1
            _replace_issues(con, issues)
            _set_metadata(con, "vault", str(vault))
            _set_metadata(con, "format_version", "2")
            if (
                any(stats.values())
                or con.execute("SELECT 1 FROM metadata WHERE key='generated_utc'").fetchone() is None
            ):
                _set_metadata(con, "generated_utc", datetime.now(UTC).isoformat())
        return stats
    finally:
        con.close()


def _properties(con: sqlite3.Connection, note_id: int) -> dict:
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


def _cap_limit(limit: object, max_limit: int | None) -> int:
    try:
        value = int(limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    value = max(1, value)
    return min(value, max_limit) if max_limit is not None else value


def _bounded_snippet(text: object) -> str:
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) > SNIPPET_CHARS:
        return collapsed[: SNIPPET_CHARS - 2].rstrip() + " …"
    return collapsed


def search(
    db_path: str | Path,
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    vault: str | Path | None = None,
    max_limit: int | None = MAX_LIMIT,
) -> dict:
    """Search the indexed vault, returning relevance-ranked results with staleness."""
    active_limit = _cap_limit(limit, max_limit)
    result: dict = {"query": query, "results": [], "truncated": False, "index_outdated": False}
    match = build_match(query)
    con = connect_readonly(db_path)
    try:
        result["index_outdated"] = detect_index_outdated(con)
        if not match:
            return result
        indexed_timestamp = _metadata(con, "generated_utc")
        rows = con.execute(
            "SELECT notes.id, notes.path, notes.title, notes.type, bm25(notes_fts),"
            " snippet(notes_fts, 1, '', '', ' … ', 20), notes.content_hash"
            " FROM notes_fts JOIN notes ON notes.id = notes_fts.rowid"
            " WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts) LIMIT ?",
            (match, active_limit + 1),
        ).fetchall()
        result["truncated"] = len(rows) > active_limit
        for note_id, path, title, note_type, score, snippet, content_hash in rows[:active_limit]:
            normalized_type = str(note_type or "").strip().lower()
            result["results"].append(
                {
                    "source_id": path,
                    "source_path": path,
                    "path": path,
                    "title": title,
                    "note_type": note_type,
                    "source_type": "meeting" if normalized_type in MEETING_TYPES else "document",
                    "score": score,
                    "snippet": _bounded_snippet(snippet),
                    "source_timestamp": _source_timestamp(_properties(con, note_id), path),
                    "indexed_timestamp": indexed_timestamp,
                    "stale": per_result_stale(vault, path, content_hash),
                }
            )
        return result
    finally:
        con.close()
