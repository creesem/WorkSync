"""Krisp discovery: turn a pulled transcript into a meeting-note candidate.

Discovery reads the runtime inbox directly (transcripts and sidecars are not vault
markdown), skips anything already processed, and builds a complete deterministic
``meeting`` proposal from the sidecar. Attendees are linked only when a speaker name
resolves to a canonical Person; unmatched and ambiguous speaker names are recorded in
provenance and never invented.

Project references are identified index-driven: a canonical project is proposed only when
its ``title`` or ``project_id`` appears in the transcript. Because the source is free text
with no explicit reference syntax, a project *reference* that fails to resolve cannot be
detected, so there is no unmatched-project set; the only project failure mode is an
ambiguous title (claimed by more than one entity), which is recorded and never linked. No
second markdown parser is involved.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from worksync.ingest.krisp.sidecar import PROCESSED_DIRNAME, parse_iso_prefix, read_sidecar
from worksync.ingest.proposal import Proposal
from worksync.safety.files import sha256_file
from worksync.work.repository import WorkIndex
from worksync.work.schema import link_target

UNDATED_PLACEHOLDER = "1970-01-01"
MAX_PROJECTS = 5
PROVENANCE_CAP = 40
MODEL_INPUT_LIMIT = 1200
_NOTES_SCHEMA = {
    "type": "object",
    "properties": {"notes": {"type": "string"}},
    "required": ["notes"],
}


def discover_krisp(
    inbox: str | Path | None,
    index: WorkIndex,
    *,
    today: date,
    model: object | None = None,
) -> tuple[Proposal, ...]:
    """Return one meeting proposal per unprocessed transcript, in deterministic order."""
    if inbox is None:
        return ()
    root = Path(inbox).expanduser().resolve()
    if not root.is_dir():
        return ()
    proposals: list[Proposal] = []
    for transcript in _transcripts(root):
        sidecar = read_sidecar(root, transcript)
        if not sidecar:
            continue
        proposal = build_meeting_proposal(transcript, root, sidecar, index, today=today, model=model)
        if proposal is not None:
            proposals.append(proposal)
    return tuple(proposals)


def build_meeting_proposal(
    transcript: Path,
    inbox_root: Path,
    sidecar: dict[str, Any],
    index: WorkIndex,
    *,
    today: date,
    model: object | None = None,
) -> Proposal:
    """Build one deterministic meeting proposal from a transcript and its sidecar."""
    meeting_id = str(sidecar.get("meeting_id") or "").strip() or transcript.stem
    source_path = transcript.relative_to(inbox_root).as_posix()
    source_sha = sha256_file(transcript)
    fields, provenance = _fields(transcript, sidecar, index, meeting_id=meeting_id, today=today)
    if model is not None:
        fields, provenance = _apply_model(fields, provenance, model)
    return Proposal(
        id=f"krisp:{meeting_id}",
        action="meeting",
        source_path=source_path,
        source_sha256=source_sha,
        fields=fields,
        confidence=_confidence(fields),
        provenance=tuple(provenance),
    )


def _fields(
    transcript: Path,
    sidecar: dict[str, Any],
    index: WorkIndex,
    *,
    meeting_id: str,
    today: date,
) -> tuple[dict[str, Any], list[str]]:
    text = _read_text(transcript)
    title = str(sidecar.get("title") or transcript.stem).strip() or transcript.stem
    date_iso, date_status = _date(sidecar.get("started_at"), today=today)
    attendees, unmatched, ambiguous_speakers = _attendees(sidecar.get("speakers") or (), index)
    projects, ambiguous_projects = _projects(text, index)
    key_points = _key_points(sidecar.get("notes") or {})
    action_items = _action_items(sidecar.get("notes") or {})

    fields: dict[str, Any] = {
        "title": title,
        "status": "held",
        "date": date_iso,
        "attendees": attendees,
        "projects": projects,
        "source_system": "krisp",
        "external_id": meeting_id,
        "key_points": key_points,
        "action_items": action_items,
    }
    if date_status:
        fields["date_status"] = date_status

    provenance = [
        "title <- Krisp sidecar",
        f"date <- recording ({date_iso})" if not date_status else "date <- undated placeholder",
        f"attendees resolved {len(attendees)} of {len(sidecar.get('speakers') or ())}",
        f"projects matched {len(projects)}",
        "notes draft <- deterministic",
        "actions <- Krisp action items",
    ]
    if unmatched:
        provenance.append("unmatched speakers: " + ", ".join(unmatched))
    if ambiguous_speakers:
        provenance.append("ambiguous speakers: " + ", ".join(ambiguous_speakers))
    if ambiguous_projects:
        provenance.append("ambiguous projects: " + ", ".join(ambiguous_projects))
    return fields, provenance[:PROVENANCE_CAP]


def _attendees(speakers: Any, index: WorkIndex) -> tuple[list[str], list[str], list[str]]:
    resolved: list[str] = []
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for speaker in speakers if isinstance(speakers, (list, tuple)) else ():
        if not isinstance(speaker, dict):
            continue
        name = _speaker_name(speaker)
        if not name:
            continue
        person = index.get("person", name)
        if person is not None:
            link = f"[[{person.title}]]"
            if link not in resolved:
                resolved.append(link)
        elif link_target(name) in index.duplicate_keys:
            if name not in ambiguous:
                ambiguous.append(name)
        elif name not in unmatched:
            unmatched.append(name)
    return resolved, unmatched, ambiguous


def _projects(text: str, index: WorkIndex) -> tuple[list[str], list[str]]:
    haystack = text.casefold()
    resolved: list[str] = []
    ambiguous: list[str] = []
    projects = index.list_type("project")
    id_counts = Counter(str(getattr(project, "project_id", "") or "").strip() for project in projects)
    for project in projects:
        title = str(project.title or "").strip()
        project_id = str(getattr(project, "project_id", "") or "").strip()
        matched = (bool(title) and title.casefold() in haystack) or (
            bool(project_id) and project_id.casefold() in haystack
        )
        if not matched:
            continue
        entity = index.get("project", title) if title else None
        ambiguous_id = bool(project_id) and id_counts[project_id] > 1
        if entity is None or ambiguous_id:
            label = title or project_id
            if label and label not in ambiguous:
                ambiguous.append(label)
            continue
        link = f"[[{entity.title}]]"
        if link not in resolved:
            resolved.append(link)
        if len(resolved) >= MAX_PROJECTS:
            break
    return resolved, ambiguous


def _key_points(notes: Any) -> list[str]:
    points: list[str] = []
    for child in _children(notes, "key_points"):
        text = str(child.get("text") or "").strip()
        if text:
            points.append(text)
    return points


def _action_items(notes: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for child in _children(notes, "action_items"):
        text = str(child.get("text") or "").strip()
        if not text:
            continue
        assignee = child.get("assignee")
        name = _speaker_name(assignee) if isinstance(assignee, dict) else ""
        items.append({"assignee": name, "text": text})
    return items


def _children(notes: Any, block_type: str) -> list[dict[str, Any]]:
    if not isinstance(notes, dict):
        return []
    blocks = notes.get("blocks")
    if not isinstance(blocks, list):
        return []
    children: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict) and str(block.get("type") or "") == block_type:
            kids = block.get("children")
            if isinstance(kids, list):
                children.extend(child for child in kids if isinstance(child, dict))
    return children


def _apply_model(fields: dict[str, Any], provenance: list[str], model: object) -> tuple[dict[str, Any], list[str]]:
    """Optionally draft the ``## Notes`` prose from a bounded, cited input.

    The model is suggestion-only: a missing method, a raised error, or an unusable
    response falls back to the deterministic bullets, and the model never changes the
    proposal's existence, status, or promotion.
    """
    suggest = getattr(model, "suggest", None)
    if not callable(suggest):
        return fields, provenance
    try:
        suggestion = suggest(_notes_prompt(fields), _NOTES_SCHEMA)
    except Exception:  # noqa: BLE001 - a model failure must never break the pipeline
        return fields, provenance
    if not isinstance(suggestion, dict):
        return fields, provenance
    prose = str(suggestion.get("notes") or "").strip()
    if not prose:
        return fields, provenance
    return {**fields, "notes_text": prose}, [*provenance, "notes draft <- local model (suggestion)"]


def _notes_prompt(fields: dict[str, Any]) -> str:
    points = "\n".join(f"- {point}" for point in fields.get("key_points") or ())
    actions = "\n".join(f"- {item.get('text', '')}" for item in fields.get("action_items") or ())
    content = f"Key points:\n{points}\n\nAction items:\n{actions}".strip()[:MODEL_INPUT_LIMIT]
    return (
        "Rewrite these meeting notes as a short, plain Markdown summary for an Obsidian "
        "meeting note. Use only the given content and do not invent facts. Respond as JSON "
        "with one key 'notes'.\n\n" + content
    )


def _confidence(fields: dict[str, Any]) -> float:
    signals = sum(1 for key in ("attendees", "projects", "key_points", "action_items") if fields.get(key))
    return round(min(0.9, 0.5 + 0.1 * signals), 4)


def _transcripts(root: Path) -> list[Path]:
    transcripts = [path for path in sorted(root.rglob("*.txt")) if path.is_file() and not _in_processed(path, root)]
    return transcripts


def _in_processed(path: Path, root: Path) -> bool:
    return any(part.casefold() == PROCESSED_DIRNAME.casefold() for part in path.relative_to(root).parts[:-1])


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _speaker_name(speaker: Any) -> str:
    if not isinstance(speaker, dict):
        return str(speaker or "").strip()
    parts = [str(speaker.get("first_name") or "").strip(), str(speaker.get("last_name") or "").strip()]
    return " ".join(part for part in parts if part).strip()


def _date(started_at: Any, *, today: date) -> tuple[str, str | None]:
    iso = parse_iso_prefix(started_at)
    return (iso, None) if iso else (UNDATED_PLACEHOLDER, "undated")
