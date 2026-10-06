"""Schema detection and entity construction from inventory records.

Turns an :class:`~worksync.inventory.parse.IndexRecord` into a typed work entity.
Notes whose ``type`` is absent or unknown are not work entities and are skipped
without error. The retired legacy ``task`` type reads as ``action``.
"""

from __future__ import annotations

import re
from typing import Any

from worksync.inventory.parse import IndexRecord
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


def detect_type(value: object) -> str | None:
    """Return the work type named by a ``type`` value, or ``None``.

    ``task`` maps to ``action``; case and quotes are normalized.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().strip("\"'").casefold()
    text = LEGACY_TYPE_ALIASES.get(text, text)
    return text if text in OPERATOR_TYPE_VALUES else None


def normalize_priority(value: object) -> str | None:
    """Map a legacy or canonical priority to ``P1``-``P4`` (or ``None``)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"medium", "none", "null"}:
        return None
    upper = text.upper()
    if upper in {"P1", "P2", "P3", "P4"}:
        return upper
    if text.isdigit():
        number = int(text)
        if 1 <= number <= 3:
            return f"P{number}"
        if 4 <= number <= 7:
            return "P4"
    return text


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
