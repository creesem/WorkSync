"""Detect and repair malformed YAML frontmatter without a tolerant parser.

Detection wraps the single inventory scanner (:func:`worksync.inventory.parse.scan_vault`
and :func:`read_frontmatter`); it adds no parser. A small ordered set of rules maps a
malformed block to a repaired block that re-parses cleanly, rewriting only the
offending line(s) in place. Any malformed note that matches no rule is reported with
no rule so a repair run can fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from worksync.inventory.parse import IndexRecord, read_frontmatter, scan_vault, split_frontmatter
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp, MutationError
from worksync.safety.zones import write_zones

RULE_QUOTED_BACKSLASH = "normalize-backslash-quoted-scalar"
RULE_WIKILINK_BACKSLASH = "normalize-backslash-wikilink"
RULE_PLACEHOLDER = "quote-template-placeholder"

REVIEWER = "worksync-migration"
VERB = "repair_frontmatter"
REASON = "Repair malformed YAML frontmatter: normalize backslash paths and quote template placeholders"

_DOUBLE_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
_WIKILINK = re.compile(r"\[\[[^\n]*?\]\]")
_PLACEHOLDER_SCALAR = re.compile(r"^(\s*[A-Za-z_][A-Za-z0-9_-]*\s*:\s*)(\{\{[^{}]*\}\})[ \t]*$", re.MULTILINE)
_SIMPLE_ESCAPES = frozenset('0abtnvfre "/\\N_LP')
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class MalformedNote:
    """One malformed note, the rule that repairs it, and its fresh source hash."""

    path: str
    rule: str | None
    content: str | None
    expected: str


def _normalize_backslashes(text: str) -> str:
    """Replace backslash path separators while preserving valid YAML escapes.

    A backslash that begins a valid double-quoted YAML escape (``\\n``, ``\\t``,
    ``\\x41`` …) is a meaning, not a path, and is left alone; any other backslash is a
    Windows path separator and becomes ``/`` so a path stays a path.
    """
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\" or index + 1 >= len(text):
            out.append("/" if char == "\\" else char)
            index += 1
            continue
        following = text[index + 1]
        width = {"x": 2, "u": 4, "U": 8}.get(following, 0)
        digits = text[index + 2 : index + 2 + width]
        if following in _SIMPLE_ESCAPES:
            out.append(text[index : index + 2])
            index += 2
        elif width and len(digits) == width and all(digit in _HEX_DIGITS for digit in digits):
            out.append(text[index : index + 2 + width])
            index += 2 + width
        else:
            out.append("/")
            index += 1
    return "".join(out)


def _repair_quoted_backslash(block: str) -> str | None:
    if not any("\\" in match.group(0) for match in _DOUBLE_QUOTED.finditer(block)):
        return None
    repaired = _DOUBLE_QUOTED.sub(lambda match: _normalize_backslashes(match.group(0)), block)
    return repaired if repaired != block else None


def _repair_wikilink_backslash(block: str) -> str | None:
    if not any("\\" in match.group(0) for match in _WIKILINK.finditer(block)):
        return None
    repaired = _WIKILINK.sub(lambda match: _normalize_backslashes(match.group(0)), block)
    return repaired if repaired != block else None


def _repair_placeholder(block: str) -> str | None:
    if not _PLACEHOLDER_SCALAR.search(block):
        return None
    return _PLACEHOLDER_SCALAR.sub(lambda match: f'{match.group(1)}"{match.group(2)}"', block)


_RULES = (
    (RULE_WIKILINK_BACKSLASH, _repair_wikilink_backslash),
    (RULE_QUOTED_BACKSLASH, _repair_quoted_backslash),
    (RULE_PLACEHOLDER, _repair_placeholder),
)


def _repair_content(content: str) -> tuple[str, str] | None:
    block, body = split_frontmatter(content)
    if not block:
        return None
    for name, rule in _RULES:
        repaired = rule(block)
        if repaired is None:
            continue
        candidate = f"---\n{repaired}\n---\n{body}"
        if not read_frontmatter(candidate).malformed:
            return name, candidate
    return None


def _detect_record(record: IndexRecord) -> MalformedNote:
    repaired = _repair_content(record.content)
    if repaired is None:
        return MalformedNote(record.path, None, None, record.content_hash)
    rule, content = repaired
    return MalformedNote(record.path, rule, content, record.content_hash)


def detect(vault: str | Path) -> list[MalformedNote]:
    """Return every malformed note with its matched rule; never writes."""
    return [_detect_record(record) for record in scan_vault(vault) if record.frontmatter_malformed]


def apply_repairs(
    vault: str | Path,
    runtime: str | Path,
    *,
    detections: list[MalformedNote] | None = None,
    now: datetime | None = None,
) -> CommitResult | None:
    """Repair every malformed note as one gated canonical transaction.

    Returns ``None`` when there is nothing to do. Fails closed with no writes when a
    malformed note matches no rule.
    """
    if detections is None:
        detections = detect(vault)
    if not detections:
        return None
    unmatched = [note for note in detections if note.rule is None or note.content is None]
    if unmatched:
        raise MutationError(
            "unknown_malformed",
            f"{len(unmatched)} malformed note(s) match no known repair rule.",
            affected=tuple(note.path for note in unmatched),
        )
    vault_path = Path(vault).expanduser().resolve()
    ops = tuple(
        FileOp("update", Path(note.path), "trusted", content=note.content, expected=note.expected)
        for note in detections
    )
    changeset = ChangeSet(VERB, ops, reviewer=REVIEWER, reason=REASON)
    return commit(changeset, write_zones(vault_path, runtime), now=now)
