"""Pure content helpers for consolidating one action note into another.

No I/O and no error types live here: the domain modules (duplicates, clarification)
own note loading and their own failure vocabulary, and share only the exact string
transformations for a merge or an in-place redirect tombstone.
"""

from __future__ import annotations

import json

from worksync.inventory.parse import edit_frontmatter_fields, split_frontmatter

MERGED_HEADING = "## Merged context"
UPDATES_HEADING = "## Updates"
LAST_ACTION_LIMIT = 240


def revision(frontmatter: dict) -> int:
    """Return the note's current revision number, or 0 when unset/invalid."""
    try:
        return int(frontmatter.get("revision"))
    except (TypeError, ValueError):
        return 0


def merged_content(canonical_content: str, duplicate_content: str) -> str:
    """Append the duplicate's body under a merged-context heading to the canonical note."""
    body = split_frontmatter(duplicate_content)[1].strip()
    if not body:
        return canonical_content
    return canonical_content.rstrip("\n") + f"\n\n{MERGED_HEADING}\n\n{body}\n"


def redirect_content(
    content: str, frontmatter: dict, canonical_title: str, *, when: str, reviewer: str, reason: str
) -> str:
    """Return *content* as an in-place redirect tombstone pointing at *canonical_title*."""
    fields = {
        "type": "redirect",
        "status": "cancelled",
        "redirect": json.dumps(f"[[{canonical_title}]]"),
        "updated": when,
        "revision": str(revision(frontmatter) + 1),
        "updated_by": str(reviewer).strip(),
        "last_action": str(reason).strip()[:LAST_ACTION_LIMIT],
    }
    return edit_frontmatter_fields(content, set_fields=fields)


def archive_content(content: str, frontmatter: dict, title: str, *, when: str, reviewer: str, reason: str) -> str:
    """Return *content* as an in-place archive tombstone.

    The gateway cannot update-then-move a note in one ``ChangeSet``, so archiving is the
    same in-place ``type: redirect`` tombstone a redirect writes; this named helper makes
    that deliberate coincidence explicit at the call site.
    """
    return redirect_content(content, frontmatter, title, when=when, reviewer=reviewer, reason=reason)


def append_update_entry(content: str, *, when: str, reviewer: str, reason: str) -> str:
    """Append one structured review entry to the note's ``## Updates`` history.

    The ``## Updates`` section is the final section of a canonical note. When it is
    present the entry is appended as its last line; otherwise the section is added at the
    end of the body. The entry is a deterministic bullet, not free-form prose, so the
    reason stays visible in-note without becoming an unvalidated paragraph.
    """
    entry = f"- {when} · {_one_line(reviewer)} · {_one_line(reason)}"
    text = content.rstrip("\n")
    if any(line.strip() == UPDATES_HEADING for line in text.splitlines()):
        return f"{text}\n{entry}\n"
    return f"{text}\n\n{UPDATES_HEADING}\n\n{entry}\n"


def _one_line(value: str) -> str:
    """Collapse *value* to a single bounded line so it cannot inject Markdown structure."""
    return " ".join(str(value).split())[:LAST_ACTION_LIMIT]
