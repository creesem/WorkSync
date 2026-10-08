"""Deterministic enrichment of a discovered source into a proposal.

Rules run first and always produce a complete proposal. Each proposed field carries a
human-readable provenance reason. The optional local-model pass (ticket 04) only fills
weak fields as suggestions.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Protocol

from worksync.ingest.discover import Source
from worksync.ingest.proposal import Proposal
from worksync.inventory.parse import split_frontmatter
from worksync.work.repository import WorkIndex
from worksync.work.schema import ACTIVE_ACTION_STATUSES, canonical_priority
from worksync.work.similarity import score

LINK_THRESHOLD = 0.7
MERGE_THRESHOLD = 0.5
NON_ACTION_TYPES = frozenset({"project", "person", "ticket", "meeting"})
DROP_TYPES = frozenset({"reference", "placeholder", "redirect", "dashboard", "index", "weekly", "daily"})
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
MODEL_FIELDS = ("owners", "project", "priority", "due")
MODEL_CONFIDENCE_CAP = 0.5
MODEL_BODY_LIMIT = 1200


class Suggester(Protocol):
    """A local model that returns a structured suggestion, or ``None`` when unavailable."""

    def suggest(self, prompt: str, schema: dict) -> dict | None: ...


def enrich(source: Source, index: WorkIndex, *, today: date, model: Suggester | None = None) -> Proposal | None:
    """Return one proposal for *source*, or ``None`` when it is not a candidate.

    Deterministic rules run first and always produce a complete proposal. When *model* is
    supplied it is consulted only for fields the rules left unresolved; its suggestions
    carry provenance and a capped confidence, and never resolve the proposal.
    """
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
    ai_fields: tuple[str, ...] = ()
    if model is not None:
        fields, provenance, ai_fields = _apply_model(fields, provenance, record, index, today=today, model=model)
    provenance.insert(0, f"title <- {title_source}")

    match, similarity = _best_match(title, index, exclude=record.path)
    if match is not None and similarity >= LINK_THRESHOLD:
        return Proposal(
            id=proposal_id,
            action="link-existing",
            source_path=record.path,
            source_sha256=record.content_hash,
            target_path=match.path,
            fields=fields,
            confidence=round(min(similarity, MODEL_CONFIDENCE_CAP) if ai_fields else similarity, 4),
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
            confidence=round(min(similarity, MODEL_CONFIDENCE_CAP) if ai_fields else similarity, 4),
            provenance=(*provenance, f"overlaps '{match.title}' ({similarity:.2f}) -> merge"),
        )
    return Proposal(
        id=proposal_id,
        action="action",
        source_path=record.path,
        source_sha256=record.content_hash,
        fields=fields,
        confidence=_confidence(fields, ai_fields=ai_fields),
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


def _best_match(title: str, index: WorkIndex, *, exclude: str | None = None):
    best = None
    best_score = 0.0
    for entity in index.view_entities("action"):
        if entity.path == exclude or entity.status not in ACTIVE_ACTION_STATUSES:
            continue
        current = score(title, entity.title)
        if current > best_score:
            best, best_score = entity, current
    return best, best_score


def _confidence(fields: dict, *, ai_fields: tuple[str, ...] = ()) -> float:
    resolved = sum(1 for key in ("owners", "project", "priority", "due") if fields.get(key))
    confidence = min(0.95, 0.4 + 0.1 * resolved)
    if ai_fields:
        confidence = min(confidence, MODEL_CONFIDENCE_CAP)
    return round(confidence, 4)


def _apply_model(
    fields: dict,
    provenance: list[str],
    record,
    index: WorkIndex,
    *,
    today: date,
    model: Suggester,
) -> tuple[dict, list[str], tuple[str, ...]]:
    weak = [key for key in MODEL_FIELDS if not fields.get(key)]
    if not weak:
        return fields, provenance, ()
    try:
        suggestion = model.suggest(_model_prompt(record, weak, today=today), _model_schema(weak))
    except Exception:
        return fields, provenance, ()
    if not isinstance(suggestion, dict):
        return fields, provenance, ()

    updated = dict(fields)
    reasons = list(provenance)
    filled: list[str] = []
    for key in weak:
        canonical = _normalize_suggestion(key, suggestion.get(key), index)
        if canonical is None:
            continue
        updated[key] = canonical
        filled.append(key)
        reasons.append(f"{key} <- local model (suggestion)")
    if not filled:
        return fields, provenance, ()
    return updated, reasons, tuple(filled)


def _normalize_suggestion(key: str, value: object, index: WorkIndex) -> object | None:
    if key == "owners":
        return _suggested_owner(value, index)
    if key == "project":
        target = _link_target(value)
        entity = index.get("project", target) if target else None
        return f"[[{entity.title}]]" if entity is not None else None
    if key == "priority":
        mappable, canonical = canonical_priority(value)
        return canonical if mappable and canonical else None
    if key == "due":
        return _iso_date(value)
    return None


def _suggested_owner(value: object, index: WorkIndex) -> list[str] | None:
    raw = value if isinstance(value, (list, tuple)) else (value,)
    for item in raw:
        target = _link_target(item)
        entity = index.get("person", target) if target else None
        if entity is not None:
            return [f"[[{entity.title}]]"]
    return None


def _model_schema(weak: list[str]) -> dict:
    properties: dict[str, dict] = {}
    for key in weak:
        if key == "owners":
            properties[key] = {"type": "array", "items": {"type": "string"}}
        else:
            properties[key] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": list(weak)}


def _model_prompt(record, weak: list[str], *, today: date) -> str:
    body = split_frontmatter(record.content)[1].strip()[:MODEL_BODY_LIMIT]
    keys = ", ".join(weak)
    return (
        "Propose values for a work action from this note. Only propose a value clearly "
        "supported by the note; use an empty string when unknown. Respond as JSON with "
        f"exactly these keys: {keys}. Today is {today.isoformat()}.\n\n"
        f"Title: {record.title}\nNote:\n{body}"
    )


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
