"""Canonical similarity scoring for titles and work entities.

One deterministic scorer shared by ingest duplicate detection and the future duplicate
resolution workflow, so the two never diverge. Pure text, no I/O.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

WORD_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    {"the", "a", "an", "to", "of", "for", "and", "or", "with", "on", "in", "at", "by", "from", "is", "be"}
)


def words(text: object) -> list[str]:
    """Return the significant lowercase word tokens in *text*."""
    return [token for token in WORD_RE.findall(str(text or "").casefold()) if token not in STOPWORDS]


def title_tokens(text: object) -> set[str]:
    """Return the significant token set for a title."""
    return set(words(text))


def title_jaccard(left: object, right: object) -> float:
    """Return the Jaccard similarity of two titles' token sets."""
    first, second = title_tokens(left), title_tokens(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def score(left: object, right: object) -> float:
    """Return a 0–1 similarity combining token overlap and sequence ratio."""
    first = str(left or "").casefold().strip()
    second = str(right or "").casefold().strip()
    if not first or not second:
        return 0.0
    return 0.7 * title_jaccard(first, second) + 0.3 * SequenceMatcher(None, first, second).ratio()
