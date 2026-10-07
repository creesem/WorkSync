"""Schema detection and entity construction from inventory records.

Turns an :class:`~worksync.inventory.parse.IndexRecord` into a typed work entity.
Notes whose ``type`` is absent or unknown are not work entities and are skipped
without error. The retired legacy ``task`` type reads as ``action``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from worksync.inventory.parse import IndexRecord
from worksync.work.dates import parse_iso_date
from worksync.work.models import (
    Action,
    EntityBase,
    EntityType,
    Meeting,
    Person,
    Project,
    Ticket,
)

OPERATOR_TYPE_VALUES: tuple[str, ...] = tuple(member.value for member in EntityType)
LEGACY_TYPE_ALIASES: dict[str, str] = {"task": "action"}
LEGACY_TASK_STATUS: dict[str, str] = {
    "todo": "open",
    "inbox": "open",
    "active": "in_progress",
    "complete": "done",
    "dropped": "cancelled",
}
ACTION_STATUS_VALUES = frozenset({"open", "in_progress", "waiting", "watch", "parked", "done", "cancelled"})
PROJECT_STATUS_VALUES = frozenset({"active", "paused", "blocked", "done", "archived"})
PROJECT_STATUS_ALIASES: dict[str, str] = {"complete": "done"}
PERSON_STATUS_VALUES = frozenset({"active", "inactive"})
MEETING_STATUS_VALUES = frozenset({"scheduled", "held", "cancelled"})
UNDATED_DATE = "1970-01-01"
DATE_STATUS_UNDATED = "undated"
_FILENAME_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def detect_type(value: object) -> str | None:
    """Return the work type named by a ``type`` value, or ``None``.

    ``task`` maps to ``action``; case and quotes are normalized.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().strip("\"'").casefold()
    text = LEGACY_TYPE_ALIASES.get(text, text)
    return text if text in OPERATOR_TYPE_VALUES else None


def _priority_mapping(value: object) -> tuple[bool, str | None]:
    """Return ``(mappable, canonical)`` for a priority value.

    ``canonical`` of ``None`` means the value normalizes to unset. ``mappable`` of
    ``False`` means the value is outside the mapping.
    """
    if value is None:
        return True, None
    text = str(value).strip()
    if not text or text.casefold() in {"medium", "none", "null"}:
        return True, None
    upper = text.upper()
    if upper in {"P1", "P2", "P3", "P4"}:
        return True, upper
    if text.isdigit():
        number = int(text)
        if 1 <= number <= 3:
            return True, f"P{number}"
        if 4 <= number <= 7:
            return True, "P4"
    return False, None


def normalize_priority(value: object) -> str | None:
    """Map a legacy or canonical priority to ``P1``-``P4`` (or ``None``).

    Unknown values pass through unchanged so the tolerant reader can still surface them.
    """
    mappable, canonical = _priority_mapping(value)
    return canonical if mappable else str(value).strip()


def canonical_priority(value: object) -> tuple[bool, str | None]:
    """Map a present ``priority`` value to ``(mappable, canonical)`` for the migration.

    ``canonical`` of ``None`` means the value normalizes to unset and the key is
    removed. ``mappable`` of ``False`` means the value is outside the mapping and must
    not be guessed.
    """
    return _priority_mapping(value)


_PRIORITY_RANK: dict[str, int] = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def priority_rank(value: object) -> int | None:
    """Return the canonical rank ``P1``->1 … ``P4``->4, or ``None`` when unset/unknown.

    The single owner of priority ordering, so ranking callers never re-encode it.
    """
    return _PRIORITY_RANK.get(normalize_priority(value) or "")


def _canonical_status(value: object, aliases: dict[str, str], allowed: frozenset[str]) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = aliases.get(text.casefold(), text.casefold())
    return key if key in allowed else None


def canonical_action_status(value: object) -> str | None:
    """Map a legacy or canonical action status to its canonical value, or ``None``."""
    return _canonical_status(value, LEGACY_TASK_STATUS, ACTION_STATUS_VALUES)


def canonical_project_status(value: object) -> str | None:
    """Map a legacy or canonical project status to its canonical value, or ``None``."""
    return _canonical_status(value, PROJECT_STATUS_ALIASES, PROJECT_STATUS_VALUES)


def canonical_person_status(value: object) -> str | None:
    """Map a legacy or canonical person status to its canonical value, or ``None``."""
    return _canonical_status(value, {}, PERSON_STATUS_VALUES)


def canonical_meeting_status(value: object, *, when: date) -> str | None:
    """Return ``held`` for a date on or before *when*, else ``scheduled``.

    Returns ``None`` when the value is not a parseable ISO date.
    """
    parsed = parse_iso_date(value)
    if parsed is None:
        return None
    return "held" if parsed.date() <= when else "scheduled"


def date_from_filename(path: str | Path) -> str | None:
    """Return the first ``YYYY-MM-DD`` found in a note's filename, or ``None``."""
    match = _FILENAME_DATE.search(Path(path).stem)
    if match is None:
        return None
    candidate = match.group(0)
    return candidate if parse_iso_date(candidate) is not None else None


@dataclass(frozen=True)
class NormalizationIntent:
    """The field edits one note needs to reach the reconciled schema.

    An empty intent (no edits and no ``skipped``) means the note already matches. A
    non-empty ``skipped`` means the note cannot be mapped deterministically and must be
    left untouched and reported.
    """

    set_fields: dict[str, str | None] = field(default_factory=dict)
    rename_keys: dict[str, str] = field(default_factory=dict)
    changes: tuple[str, ...] = ()
    skipped: str | None = None

    @property
    def has_changes(self) -> bool:
        """Return True when the note needs at least one field edit."""
        return bool(self.set_fields or self.rename_keys)


def _declared_type(frontmatter: dict[str, Any]) -> str:
    return str(frontmatter.get("type") or "").strip().strip("\"'").casefold()


def _action_intent(frontmatter: dict[str, Any]) -> NormalizationIntent:
    set_fields: dict[str, str | None] = {}
    changes: list[str] = []

    if _declared_type(frontmatter) == "task":
        set_fields["type"] = "action"
        changes.append("type: task -> action")

    status_value = frontmatter.get("status")
    canonical_status = canonical_action_status(status_value)
    if canonical_status is None:
        return NormalizationIntent(skipped=f"unmappable action status: {status_value!r}")
    current_status = str(status_value).strip().casefold() if status_value is not None else ""
    if canonical_status != current_status:
        set_fields["status"] = canonical_status
        changes.append(f"status: {status_value} -> {canonical_status}")

    if "priority" in frontmatter:
        mappable, canonical = canonical_priority(frontmatter.get("priority"))
        if not mappable:
            return NormalizationIntent(skipped=f"unmappable action priority: {frontmatter.get('priority')!r}")
        if canonical is None:
            set_fields["priority"] = None
            changes.append("priority: removed")
        elif canonical != str(frontmatter.get("priority")).strip().upper():
            set_fields["priority"] = canonical
            changes.append(f"priority: {frontmatter.get('priority')} -> {canonical}")

    return NormalizationIntent(set_fields, {}, tuple(changes))


def _meeting_intent(path: str, frontmatter: dict[str, Any], *, when: date) -> NormalizationIntent:
    set_fields: dict[str, str | None] = {}
    rename_keys: dict[str, str] = {}
    changes: list[str] = []

    if frontmatter.get("people") is not None and frontmatter.get("attendees") is not None:
        return NormalizationIntent(skipped="meeting carries both people and attendees")
    if frontmatter.get("people") is not None:
        rename_keys["people"] = "attendees"
        changes.append("people -> attendees")

    date_value = frontmatter.get("date")
    if date_value is None or not str(date_value).strip():
        derived = date_from_filename(path)
        if derived is not None:
            date_value = derived
            set_fields["date"] = derived
            changes.append(f"date: derived {derived}")
        else:
            date_value = UNDATED_DATE
            set_fields["date"] = UNDATED_DATE
            changes.append(f"date: undated -> {UNDATED_DATE}")
            if str(frontmatter.get("date_status") or "").strip().casefold() != DATE_STATUS_UNDATED:
                set_fields["date_status"] = DATE_STATUS_UNDATED
                changes.append("date_status: -> undated")

    status_value = frontmatter.get("status")
    current_status = str(status_value).strip().casefold() if status_value is not None else ""
    if current_status and current_status not in MEETING_STATUS_VALUES:
        return NormalizationIntent(skipped=f"unmappable meeting status: {status_value!r}")
    if not current_status:
        canonical_status = canonical_meeting_status(date_value, when=when)
        if canonical_status is None:
            return NormalizationIntent(skipped=f"meeting date is not a parseable ISO date: {date_value!r}")
        set_fields["status"] = canonical_status
        changes.append(f"status: -> {canonical_status}")

    return NormalizationIntent(set_fields, rename_keys, tuple(changes))


def _project_intent(frontmatter: dict[str, Any]) -> NormalizationIntent:
    if "status" not in frontmatter or frontmatter.get("status") is None:
        return NormalizationIntent()
    canonical = canonical_project_status(frontmatter.get("status"))
    if canonical is None:
        return NormalizationIntent(skipped=f"unmappable project status: {frontmatter.get('status')!r}")
    current = str(frontmatter.get("status")).strip().casefold()
    if canonical != current:
        return NormalizationIntent({"status": canonical}, {}, (f"status: {current} -> {canonical}",))
    return NormalizationIntent()


def _person_intent(frontmatter: dict[str, Any]) -> NormalizationIntent:
    status_value = frontmatter.get("status")
    current = str(status_value).strip().casefold() if status_value is not None else ""
    if not current:
        return NormalizationIntent({"status": "active"}, {}, ("status: -> active",))
    canonical = canonical_person_status(status_value)
    if canonical is None:
        return NormalizationIntent(skipped=f"unmappable person status: {status_value!r}")
    if canonical != current:
        return NormalizationIntent({"status": canonical}, {}, (f"status: {current} -> {canonical}",))
    return NormalizationIntent()


def normalization_intent(
    entity_type: str, path: str, frontmatter: dict[str, Any], *, when: date
) -> NormalizationIntent:
    """Return the field edits one work note needs to reach the reconciled schema.

    Pure function of the parsed frontmatter, the note path, and the migration date; it
    never reads or writes the filesystem.
    """
    if entity_type == EntityType.ACTION.value:
        return _action_intent(frontmatter)
    if entity_type == EntityType.MEETING.value:
        return _meeting_intent(path, frontmatter, when=when)
    if entity_type == EntityType.PROJECT.value:
        return _project_intent(frontmatter)
    if entity_type == EntityType.PERSON.value:
        return _person_intent(frontmatter)
    return NormalizationIntent(skipped=f"no mapping for entity type: {entity_type!r}")


def normalize_target(value: object) -> str:
    """Normalize a wikilink/name target to a lookup key."""
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def link_target(value: str) -> str:
    """Normalize a wikilink-valued frontmatter string to a lookup key."""
    text = value.strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.split("|", 1)[0].split("#", 1)[0]
    return normalize_target(text)


def link_targets(entity: EntityBase, field_name: str) -> tuple[str, ...]:
    """Return normalized targets for one relationship field of an entity."""
    value = getattr(entity, field_name, None)
    if value is None:
        return ()
    values = value if isinstance(value, tuple) else (value,)
    targets = []
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        targets.append(link_target(text))
    return tuple(targets)


def entity_from_record(record: IndexRecord) -> EntityBase | None:
    """Build a typed entity from an index record, or return ``None`` to skip it."""
    frontmatter = record.frontmatter
    if not isinstance(frontmatter, dict):
        return None
    declared = frontmatter.get("type")
    entity_type = detect_type(declared)
    if entity_type is None:
        return None

    is_legacy_task = isinstance(declared, str) and declared.strip().strip("\"'").casefold() == "task"
    status = _as_str(frontmatter.get("status")) or ""
    if is_legacy_task:
        status = LEGACY_TASK_STATUS.get(status, status)
    common: dict[str, Any] = {
        "path": record.path,
        "title": record.title,
        "status": status,
        "aliases": tuple(record.aliases),
        "tags": tuple(record.tags),
        "raw": dict(frontmatter),
    }

    if entity_type == EntityType.PROJECT.value:
        return Project(
            **common,
            owners=_tuple_field(frontmatter, "owners", "owner"),
            people=_tuple_field(frontmatter, "people"),
            priority=normalize_priority(frontmatter.get("priority")),
            health=_as_str(frontmatter.get("health")),
            effort=_as_str(frontmatter.get("effort")),
            portfolio=_as_str(frontmatter.get("portfolio")),
            systems=_tuple_field(frontmatter, "systems"),
            next_action=_as_str(frontmatter.get("next_action")),
            last_reviewed=_as_str(frontmatter.get("last_reviewed")),
            next_review=_as_str(frontmatter.get("next_review")),
            project_id=_as_str(frontmatter.get("project_id")),
            search_terms=_tuple_field(frontmatter, "search_terms"),
            repos=_tuple_field(frontmatter, "repos"),
        )
    if entity_type == EntityType.PERSON.value:
        return Person(
            **common,
            role=_as_str(frontmatter.get("role")),
            team=_as_str(frontmatter.get("team")),
            manager=_as_str(frontmatter.get("manager")),
            email=_as_str(frontmatter.get("email")),
        )
    if entity_type == EntityType.TICKET.value:
        return Ticket(
            **common,
            assignee=_as_str(frontmatter.get("assignee")),
            priority=normalize_priority(frontmatter.get("priority")),
            application=_as_str(frontmatter.get("application")),
            project=_as_str(frontmatter.get("project")),
            source_system=_as_str(frontmatter.get("source_system")),
            external_id=_as_str(frontmatter.get("external_id")),
            sync_mode=_as_str(frontmatter.get("sync_mode")),
            next_action=_as_str(frontmatter.get("next_action")),
            manager_attention=_as_bool(frontmatter.get("manager_attention")),
            last_checked=_as_str(frontmatter.get("last_checked")),
        )
    if entity_type == EntityType.MEETING.value:
        return Meeting(
            **common,
            date=_as_str(frontmatter.get("date")),
            attendees=_tuple_field(frontmatter, "attendees", "people"),
            projects=_tuple_field(frontmatter, "projects"),
            project=_as_str(frontmatter.get("project")),
            meeting_type=_as_str(frontmatter.get("meeting_type")),
            source_system=_as_str(frontmatter.get("source_system")),
            external_id=_as_str(frontmatter.get("external_id")),
            sync_mode=_as_str(frontmatter.get("sync_mode")),
        )
    if entity_type == EntityType.ACTION.value:
        return Action(
            **common,
            owners=_tuple_field(frontmatter, "owners", "owner"),
            priority=normalize_priority(frontmatter.get("priority")),
            due=_as_str(frontmatter.get("due")),
            project=_as_str(frontmatter.get("project")),
            related_ticket=_as_str(frontmatter.get("related_ticket")),
            waiting_on=_as_str(frontmatter.get("waiting_on")),
            completed=_as_str(frontmatter.get("completed")),
            next_action=_as_str(frontmatter.get("next_action")),
        )
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or None


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list | tuple):
        return tuple(text for item in value if (text := str(item).strip()))
    text = str(value).strip()
    return (text,) if text else ()


def _tuple_field(frontmatter: dict[str, Any], *keys: str) -> tuple[str, ...]:
    for key in keys:
        if frontmatter.get(key) is not None:
            return _as_tuple(frontmatter.get(key))
    return ()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1"}
    return bool(value)
