"""Deterministic meeting eligibility and action extraction for the potential-task pool.

The parser is deliberately literal: it reads only the ``## Actions`` section of a finalized
(``held``) meeting, accepts only checkbox/unordered-bullet lines, and never invents a title,
owner, due date, project, priority, quote, or placeholder action. Identity depends only on the
canonical meeting id, the normalized action line, and the occurrence of identical lines, so
reordering a note never changes a candidate id.

The module is the single extraction seam: the new-meeting ingest apply and the later
``pool scan`` path both call :func:`extract_meeting`, so they cannot drift apart. Reads never
touch the vault; writes go through :mod:`worksync.work.pool_store`.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from worksync.inventory.parse import HEADING_RE, IndexRecord, read_frontmatter, scan_vault
from worksync.safety.files import sha256_bytes, sha256_file
from worksync.safety.models import FileOp
from worksync.work.pool import (
    EXTRACTION_VERSION,
    MANUAL_PROVENANCE_CLASSES,
    POOL_FILENAME,
    PRIORITIES,
    HistoryEntry,
    MeetingExtraction,
    PoolCandidate,
    PoolError,
    PoolManifest,
    PoolSource,
    TaskFieldValue,
    pool_path,
    read_manifest,
    transition_candidate,
)
from worksync.work.pool_store import (
    PoolWriteResult,
    prepare_pool_write,
    render_manifest,
    write_pool,
)
from worksync.work.schema import (
    DATE_STATUS_UNDATED,
    UNDATED_DATE,
    detect_type,
    is_entity_id,
    person_id_slug,
)
from worksync.work.since_last_check import USER_STATE_ZONE

EXTRACTION_RULE_VERSION = EXTRACTION_VERSION
POOL_SCAN_VERB = "pool_scan"
POOL_ADD_VERB = "pool_add"
POOL_INGEST_VERB = "ingest_meeting"
MEETING_TYPE = "meeting"
ACTIONS_HEADING = "actions"
HELD_STATUS = "held"
STATUS_REASONS = {
    "draft": "status_draft",
    "scheduled": "status_scheduled",
    "cancelled": "status_cancelled",
}
SKIP_REASONS = frozenset(
    {
        "not_meeting",
        "invalid_source",
        "missing_meeting_id",
        "unreliable_date",
        "status_draft",
        "status_scheduled",
        "status_cancelled",
        "status_missing",
        "status_invalid",
        "cutoff",
        "no_actions",
    }
)
PARSE_REASONS = frozenset(
    {
        "project_unassigned",
        "project_ambiguous",
        "owner_explicit",
        "owner_missing",
        "owner_ambiguous",
        "due_explicit",
        "due_missing",
        "due_ambiguous",
        "priority_explicit",
        "priority_missing",
    }
)
MAX_MEETING_ID_LENGTH = 60

_DATE_PREFIX = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})(?:[T ].*)?$")
_DATE_TOKEN = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_PRIORITY = re.compile(r"(?<![A-Za-z0-9])P([1-4])(?![0-9])", re.IGNORECASE)
_LIST_LINE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-*+])(?P<rest>[ \t]+.*)$")
_CHECKBOX = re.compile(r"^\[(?P<state>[ xX])\](?:[ \t]+(?P<text>.*\S.*))?$")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_AT_MENTION = re.compile(r"(?<![\w@])@(?P<name>[\w][\w'-]*)")
_LEADING_NAME = re.compile(r"^(?P<name>[^:—–]{1,80}?)[ \t]*(?P<sep>:|—|–)[ \t]*(?P<rest>.*\S.*)$")
_FENCE = re.compile(r"^[ \t]{0,3}(```+|~~~+)")


# --- meeting notes -------------------------------------------------------------------------


@dataclass(frozen=True)
class MeetingNote:
    """A meeting-family note read from the vault or rendered for a new-meeting apply."""

    path: str
    title: str
    content: str
    content_hash: str
    frontmatter: Mapping[str, Any]
    frontmatter_present: bool = True
    frontmatter_closed: bool = True
    frontmatter_malformed: bool = False

    @property
    def detected_type(self) -> str | None:
        return detect_type(self.frontmatter.get("type"))

    @property
    def meeting_id(self) -> str | None:
        return _clean_text(self.frontmatter.get("meeting_id"))

    @classmethod
    def from_text(cls, path: str, text: str, *, title: str | None = None) -> MeetingNote:
        """Build a note from its exact text; the content hash matches the bytes written."""
        frontmatter = read_frontmatter(text)
        headings = [(len(match.group(1)), match.group(2).strip()) for match in HEADING_RE.finditer(text)]
        resolved_title = (
            _clean_text(frontmatter.data.get("title"))
            or (headings[0][1] if headings else Path(path).stem)
            or Path(path).stem
        )
        return cls(
            path=Path(path).as_posix(),
            title=title or resolved_title,
            content=text,
            content_hash=sha256_bytes(text.encode("utf-8")),
            frontmatter=frontmatter.data,
            frontmatter_present=frontmatter.present,
            frontmatter_closed=frontmatter.closed,
            frontmatter_malformed=frontmatter.malformed,
        )

    @classmethod
    def from_record(cls, record: IndexRecord) -> MeetingNote:
        return cls(
            path=record.path,
            title=record.title,
            content=record.content,
            content_hash=record.content_hash,
            frontmatter=record.frontmatter,
            frontmatter_present=record.frontmatter_present,
            frontmatter_closed=record.frontmatter_closed,
            frontmatter_malformed=record.frontmatter_malformed,
        )

    @classmethod
    def from_file(cls, path: str | Path, vault: str | Path) -> MeetingNote:
        """Read one vault note; used by manual add to validate a real source meeting."""
        target = Path(path).expanduser().resolve()
        root = Path(vault).expanduser().resolve()
        try:
            relative = target.relative_to(root).as_posix()
        except ValueError as exc:
            raise PoolError("invalid_source", "A source meeting must be inside the vault.", 400) from exc
        if not target.is_file():
            raise PoolError("invalid_source", "The source meeting does not exist.", 400)
        text = target.read_bytes().decode("utf-8-sig", errors="replace")
        note = cls.from_text(relative, text)
        return replace(note, content_hash=sha256_file(target))


# --- context -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionContext:
    """The validated people/project index and the pool activation boundary."""

    pool_start_local_date: str
    people: Mapping[str, str]
    projects: Mapping[str, str]

    @classmethod
    def build(
        cls,
        *,
        pool_start_local_date: str,
        people: Iterable[str] = (),
        projects: Iterable[str] = (),
    ) -> ExtractionContext:
        try:
            date.fromisoformat(str(pool_start_local_date))
        except (TypeError, ValueError) as exc:
            raise PoolError("bad_start", "pool_start_local_date must be an ISO date.", 400) from exc
        return cls(
            pool_start_local_date=str(pool_start_local_date),
            people=_name_map(people),
            projects=_name_map(projects),
        )

    @property
    def start_date(self) -> date:
        return date.fromisoformat(self.pool_start_local_date)

    def resolve_person(self, value: object) -> str | None:
        return _resolve_known(value, self.people)

    def resolve_project(self, value: object) -> str | None:
        return self.projects.get(_name_key(value))


def build_context(
    records: Iterable[IndexRecord],
    *,
    pool_start_local_date: str,
) -> ExtractionContext:
    """Build the validated person/project index from parsed vault records."""
    people: set[str] = set()
    projects: set[str] = set()
    for record in records:
        detected = detect_type(record.frontmatter.get("type"))
        if detected == "person":
            people.update(_entity_names(record, "person_id"))
        elif detected == "project":
            projects.update(_entity_names(record, "project_id"))
    return ExtractionContext.build(
        pool_start_local_date=pool_start_local_date,
        people=people,
        projects=projects,
    )


def _entity_names(record: IndexRecord, id_field: str) -> set[str]:
    names = {record.title, Path(record.path).stem}
    names.update(record.aliases)
    identifier = _clean_text(record.frontmatter.get(id_field))
    if identifier:
        names.add(identifier)
    return {name for name in (_clean_text(item) for item in names) if name}


# --- classification ------------------------------------------------------------------------


@dataclass(frozen=True)
class MeetingClassification:
    """The eligibility decision for one meeting-like note, with its reason code."""

    meeting: MeetingNote
    meeting_id: str | None
    meeting_date: str | None
    reason: str

    @property
    def eligible(self) -> bool:
        return self.reason == "eligible"

    @property
    def skipped(self) -> bool:
        return not self.eligible


def classify_meeting(meeting: MeetingNote, *, context: ExtractionContext) -> MeetingClassification:
    """Return the deterministic eligibility decision for one note."""
    if meeting.frontmatter_malformed or not meeting.frontmatter_closed or not meeting.content.strip():
        return MeetingClassification(meeting, None, None, "invalid_source")
    if meeting.detected_type != MEETING_TYPE:
        return MeetingClassification(meeting, meeting.meeting_id, _meeting_date(meeting), "not_meeting")

    meeting_id = meeting.meeting_id
    if not meeting_id or not is_entity_id(meeting_id):
        return MeetingClassification(meeting, meeting_id, _meeting_date(meeting), "missing_meeting_id")

    meeting_date = _meeting_date(meeting)
    if meeting_date is None:
        return MeetingClassification(meeting, meeting_id, None, "unreliable_date")

    reason = _status_reason(meeting.frontmatter.get("status"))
    if reason is not None:
        return MeetingClassification(meeting, meeting_id, meeting_date, reason)

    if date.fromisoformat(meeting_date) < context.start_date:
        return MeetingClassification(meeting, meeting_id, meeting_date, "cutoff")

    if _actions_section(meeting.content) is None:
        return MeetingClassification(meeting, meeting_id, meeting_date, "no_actions")

    return MeetingClassification(meeting, meeting_id, meeting_date, "eligible")


def _status_reason(value: object) -> str | None:
    """Return the skip reason for a non-finalized status, or ``None`` for ``held``."""
    text = _clean_text(value)
    if text is None:
        return "status_missing"
    normalized = text.casefold()
    if normalized == HELD_STATUS:
        return None
    return STATUS_REASONS.get(normalized, "status_invalid")


def _meeting_date(meeting: MeetingNote) -> str | None:
    """Return a reliable ISO meeting date, or ``None`` for undated/template values."""
    if _clean_text(meeting.frontmatter.get("date_status")) == DATE_STATUS_UNDATED:
        return None
    raw = meeting.frontmatter.get("date")
    if isinstance(raw, datetime):
        candidate = raw.date().isoformat()
    elif isinstance(raw, date):
        candidate = raw.isoformat()
    else:
        text = _clean_text(raw)
        match = _DATE_PREFIX.match(text) if text else None
        if match is None:
            return None
        candidate = match.group("date")
    if candidate == UNDATED_DATE:
        return None
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


# --- the parser ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedAction:
    """One eligible action line, with only explicitly evidenced field values."""

    line: int
    quote: str
    checked: bool | None
    title: str
    normalized: str
    occurrence: int
    project: str | None
    owner: str | None
    due: str | None
    priority: str | None
    parse_quality: str
    parse_reasons: tuple[str, ...]


def parse_actions(meeting: MeetingNote, *, context: ExtractionContext) -> tuple[ParsedAction, ...]:
    """Parse the ``## Actions`` section into eligible action lines, in source order."""
    section = _actions_section(meeting.content)
    if section is None:
        return ()
    project, project_reason = _meeting_project(meeting, context=context)
    attendees = _meeting_attendees(meeting, context=context)
    occurrences: dict[str, int] = {}
    actions: list[ParsedAction] = []
    for number, raw, fenced in section:
        if fenced:
            continue
        line = raw.rstrip()
        entry = _split_entry(line)
        if entry is None:
            continue
        checked, body = entry
        owner, title, owner_ambiguous = _owner_and_title(body, attendees=attendees)
        due, due_reason = _due(body)
        priority = _priority(body)
        normalized = normalized_line(line)
        occurrence = occurrences.get(normalized, 0)
        occurrences[normalized] = occurrence + 1
        reasons: list[str] = []
        if project is None:
            reasons.append(project_reason or "project_unassigned")
        if owner is None:
            reasons.append("owner_ambiguous" if owner_ambiguous else "owner_missing")
        else:
            reasons.append("owner_explicit")
        reasons.append(due_reason)
        reasons.append("priority_explicit" if priority else "priority_missing")
        actions.append(
            ParsedAction(
                line=number,
                quote=line,
                checked=checked,
                title=title,
                normalized=normalized,
                occurrence=occurrence,
                project=project,
                owner=owner,
                due=due,
                priority=priority,
                parse_quality=_parse_quality(project, owner, due, priority),
                parse_reasons=tuple(reasons),
            )
        )
    return tuple(actions)


def normalized_line(line: str) -> str:
    """Return the identity-normalized form of one raw action line."""
    entry = _split_entry(line)
    text = entry[1] if entry is not None else (line or "")
    return unicodedata.normalize("NFC", _collapse(text)).casefold()


def _split_entry(line: str) -> tuple[bool | None, str] | None:
    """Split one bullet line into ``(checked, text)``; ``None`` when it is not an entry."""
    match = _LIST_LINE.match(line.rstrip())
    if match is None:
        return None
    rest = match.group("rest").lstrip()
    checkbox = _CHECKBOX.match(rest)
    if checkbox is not None:
        text = checkbox.group("text")
        if text is None:
            return None
        return (checkbox.group("state").casefold() == "x", _collapse(text))
    text = _collapse(rest)
    return (None, text) if text else None


def _actions_section(content: str) -> tuple[tuple[int, str, bool], ...] | None:
    """Return ``(line_number, raw_line, inside_fence)`` for the ``## Actions`` section."""
    lines = content.splitlines()
    in_fence = False
    start: int | None = None
    collected: list[tuple[int, str, bool]] = []
    for index, raw in enumerate(lines, start=1):
        fence = _FENCE.match(raw)
        if fence is not None:
            in_fence = not in_fence
            if start is not None:
                collected.append((index, raw, True))
            continue
        if in_fence:
            if start is not None:
                collected.append((index, raw, True))
            continue
        heading = HEADING_RE.match(raw)
        if heading is not None:
            level = len(heading.group(1))
            text = heading.group(2).strip().rstrip("#").strip()
            if start is None:
                if level == 2 and text.casefold() == ACTIONS_HEADING:
                    start = index
                continue
            if level <= 2:
                break
        if start is not None:
            collected.append((index, raw, False))
    return None if start is None else tuple(collected)


def _meeting_project(meeting: MeetingNote, *, context: ExtractionContext) -> tuple[str | None, str]:
    listed = [
        *_as_tuple(meeting.frontmatter.get("projects")),
        *([meeting.frontmatter["project"]] if meeting.frontmatter.get("project") else []),
    ]
    valid = []
    for value in listed:
        resolved = context.resolve_project(value)
        if resolved is not None and resolved not in valid:
            valid.append(resolved)
    if len(valid) == 1:
        return valid[0], ""
    return None, ("project_ambiguous" if len(valid) > 1 else "project_unassigned")


def _meeting_attendees(meeting: MeetingNote, *, context: ExtractionContext) -> Mapping[str, str]:
    names: dict[str, str] = dict(context.people)
    for value in _as_tuple(meeting.frontmatter.get("attendees")) + _as_tuple(meeting.frontmatter.get("people")):
        resolved = context.resolve_person(value)
        label = resolved or _link_text(value)
        if label:
            names[_name_key(label)] = label
    return names


def _owner_and_title(body: str, *, attendees: Mapping[str, str]) -> tuple[str | None, str, bool]:
    """Resolve only explicit owner evidence and strip a leading owner prefix from the title.

    The third value reports ambiguous evidence (two different explicit people), which is
    recorded as a parse reason and never resolved to a guessed owner.
    """
    leading_link = _WIKILINK.match(body)
    if leading_link is not None:
        name = leading_link.group(1)
        remainder = body[leading_link.end() :].lstrip()
        if remainder[:1] in {":", "—", "–"}:
            remainder = remainder[1:].lstrip()
            resolved = _resolve_known(name, attendees)
            if resolved is not None:
                return resolved, _collapse(remainder), False

    leading_mention = _AT_MENTION.match(body)
    if leading_mention is not None:
        name = leading_mention.group("name")
        remainder = body[leading_mention.end() :].lstrip()
        if remainder[:1] in {":", "—", "–"}:
            remainder = remainder[1:].lstrip()
        resolved = _resolve_known(name, attendees)
        if resolved is not None and remainder:
            return resolved, _collapse(remainder), False

    leading_name = _LEADING_NAME.match(body)
    if leading_name is not None:
        name = leading_name.group("name").strip()
        resolved = _resolve_known(name, attendees)
        if resolved is not None:
            return resolved, _collapse(leading_name.group("rest")), False

    found: list[str] = []
    for match in _WIKILINK.finditer(body):
        resolved = _resolve_known(match.group(1), attendees)
        if resolved is not None:
            found.append(resolved)
    for match in _AT_MENTION.finditer(body):
        resolved = _resolve_known(match.group("name"), attendees)
        if resolved is not None:
            found.append(resolved)
    distinct = list(dict.fromkeys(found))
    if len(distinct) == 1:
        return distinct[0], _collapse(body), False
    return None, _collapse(body), len(distinct) > 1


def _due(body: str) -> tuple[str | None, str]:
    values = []
    for match in _DATE_TOKEN.finditer(body):
        try:
            values.append(date.fromisoformat(match.group(1)).isoformat())
        except ValueError:
            continue
    distinct = list(dict.fromkeys(values))
    if len(distinct) == 1:
        return distinct[0], "due_explicit"
    return None, ("due_ambiguous" if len(distinct) > 1 else "due_missing")


def _priority(body: str) -> str | None:
    for match in _PRIORITY.finditer(body):
        candidate = f"P{match.group(1)}"
        if candidate in PRIORITIES:
            return candidate
    return None


def _parse_quality(project: str | None, owner: str | None, due: str | None, priority: str | None) -> str:
    if project is not None and owner is not None and due is not None:
        return "complete"
    if any(value is not None for value in (project, owner, due, priority)):
        return "partial"
    return "minimal"


# --- candidates ----------------------------------------------------------------------------


def candidate_id(meeting_id: str, normalized: str, occurrence: int) -> str:
    """Return the deterministic candidate id for a meeting line."""
    payload = "\x1f".join((str(meeting_id), normalized, str(occurrence)))
    return "cand-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ExtractionResult:
    """One meeting's eligibility decision, extracted candidates, and index entry."""

    classification: MeetingClassification
    candidates: tuple[PoolCandidate, ...]
    entry: MeetingExtraction


def extract_meeting(
    meeting: MeetingNote,
    *,
    context: ExtractionContext,
    now: datetime | None = None,
) -> ExtractionResult:
    """Classify one meeting and build its deterministic candidates."""
    when = (now or datetime.now(UTC)).astimezone(UTC)
    classification = classify_meeting(meeting, context=context)
    meeting_id = classification.meeting_id or ""
    candidates: tuple[PoolCandidate, ...] = ()
    if classification.eligible:
        candidates = tuple(
            _candidate(action, classification, now=when) for action in parse_actions(meeting, context=context)
        )
    entry = MeetingExtraction(
        meeting_id=meeting_id or meeting.path,
        path=meeting.path,
        title=meeting.title,
        date=classification.meeting_date,
        content_hash=meeting.content_hash,
        eligibility="eligible" if classification.eligible else "skipped",
        reason=classification.reason,
        extraction_version=EXTRACTION_RULE_VERSION,
        candidate_ids=tuple(candidate.id for candidate in candidates),
        extracted_at=when.isoformat(),
    )
    return ExtractionResult(classification=classification, candidates=candidates, entry=entry)


def _candidate(
    action: ParsedAction,
    classification: MeetingClassification,
    *,
    now: datetime,
) -> PoolCandidate:
    meeting = classification.meeting
    return PoolCandidate(
        id=candidate_id(classification.meeting_id or "", action.normalized, action.occurrence),
        title=action.title,
        state="new",
        state_reason="meeting_extraction",
        source=PoolSource(
            kind="meeting",
            meeting_id=classification.meeting_id,
            meeting_path=meeting.path,
            meeting_date=classification.meeting_date,
            content_hash=meeting.content_hash,
            line=action.line,
            occurrence=action.occurrence,
            quote=action.quote,
            checked=action.checked,
            rule_version=EXTRACTION_RULE_VERSION,
            extracted_at=now.isoformat(),
        ),
        task_fields={
            key: TaskFieldValue(extracted=value, effective=value)
            for key, value in (
                ("project", action.project),
                ("owner", action.owner),
                ("due", action.due),
                ("priority", action.priority),
            )
        },
        parse_quality=action.parse_quality,
        parse_reasons=action.parse_reasons,
        history=(
            HistoryEntry(
                at=now.isoformat(),
                by="extractor",
                from_state=None,
                to_state="new",
                reason="meeting_extraction",
                op=EXTRACTION_RULE_VERSION,
            ),
        ),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )


# --- re-extraction -------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionPlan:
    """The pool state after merging extraction results, with its change summary."""

    manifest: PoolManifest
    results: tuple[ExtractionResult, ...] = ()
    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    obsoleted: tuple[str, ...] = ()
    meetings_changed: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.obsoleted or self.meetings_changed)


def merge_extraction(
    manifest: PoolManifest,
    results: Sequence[ExtractionResult],
    *,
    now: datetime | None = None,
) -> ExtractionPlan:
    """Merge extraction results into a manifest, preserving every human-owned field.

    Unchanged lines update provenance/extracted facts only. A materially changed line creates a
    new candidate and obsoletes the unpromoted old one (``source_line_changed``); an unpaired
    orphan is ``source_line_removed``. Promoted candidates are terminal. No decision transfers.
    """
    when = (now or datetime.now(UTC)).astimezone(UTC)
    when_text = when.isoformat()
    existing_by_meeting: dict[str, list[PoolCandidate]] = {}
    for candidate in manifest.candidates:
        if candidate.source.kind == "meeting" and candidate.source.meeting_id:
            existing_by_meeting.setdefault(candidate.source.meeting_id, []).append(candidate)
    index = {entry.meeting_id: entry for entry in manifest.meetings}
    order = [entry.meeting_id for entry in manifest.meetings]
    replacements: dict[str, PoolCandidate] = {}
    appended: list[PoolCandidate] = []
    created: list[str] = []
    updated: list[str] = []
    obsoleted: list[str] = []
    meetings_changed = False

    for result in results:
        if result.classification.reason == "not_meeting":
            continue
        key = result.entry.meeting_id
        if key not in index:
            order.append(key)
        current_entry = index.get(key)
        merged_entry = _merge_entry(current_entry, result.entry)
        if merged_entry is not current_entry:
            index[key] = merged_entry
            meetings_changed = True

        if not (result.classification.eligible or result.classification.reason == "no_actions"):
            continue

        existing = existing_by_meeting.get(key, [])
        offers = {candidate.id: candidate for candidate in result.candidates}
        existing_ids = {candidate.id for candidate in existing}
        orphans_old: list[PoolCandidate] = []
        for old in existing:
            offer = offers.get(old.id)
            if offer is None:
                orphans_old.append(old)
                continue
            merged = _update_provenance(old, offer, when=when_text)
            if merged is not old:
                replacements[old.id] = merged
                updated.append(old.id)
        orphans_new = [candidate for candidate in result.candidates if candidate.id not in existing_ids]

        paired: set[str] = set()
        for old, _new in _pair_changed(orphans_old, orphans_new):
            paired.add(old.id)
            if not _can_obsolete(old):
                continue
            replacements[old.id] = transition_candidate(
                old,
                "obsolete",
                by="extractor",
                reason="source_line_changed",
                at=when,
                op=EXTRACTION_RULE_VERSION,
            )
            obsoleted.append(old.id)
        for old in orphans_old:
            if old.id in paired or not _can_obsolete(old):
                continue
            replacements[old.id] = transition_candidate(
                old,
                "obsolete",
                by="extractor",
                reason="source_line_removed",
                at=when,
                op=EXTRACTION_RULE_VERSION,
            )
            obsoleted.append(old.id)
        for candidate in orphans_new:
            appended.append(candidate)
            created.append(candidate.id)

    if not (replacements or appended or meetings_changed):
        return ExtractionPlan(manifest=manifest, results=tuple(results))

    merged_manifest = replace(
        manifest,
        candidates=tuple(replacements.get(candidate.id, candidate) for candidate in manifest.candidates)
        + tuple(appended),
        meetings=tuple(index[key] for key in order),
    )
    return ExtractionPlan(
        manifest=merged_manifest,
        results=tuple(results),
        created=tuple(created),
        updated=tuple(updated),
        obsoleted=tuple(obsoleted),
        meetings_changed=meetings_changed,
    )


def _merge_entry(current: MeetingExtraction | None, offered: MeetingExtraction) -> MeetingExtraction:
    if current is None:
        return offered
    if current == replace(offered, extracted_at=current.extracted_at):
        return current
    return offered


def _source_provenance(source: PoolSource) -> tuple[object, ...]:
    return (
        source.meeting_path,
        source.meeting_date,
        source.content_hash,
        source.line,
        source.occurrence,
        source.quote,
        source.checked,
        source.rule_version,
    )


def _update_provenance(old: PoolCandidate, offered: PoolCandidate, *, when: str) -> PoolCandidate:
    """Return the candidate with refreshed extracted facts, or the same object when unchanged."""
    unchanged = (
        old.title == offered.title
        and old.parse_quality == offered.parse_quality
        and old.parse_reasons == offered.parse_reasons
        and all(
            old.task_fields[key].extracted == offered.task_fields[key].extracted
            for key in ("project", "owner", "due", "priority")
        )
        and _source_provenance(old.source) == _source_provenance(offered.source)
    )
    if unchanged:
        return old
    fields = {}
    for key in ("project", "owner", "due", "priority"):
        human = old.task_fields[key].human
        extracted = offered.task_fields[key].extracted
        fields[key] = TaskFieldValue(
            extracted=extracted,
            human=human,
            effective=human if human is not None else extracted,
        )
    return replace(
        old,
        title=offered.title,
        source=replace(offered.source, extracted_at=when),
        task_fields=fields,
        parse_quality=offered.parse_quality,
        parse_reasons=offered.parse_reasons,
        revision=old.revision + 1,
        updated_at=when,
    )


def _pair_changed(
    orphans_old: Sequence[PoolCandidate], orphans_new: Sequence[PoolCandidate]
) -> tuple[tuple[PoolCandidate, PoolCandidate], ...]:
    """Pair orphaned candidates with their most similar replacement (deterministically)."""
    pairs: list[tuple[PoolCandidate, PoolCandidate]] = []
    used: set[str] = set()
    for old in orphans_old:
        if not _can_obsolete(old):
            continue
        old_tokens = _tokens(old.title)
        best: PoolCandidate | None = None
        best_score = 0.0
        for new in orphans_new:
            if new.id in used:
                continue
            score = _similarity(old_tokens, _tokens(new.title))
            if score > best_score:
                best, best_score = new, score
        if best is not None and best_score >= 0.5:
            used.add(best.id)
            pairs.append((old, best))
    return tuple(pairs)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(token for token in re.split(r"[^\w]+", value.casefold()) if token)


def _similarity(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _can_obsolete(candidate: PoolCandidate) -> bool:
    """Extraction may only obsolete a live, unpromoted candidate."""
    return candidate.state not in {"promoted", "obsolete"}


# --- scan ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class PoolScanResult:
    """The outcome of a pool scan: the planned state, whether it committed, and a preview."""

    plan: ExtractionPlan
    dry_run: bool
    committed: bool
    changes: tuple[dict[str, Any], ...] = ()
    write: PoolWriteResult | None = None


def scan_pool(
    vault_root: str | Path,
    runtime_root: str | Path,
    *,
    reviewer: str,
    reason: str,
    meeting_id: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> PoolScanResult:
    """Re-read eligible meetings and merge them into the pool without touching the vault.

    Uses exactly the same eligibility and extraction rules as the new-meeting apply. A dry run
    returns the planned manifest and a preview of the single ``user_state`` update.
    """
    when = (now or datetime.now(UTC)).astimezone(UTC)
    manifest = read_manifest(runtime_root)
    records = scan_vault(vault_root)
    context = build_context(records, pool_start_local_date=manifest.pool_start_local_date)
    notes = [
        MeetingNote.from_record(record)
        for record in records
        if detect_type(record.frontmatter.get("type")) == MEETING_TYPE
    ]
    if meeting_id is not None:
        notes = [note for note in notes if note.meeting_id == meeting_id]
        if not notes:
            raise PoolError("unknown_meeting", f"No meeting with id: {meeting_id}", 404)
    results = tuple(extract_meeting(note, context=context, now=when) for note in notes)
    plan = merge_extraction(manifest, results, now=when)
    if dry_run:
        return PoolScanResult(
            plan=plan,
            dry_run=True,
            committed=False,
            changes=_preview_write(runtime_root, plan.manifest, reviewer=reviewer, reason=reason, when=when),
        )
    if not plan.changed:
        return PoolScanResult(plan=plan, dry_run=False, committed=False)
    write = write_pool(
        vault_root,
        runtime_root,
        plan.manifest,
        reviewer=reviewer,
        reason=reason,
        expected_revision=manifest.revision,
        verb=POOL_SCAN_VERB,
        now=when,
    )
    return PoolScanResult(
        plan=replace(plan, manifest=write.manifest),
        dry_run=False,
        committed=write.committed,
        changes=write.changes,
        write=write,
    )


def _preview_write(
    runtime_root: str | Path,
    manifest: PoolManifest,
    *,
    reviewer: str,
    reason: str,
    when: datetime,
    verb: str = POOL_SCAN_VERB,
) -> tuple[dict[str, Any], ...]:
    saved = prepare_pool_write(manifest, reviewer=reviewer, reason=reason, when=when, verb=verb)
    target = pool_path(runtime_root)
    return (
        {
            "kind": "update",
            "zone": USER_STATE_ZONE,
            "path": str(target),
            "destination": None,
            "before": sha256_file(target) if target.is_file() else None,
            "after": sha256_bytes(render_manifest(saved).encode("utf-8")),
        },
    )


# --- manual add ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualAddResult:
    """The outcome of an explicit manual candidate add."""

    candidate: PoolCandidate
    manifest: PoolManifest
    created: bool
    write: PoolWriteResult | None = None


def manual_candidate_id(request_id: str) -> str:
    """Return the stable candidate id derived from a client request id."""
    payload = "\x1f".join(("manual", str(request_id)))
    return "cand-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_manual_candidate(
    *,
    title: str,
    initiator: str,
    reason: str,
    provenance_classification: str,
    provenance_note: str,
    request_id: str,
    source_meeting: MeetingNote | None = None,
    project: str | None = None,
    owner: str | None = None,
    due: str | None = None,
    priority: str | None = None,
    now: datetime | None = None,
) -> PoolCandidate:
    """Build a quote-free manual candidate from explicit human input only."""
    when = (now or datetime.now(UTC)).astimezone(UTC)
    title = _required(title, "missing_title", "A manual candidate requires a title.")
    initiator = _required(initiator, "missing_initiator", "A manual candidate requires an initiator.")
    reason = _required(reason, "missing_reason", "A manual candidate requires a reason.")
    note_text = _required(provenance_note, "missing_provenance", "A manual candidate requires a provenance note.")
    request = _required(request_id, "missing_request_id", "A manual candidate requires a request id.")
    classification = _required(
        provenance_classification, "invalid_provenance", "A manual candidate requires a provenance classification."
    )
    if classification not in MANUAL_PROVENANCE_CLASSES:
        raise PoolError(
            "invalid_provenance",
            f"A manual candidate provenance classification must be one of {MANUAL_PROVENANCE_CLASSES}.",
            422,
        )
    values = {
        "project": _optional(project),
        "owner": _optional(owner),
        "due": _validated_due(due),
        "priority": _validated_priority(priority),
    }
    return PoolCandidate(
        id=manual_candidate_id(request),
        title=title,
        state="new",
        state_reason="manual_add",
        source=PoolSource(
            kind="manual",
            meeting_id=source_meeting.meeting_id if source_meeting is not None else None,
            meeting_path=source_meeting.path if source_meeting is not None else None,
            meeting_date=_meeting_date(source_meeting) if source_meeting is not None else None,
            initiated_by=initiator,
            provenance_classification=classification,
            provenance_note=note_text,
        ),
        task_fields={
            key: TaskFieldValue(extracted=None, human=value, effective=value) for key, value in values.items()
        },
        history=(
            HistoryEntry(
                at=when.isoformat(),
                by=initiator,
                from_state=None,
                to_state="new",
                reason=reason,
                op="manual_add",
            ),
        ),
        created_at=when.isoformat(),
        updated_at=when.isoformat(),
    )


def add_manual(
    vault_root: str | Path,
    runtime_root: str | Path,
    *,
    title: str,
    initiator: str,
    reason: str,
    provenance_classification: str,
    provenance_note: str,
    request_id: str,
    source_meeting: MeetingNote | str | Path | None = None,
    project: str | None = None,
    owner: str | None = None,
    due: str | None = None,
    priority: str | None = None,
    reviewer: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> ManualAddResult:
    """Add one explicit manual candidate; retrying the same request id is idempotent.

    Manual add is the only pre-cutoff exception and never invents a meeting, hash, quote, or
    line. It uses the same candidate schema, lifecycle, and gateway write path as extraction.
    """
    when = (now or datetime.now(UTC)).astimezone(UTC)
    manifest = read_manifest(runtime_root)
    resolved_source = _resolve_source_meeting(vault_root, source_meeting) if source_meeting is not None else None
    candidate = build_manual_candidate(
        title=title,
        initiator=initiator,
        reason=reason,
        provenance_classification=provenance_classification,
        provenance_note=provenance_note,
        request_id=request_id,
        source_meeting=resolved_source,
        project=project,
        owner=owner,
        due=due,
        priority=priority,
        now=when,
    )
    existing = next((item for item in manifest.candidates if item.id == candidate.id), None)
    if existing is not None:
        if existing.source.kind != "manual":
            raise PoolError("candidate_exists", "A candidate with that id already exists.", 409)
        return ManualAddResult(candidate=existing, manifest=manifest, created=False)
    planned = replace(manifest, candidates=(*manifest.candidates, candidate))
    if dry_run:
        return ManualAddResult(candidate=candidate, manifest=planned, created=True)
    write = write_pool(
        vault_root,
        runtime_root,
        planned,
        reviewer=reviewer or candidate.source.initiated_by or initiator,
        reason=reason,
        expected_revision=manifest.revision,
        verb=POOL_ADD_VERB,
        now=when,
    )
    return ManualAddResult(candidate=candidate, manifest=write.manifest, created=True, write=write)


def _resolve_source_meeting(vault_root: str | Path, value: MeetingNote | str | Path) -> MeetingNote:
    if isinstance(value, MeetingNote):
        note = value
    else:
        text = str(value).strip()
        if not text:
            raise PoolError("invalid_source", "A source meeting reference must not be blank.", 400)
        try:
            note = MeetingNote.from_file(Path(vault_root) / text, vault_root)
        except (OSError, PoolError) as exc:
            note = _meeting_by_id(vault_root, text)
            if note is None:
                if isinstance(exc, PoolError):
                    raise
                raise PoolError("invalid_source", "The source meeting does not exist.", 400) from exc
    if note.detected_type != MEETING_TYPE:
        raise PoolError("not_meeting", "A manual source must be a finalized meeting note.", 422)
    if not note.meeting_id or not is_entity_id(note.meeting_id):
        raise PoolError("missing_meeting_id", "A manual source meeting requires a valid meeting id.", 422)
    return note


def _meeting_by_id(vault_root: str | Path, meeting_id: str) -> MeetingNote | None:
    for record in scan_vault(vault_root):
        if detect_type(record.frontmatter.get("type")) != MEETING_TYPE:
            continue
        if _clean_text(record.frontmatter.get("meeting_id")) == meeting_id:
            return MeetingNote.from_record(record)
    return None


def _required(value: object, code: str, message: str) -> str:
    text = _clean_text(value)
    if text is None:
        raise PoolError(code, message, 400)
    return text


def _optional(value: object) -> str | None:
    return _clean_text(value)


def _validated_due(value: object) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise PoolError("invalid_due", "A manual due date must be an ISO date.", 422) from exc


def _validated_priority(value: object) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    candidate = text.upper()
    if candidate not in PRIORITIES:
        raise PoolError("invalid_priority", "A manual priority must be P1-P4.", 422)
    return candidate


# --- new-meeting ingest --------------------------------------------------------------------


@dataclass(frozen=True)
class NewMeeting:
    """A meeting note rendered for a new-meeting apply but not yet written."""

    path: str
    content: str


@dataclass(frozen=True)
class StagedPoolWrite:
    """The pool update (manifest plus gateway op) that belongs to one ingest transaction."""

    manifest: PoolManifest
    plan: ExtractionPlan
    op: FileOp


def stage_new_meetings(
    vault_root: str | Path,
    runtime_root: str | Path,
    meetings: Sequence[NewMeeting],
    *,
    reviewer: str,
    reason: str,
    now: datetime | None = None,
) -> StagedPoolWrite | None:
    """Plan the pool update for newly rendered meetings, or ``None`` before pool init.

    The returned op is a ``user_state`` update with the current pool SHA, so the caller can
    place it in the same ``ChangeSet`` as the meeting create (one coherent transaction).
    """
    if not meetings or not pool_path(runtime_root).is_file():
        return None
    when = (now or datetime.now(UTC)).astimezone(UTC)
    manifest = read_manifest(runtime_root)
    records = scan_vault(vault_root)
    context = build_context(records, pool_start_local_date=manifest.pool_start_local_date)
    results = tuple(
        extract_meeting(
            MeetingNote.from_text(meeting.path, meeting.content),
            context=context,
            now=when,
        )
        for meeting in meetings
    )
    plan = merge_extraction(manifest, results, now=when)
    saved = prepare_pool_write(plan.manifest, reviewer=reviewer, reason=reason, when=when, verb=POOL_INGEST_VERB)
    op = FileOp(
        "update",
        Path(POOL_FILENAME),
        USER_STATE_ZONE,
        content=render_manifest(saved),
        expected=sha256_file(pool_path(runtime_root)),
    )
    return StagedPoolWrite(manifest=saved, plan=plan, op=op)


# --- helpers -------------------------------------------------------------------------------


def _clean_text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _collapse(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _name_key(value: object) -> str:
    text = _link_text(_clean_text(value) or "")
    return _collapse(text).casefold()


def _resolve_known(value: object, names: Mapping[str, str]) -> str | None:
    """Resolve an exact name, else a unique known-name prefix (never a guess)."""
    key = _name_key(value)
    if not key:
        return None
    exact = names.get(key)
    if exact is not None:
        return exact
    matches = {label for name, label in names.items() if name.startswith(f"{key} ")}
    return matches.pop() if len(matches) == 1 else None


def _link_text(value: object) -> str:
    text = _clean_text(value) or ""
    match = _WIKILINK.fullmatch(text)
    if match is not None:
        text = match.group(1)
    return text.strip().lstrip("@").strip()


def _name_map(values: Iterable[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        label = _link_text(value)
        if label:
            mapping.setdefault(_name_key(label), label)
    return mapping


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list | tuple):
        return tuple(text for item in value if (text := _clean_text(item)))
    text = _clean_text(value)
    return (text,) if text else ()


def meeting_id_for(title: str, meeting_date: str, external_id: str | None = None) -> str:
    """Derive a stable, bounded kebab-case meeting id from a title, date, and external id."""
    tail = f"-{meeting_date}"
    suffix = person_id_slug(external_id or "")
    if suffix:
        tail = f"{tail}-{suffix}"
    head = person_id_slug(title) or "meeting"
    budget = MAX_MEETING_ID_LENGTH - len(tail)
    if budget < 8:
        return (head + tail)[:MAX_MEETING_ID_LENGTH].strip("-")
    head = head[:budget].strip("-") or "meeting"
    return f"{head}{tail}"


__all__ = [
    "EXTRACTION_RULE_VERSION",
    "PARSE_REASONS",
    "SKIP_REASONS",
    "ExtractionContext",
    "ExtractionPlan",
    "ExtractionResult",
    "ManualAddResult",
    "MeetingClassification",
    "MeetingNote",
    "ParsedAction",
    "PoolScanResult",
    "add_manual",
    "build_context",
    "build_manual_candidate",
    "candidate_id",
    "classify_meeting",
    "extract_meeting",
    "manual_candidate_id",
    "meeting_id_for",
    "merge_extraction",
    "normalized_line",
    "parse_actions",
    "scan_pool",
]
