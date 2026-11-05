"""Parse and validate personal notes into typed entities.

A personal note needs both its declared personal ``type`` and a path under
``11. Personal/``. Anything else is skipped without an issue, which is how work
records stay out of the personal layer. Malformed fields that would make a row
ambiguous (dates, time, duration, priority) exclude the note from personal views
rather than guessing.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from worksync.inventory.parse import IndexRecord
from worksync.work.personal.models import (
    AREA_STATUS_VALUES,
    PERSONAL_ROOT,
    PRIORITY_VALUES,
    PROJECT_STATUS_VALUES,
    TASK_STATUS_VALUES,
    PersonalArea,
    PersonalEntity,
    PersonalProject,
    PersonalTask,
    PersonalType,
)
from worksync.work.schema import is_entity_id
from worksync.work.validate import ValidationIssue

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_STATUS_ALIASES = {"complete": "done"}


def detect_personal_type(value: object) -> str | None:
    """Return the personal type named by a ``type`` value, or ``None``."""
    if not isinstance(value, str):
        return None
    text = value.strip().strip("\"'").casefold()
    return text if text in {member.value for member in PersonalType} else None


def is_personal_path(path: str | PurePosixPath) -> bool:
    """Return True when *path* is under the personal root (never a lookalike)."""
    parts = PurePosixPath(str(path).replace("\\", "/")).parts
    return bool(parts) and parts[0].casefold() == PERSONAL_ROOT.casefold()


def link_name(value: object) -> str | None:
    """Return the display name of a wikilink/plain reference, or ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.split("|", 1)[0].split("#", 1)[0].strip()
    return text or None


def parse_personal_record(record: IndexRecord) -> tuple[PersonalEntity | None, tuple[ValidationIssue, ...]]:
    """Parse one inventory record into a personal entity plus validation issues."""
    if not is_personal_path(record.path):
        return None, ()
    personal_type = detect_personal_type(record.frontmatter.get("type"))
    if personal_type is None:
        return None, ()
    issues: list[ValidationIssue] = []
    frontmatter = record.frontmatter
    title = _text(frontmatter.get("title")) or record.title
    status = _status(frontmatter.get("status"), issues, record.path)
    revision = _revision(frontmatter.get("revision"), issues, record.path)
    if not title:
        issues.append(_issue(record.path, "Missing required field: title", rule="required"))

    if personal_type == PersonalType.AREA.value:
        entity: PersonalEntity | None = PersonalArea(
            path=record.path,
            title=title,
            status=status,
            area_id=_required_id(frontmatter.get("area_id"), "area_id", issues, record.path),
            description=_text(frontmatter.get("description")),
            created=_text(frontmatter.get("created")),
            updated=_text(frontmatter.get("updated")),
            revision=revision,
            raw=dict(frontmatter),
        )
        _check_status(status, AREA_STATUS_VALUES, personal_type, issues, record.path)
    elif personal_type == PersonalType.PROJECT.value:
        entity = PersonalProject(
            path=record.path,
            title=title,
            status=status,
            project_id=_required_id(frontmatter.get("project_id"), "project_id", issues, record.path),
            area=_link(frontmatter.get("area"), "area", issues, record.path),
            priority=_priority(frontmatter.get("priority"), issues, record.path),
            due=_date(frontmatter.get("due"), "due", issues, record.path),
            created=_text(frontmatter.get("created")),
            updated=_text(frontmatter.get("updated")),
            revision=revision,
            raw=dict(frontmatter),
        )
        _check_status(status, PROJECT_STATUS_VALUES, personal_type, issues, record.path)
    else:
        completed = _date(frontmatter.get("completed"), "completed", issues, record.path)
        entity = PersonalTask(
            path=record.path,
            title=title,
            status=status,
            task_id=_required_id(frontmatter.get("task_id"), "task_id", issues, record.path),
            area=_link(frontmatter.get("area"), "area", issues, record.path),
            project=_link(frontmatter.get("project"), "project", issues, record.path),
            priority=_priority(frontmatter.get("priority"), issues, record.path),
            due=_date(frontmatter.get("due"), "due", issues, record.path),
            scheduled_date=_date(frontmatter.get("scheduled_date"), "scheduled_date", issues, record.path),
            start_time=_time(frontmatter.get("start_time"), issues, record.path),
            duration_minutes=_duration(frontmatter.get("duration_minutes"), issues, record.path),
            completed=completed,
            created=_text(frontmatter.get("created")),
            updated=_text(frontmatter.get("updated")),
            revision=revision,
            raw=dict(frontmatter),
        )
        _check_status(status, TASK_STATUS_VALUES, personal_type, issues, record.path)
        if status == "done" and completed is None:
            issues.append(_issue(record.path, "status 'done' requires field: completed", rule="completed"))

    return (None if issues else entity), tuple(issues)


def _issue(path: str, message: str, *, rule: str, severity: str = "error") -> ValidationIssue:
    return ValidationIssue(path=path, message=message, severity=severity, rule=rule)


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _required_id(value: Any, field: str, issues: list[ValidationIssue], path: str) -> str:
    text = _text(value)
    if not text:
        issues.append(_issue(path, f"Missing required field: {field}", rule="required"))
        return ""
    if not is_entity_id(text):
        issues.append(_issue(path, f"Invalid {field} '{text}'", rule="personal_id"))
        return text
    return text


def _status(value: Any, issues: list[ValidationIssue], path: str) -> str:
    text = _text(value)
    if not text:
        issues.append(_issue(path, "Missing required field: status", rule="required"))
        return ""
    return _STATUS_ALIASES.get(text.casefold(), text.casefold())


def _check_status(
    status: str, allowed: frozenset[str], personal_type: str, issues: list[ValidationIssue], path: str
) -> None:
    if status and status not in allowed:
        issues.append(_issue(path, f"Invalid status '{status}' for {personal_type}", rule="enum"))


def _revision(value: Any, issues: list[ValidationIssue], path: str) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        issues.append(_issue(path, f"Invalid revision '{value}'", rule="revision", severity="warning"))
        return 0


def _priority(value: Any, issues: list[ValidationIssue], path: str) -> str | None:
    text = _text(value)
    if text is None:
        return None
    canonical = text.upper()
    if canonical not in PRIORITY_VALUES:
        issues.append(_issue(path, f"Invalid priority '{text}'", rule="priority"))
        return None
    return canonical


def _date(value: Any, field: str, issues: list[ValidationIssue], path: str) -> str | None:
    text = _text(value)
    if text is None:
        return None
    if not _DATE_RE.fullmatch(text):
        issues.append(_issue(path, f"Invalid {field} date '{text}' (expected YYYY-MM-DD)", rule="date"))
        return None
    try:
        from datetime import date as _date_type

        _date_type.fromisoformat(text)
    except ValueError:
        issues.append(_issue(path, f"Invalid {field} date '{text}' (expected YYYY-MM-DD)", rule="date"))
        return None
    return text


def _time(value: Any, issues: list[ValidationIssue], path: str) -> str | None:
    text = _text(value)
    if text is None:
        return None
    if not _TIME_RE.fullmatch(text):
        issues.append(_issue(path, f"Invalid start_time '{text}' (expected HH:MM)", rule="time"))
        return None
    return text


def _duration(value: Any, issues: list[ValidationIssue], path: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        issues.append(_issue(path, f"Invalid duration_minutes '{value}'", rule="duration"))
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        issues.append(_issue(path, f"Invalid duration_minutes '{value}'", rule="duration"))
        return None
    if minutes <= 0:
        issues.append(_issue(path, f"Invalid duration_minutes '{value}' (must be > 0)", rule="duration"))
        return None
    return minutes


def _link(value: Any, field: str, issues: list[ValidationIssue], path: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        issues.append(_issue(path, f"Invalid {field} reference (expected a name)", rule="link"))
        return None
    return link_name(value)
