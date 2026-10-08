"""Deterministic enrichment of a discovered source into a proposal.

Rules run first and always produce a complete proposal. Each proposed field carries a
human-readable provenance reason. The optional local-model pass (ticket 04) only fills
weak fields as suggestions.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from worksync.ingest.discover import Source
from worksync.ingest.proposal import Proposal
from worksync.work.repository import WorkIndex
from worksync.work.schema import ACTIVE_ACTION_STATUSES, canonical_priority
from worksync.work.similarity import score

LINK_THRESHOLD = 0.7
MERGE_THRESHOLD = 0.5
NON_ACTION_TYPES = frozenset({"project", "person", "ticket", "meeting"})
DROP_TYPES = frozenset({"reference", "placeholder", "redirect", "dashboard", "index", "weekly", "daily"})
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def enrich(source: Source, index: WorkIndex, *, today: date) -> Proposal | None:
    """Return one proposal for *source*, or ``None`` when it is not a candidate."""
    record = source.record
    note_type = _note_type(record)
    if note_type in NON_ACTION_TYPES:
        return None

    proposal_id = f"{record.path}#0"
    if note_type in DROP_TYPES:
        return Proposal(
            id=proposal_id,
            action="drop",
            source_path=record.path,
            source_sha256=record.content_hash,
            confidence=0.6,
            provenance=(f"declared type '{note_type}' -> drop",),
        )

    title, title_source = _title(record)
    if not title:
        return None
    fields, provenance = _fields(record, index, title=title)
    provenance.insert(0, f"title <- {title_source}")

    match, similarity = _best_match(title, index)
    if match is not None and similarity >= LINK_THRESHOLD:
        return Proposal(
            id=proposal_id,
            action="link-existing",
            source_path=record.path,
            source_sha256=record.content_hash,
            target_path=match.path,
            fields=fields,
            confidence=round(similarity, 4),
            provenance=(*provenance, f"matches '{match.title}' ({similarity:.2f}) -> link-existing"),
        )
    if match is not None and similarity >= MERGE_THRESHOLD:
        return Proposal(
            id=proposal_id,
            action="merge",
            source_path=record.path,
            source_sha256=record.content_hash,
            target_path=match.path,
            fields=fields,
            confidence=round(similarity, 4),
            provenance=(*provenance, f"overlaps '{match.title}' ({similarity:.2f}) -> merge"),
        )
    return Proposal(
        id=proposal_id,
        action="action",
        source_path=record.path,
        source_sha256=record.content_hash,
        fields=fields,
        confidence=_confidence(fields),
        provenance=tuple(provenance),
    )


def _fields(record, index: WorkIndex, *, title: str) -> tuple[dict, list[str]]:
    frontmatter = record.frontmatter
    fields: dict = {"title": title, "status": "open", "source": record.path}
    provenance: list[str] = []

    project = _link_target(frontmatter.get("project"))
    project_entity = index.resolve(project) if project else None
    if project and project_entity is not None:
        fields["project"] = f"[[{project_entity.title}]]"
        provenance.append(f"project <- note ({project_entity.title})")

    owner = _first_link(frontmatter.get("owners"))
    if owner:
        provenance.append("owner <- note owners")
    elif project_entity is not None:
        owner = _first_link(project_entity.raw.get("owners"))
        if owner:
            provenance.append(f"owner <- project '{project_entity.title}'")
    if owner:
        fields["owners"] = [f"[[{owner}]]"]

    priority = frontmatter.get("priority")
    if priority is not None:
        mappable, canonical = canonical_priority(priority)
        if mappable and canonical:
            fields["priority"] = canonical
            provenance.append(f"priority <- note ({canonical})")
    elif project_entity is not None:
        mappable, canonical = canonical_priority(project_entity.raw.get("priority"))
        if mappable and canonical:
            fields["priority"] = canonical
            provenance.append(f"priority <- project ({canonical})")

    due = _iso_date(frontmatter.get("due"))
    if due:
        fields["due"] = due
        provenance.append(f"due <- note ({due})")

    return fields, provenance


def _best_match(title: str, index: WorkIndex):
    best = None
    best_score = 0.0
    for entity in index.view_entities("action"):
        if entity.status not in ACTIVE_ACTION_STATUSES:
            continue
        current = score(title, entity.title)
        if current > best_score:
            best, best_score = entity, current
    return best, best_score


def _confidence(fields: dict) -> float:
    resolved = sum(1 for key in ("owners", "project", "priority", "due") if fields.get(key))
    return round(min(0.95, 0.4 + 0.1 * resolved), 4)


def _note_type(record) -> str:
    value = record.frontmatter.get("type")
    return str(value or "").strip().strip("\"'").casefold()


def _title(record) -> tuple[str, str]:
    if record.headings:
        return record.headings[0][1], "heading"
    stem = Path(record.path).stem
    return stem, "filename"


def _link_target(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    match = WIKILINK_RE.search(text)
    return (match.group(1).strip() if match else text) or None


def _first_link(value: object) -> str | None:
    if isinstance(value, (list, tuple)):
        for item in value:
            target = _link_target(item)
            if target:
                return target
        return None
    return _link_target(value)


def _iso_date(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text
