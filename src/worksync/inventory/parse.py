"""YAML-faithful vault reader: the single parse layer.

Produces :class:`IndexRecord` from vault notes. Frontmatter is read with
:func:`read_frontmatter` (PyYAML) and written with :func:`set_frontmatter_fields`,
so the reader and any writer stay byte-compatible. Encoding is ``utf-8-sig``.
Lossy line parsers are retired.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_/-]+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
TASK_RE = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.*)$", re.MULTILINE)

EXCLUDED_DIRS = (".obsidian", ".trash", ".git")


@dataclass(frozen=True)
class Frontmatter:
    """The outcome of reading a note's leading YAML block."""

    data: dict[str, Any]
    present: bool
    closed: bool
    malformed: bool


@dataclass
class IndexRecord:
    """One parsed vault note, with YAML-faithful frontmatter."""

    path: str
    title: str
    content: str
    content_hash: str
    size: int
    modified_utc: str
    frontmatter: dict[str, Any]
    frontmatter_present: bool
    frontmatter_closed: bool
    frontmatter_malformed: bool
    headings: list[tuple[int, str]] = field(default_factory=list)
    links: list[tuple[str, str | None]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    tasks: list[tuple[bool, str, int]] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


def split_frontmatter(content: str) -> tuple[str, str]:
    """Split a note into ``(frontmatter_block, body)``.

    Returns ``("", content)`` when the note has no well-formed ``---`` block. This
    is the single canonical splitter for both read and write paths.
    """
    if not content.startswith("---\n"):
        return "", content
    rest = content.removeprefix("---\n")
    frontmatter, sep, body = rest.partition("\n---\n")
    if not sep:
        return "", content
    return frontmatter, body


def read_frontmatter(content: str) -> Frontmatter:
    """Read the leading YAML block tolerantly.

    Never raises: missing, unclosed, or invalid YAML yields empty ``data`` with the
    ``present``/``closed``/``malformed`` flags set so a caller can report it.
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return Frontmatter({}, present=False, closed=True, malformed=False)
    end = next((index for index in range(1, min(len(lines), 500)) if lines[index].strip() == "---"), None)
    if end is None:
        return Frontmatter({}, present=True, closed=False, malformed=False)
    block = "\n".join(lines[1:end])
    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError:
        return Frontmatter({}, present=True, closed=True, malformed=True)
    if parsed is None:
        return Frontmatter({}, present=True, closed=True, malformed=False)
    if not isinstance(parsed, dict):
        return Frontmatter({}, present=True, closed=True, malformed=True)
    return Frontmatter(parsed, present=True, closed=True, malformed=False)


def set_frontmatter_fields(content: str, fields: dict[str, str | None]) -> str:
    """Return ``content`` with the given frontmatter fields set, removed, or replaced.

    A ``None`` value removes the key; any other value replaces (or appends) it while
    leaving untouched fields and their formatting intact.
    """
    frontmatter, body = split_frontmatter(content)
    lines = frontmatter.splitlines() if frontmatter else []
    for key, value in fields.items():
        lines = [line for line in lines if not re.match(rf"^{re.escape(key)}:\s*", line)]
        if value is not None:
            lines.append(f"{key}: {value}")
    rendered = "\n".join(lines).strip()
    if rendered:
        return f"---\n{rendered}\n---\n{body.lstrip(chr(10))}"
    return body.lstrip("\n")


def _as_text(value: Any) -> str | None:
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


def _aliases(frontmatter: dict[str, Any]) -> list[str]:
    raw = frontmatter.get("aliases")
    if isinstance(raw, list):
        return [text for item in raw if (text := str(item).strip())]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def parse_note(path: Path, vault: Path) -> IndexRecord:
    """Read one note into an :class:`IndexRecord` (never mutates it)."""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    frontmatter = read_frontmatter(text)
    headings = [(len(match.group(1)), match.group(2).strip()) for match in HEADING_RE.finditer(text)]
    title = _as_text(frontmatter.data.get("title")) or (headings[0][1] if headings else path.stem)
    links: list[tuple[str, str | None]] = []
    for match in WIKILINK_RE.finditer(text):
        raw_target = match.group(1)
        target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
        alias = raw_target.split("|", 1)[1].strip() if "|" in raw_target else None
        if target:
            links.append((target, alias))
    tasks: list[tuple[bool, str, int]] = []
    for match in TASK_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        tasks.append((match.group(1).lower() == "x", match.group(2).strip(), line))
    stat = path.stat()
    root = Path(vault).expanduser().resolve()
    return IndexRecord(
        path=path.resolve().relative_to(root).as_posix(),
        title=title,
        content=text,
        content_hash=hashlib.sha256(raw).hexdigest(),
        size=len(raw),
        modified_utc=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        frontmatter=frontmatter.data,
        frontmatter_present=frontmatter.present,
        frontmatter_closed=frontmatter.closed,
        frontmatter_malformed=frontmatter.malformed,
        headings=headings,
        links=links,
        tags=sorted(set(TAG_RE.findall(text))),
        tasks=tasks,
        aliases=_aliases(frontmatter.data),
    )


def iter_markdown(vault: str | Path, *, excluded: tuple[str, ...] = EXCLUDED_DIRS) -> list[Path]:
    """Return markdown note paths under *vault* in deterministic order."""
    root = Path(vault).expanduser().resolve()
    excluded_set = set(excluded)
    paths = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        if any(part in excluded_set for part in path.relative_to(root).parts):
            continue
        paths.append(path)
    return paths


def scan_vault(vault: str | Path, *, excluded: tuple[str, ...] = EXCLUDED_DIRS) -> list[IndexRecord]:
    """Parse every markdown note under *vault*; one bad note never aborts the scan.

    Records are de-duplicated by resolved vault-relative path so a symlinked or
    junctioned directory cannot index the same note twice.
    """
    root = Path(vault).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Vault root does not exist: {root}")
    records: list[IndexRecord] = []
    seen: set[str] = set()
    for path in iter_markdown(root, excluded=excluded):
        record = parse_note(path, root)
        if record.path in seen:
            continue
        seen.add(record.path)
        records.append(record)
    return records
