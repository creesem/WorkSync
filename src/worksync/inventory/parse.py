"""YAML-faithful vault reader: the single parse layer.

Produces :class:`IndexRecord` from vault notes. Frontmatter is read with
:func:`read_frontmatter` (PyYAML) and written in place with
:func:`edit_frontmatter_fields` (which :func:`set_frontmatter_fields` delegates to), so
the reader and the one writer stay byte-compatible. Encoding is ``utf-8-sig``. Lossy
line parsers are retired.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
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


_KEY_LINE = re.compile(r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?P<rest>.*?)(?P<eol>\r?\n?)$")


def _replace_scalar(match: re.Match[str], value: str) -> str:
    rest = match.group("rest")
    leading = rest[: len(rest) - len(rest.lstrip(" \t"))] or " "
    core = rest.strip(" \t")
    quoted = len(core) >= 2 and core[0] == core[-1] and core[0] in "\"'"
    core = f"{core[0]}{value}{core[0]}" if quoted else value
    return f"{match.group('indent')}{match.group('key')}:{leading}{core}{match.group('eol')}"


def edit_frontmatter_fields(
    content: str,
    *,
    set_fields: Mapping[str, str | None] | None = None,
    rename_keys: Mapping[str, str] | None = None,
) -> str:
    """Return ``content`` with only the named frontmatter fields edited in place.

    A ``set_fields`` value of ``None`` removes the key (and any indented block it owns).
    A scalar replacement stays on its existing line and keeps the value's quoting; a
    rename keeps the value lines; a missing key is appended at the end of the block.
    Every unmapped line, its order, the note body, and the line endings (including CRLF)
    are preserved byte-for-byte.
    """
    set_fields = dict(set_fields or {})
    renames = dict(rename_keys or {})
    if not set_fields and not renames:
        return content

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        additions = "".join(f"{key}: {value}\n" for key, value in set_fields.items() if value is not None)
        if not additions:
            return content
        return f"---\n{additions}---\n{content}"

    close = next((index for index in range(1, len(lines)) if lines[index].rstrip("\r\n") == "---"), None)
    if close is None:
        return content
    block = lines[1:close]
    tail = lines[close:]
    eol = "\r\n" if lines[0].endswith("\r\n") else "\n"
    edited: list[str] = []
    handled: set[str] = set()
    index = 0
    while index < len(block):
        line = block[index]
        match = _KEY_LINE.match(line)
        if match is None or match.group("indent"):
            edited.append(line)
            index += 1
            continue
        key = match.group("key")
        drop = key in set_fields and set_fields[key] is None
        if drop:
            index += 1
            while index < len(block) and block[index][:1] in (" ", "\t"):
                index += 1
            continue
        if key in renames:
            edited.append(f"{match.group('indent')}{renames[key]}:{match.group('rest')}{match.group('eol')}")
            handled.add(key)
        elif key in set_fields:
            edited.append(_replace_scalar(match, str(set_fields[key])))
            handled.add(key)
        else:
            edited.append(line)
        index += 1
    for key, value in set_fields.items():
        if value is None or key in handled or key in renames:
            continue
        edited.append(f"{key}: {value}{eol}")
    return "".join([lines[0], *edited, *tail])


def set_frontmatter_fields(content: str, fields: dict[str, str | None]) -> str:
    """Return ``content`` with the given frontmatter fields set, removed, or replaced.

    A ``None`` value removes the key; any other value replaces (or appends) it. This is
    a thin convenience wrapper over :func:`edit_frontmatter_fields`, so the parse layer
    owns exactly one frontmatter writer.
    """
    return edit_frontmatter_fields(content, set_fields=fields)


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
