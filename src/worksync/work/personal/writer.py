"""Gateway-backed personal writes: create, quick capture, update, and complete.

Every mutation is one ``trusted`` :func:`worksync.safety.gateway.commit`
transaction. Create refuses an existing target; update is SHA-preconditioned and
backed up; nothing in this module deletes a note. The write seam is reachable only
through :mod:`worksync.gui.actions`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from worksync.core.names import safe_name
from worksync.core.paths import resolve_stored_path
from worksync.inventory.parse import IndexRecord, parse_note, set_frontmatter_values
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.personal.models import (
    AREAS_DIR,
    PERSONAL_ROOT,
    PRIORITY_VALUES,
    PROJECTS_DIR,
    TASK_STATUS_VALUES,
    TASKS_DIR,
)
from worksync.work.personal.repository import PersonalIndex
from worksync.work.personal.schema import detect_personal_type, is_personal_path
from worksync.work.schema import person_id_slug

TASK_FIELDS = frozenset(
    {
        "title",
        "status",
        "area",
        "project",
        "priority",
        "due",
        "scheduled_date",
        "start_time",
        "duration_minutes",
    }
)
_PLAIN_KEYS = frozenset(
    {
        "type",
        "area_id",
        "project_id",
        "task_id",
        "status",
        "priority",
        "due",
        "scheduled_date",
        "start_time",
        "duration_minutes",
        "created",
        "updated",
        "completed",
        "revision",
    }
)
_PLAIN_RE = re.compile(r"^[A-Za-z0-9_.:+\-]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_STATUS_ALIASES = {"complete": "done"}


class PersonalWriteError(ValueError):
    """Raised when a personal write cannot be planned or applied."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class PersonalWriteResult:
    """The visible outcome of one personal write."""

    path: str
    committed: bool
    sha: str | None
    journal: Path | None
    changes: tuple[dict, ...]
    planned: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


def create_area(
    vault: str | Path,
    runtime: str | Path,
    *,
    name: str,
    description: str | None = None,
    reason: str,
    reviewer: str,
    now: datetime | None = None,
    dry_run: bool = False,
    confirmed: bool = False,
) -> PersonalWriteResult:
    """Create one area note under ``11. Personal/Areas``."""
    _require_reviewer_reason(reviewer, reason)
    title = _normalize_text(name)
    area_id = _identifier(title, "invalid_name", "An area name is required.")
    index = PersonalIndex.from_vault(vault)
    if any(area.area_id.casefold() == area_id for area in index.areas):
        raise PersonalWriteError("duplicate_id", f"An area with id '{area_id}' already exists.")
    if any(area.title.casefold() == title.casefold() for area in index.areas):
        raise PersonalWriteError("duplicate_id", f"An area named '{title}' already exists.")
    timestamp = _timestamp(now)
    fields: dict[str, object | None] = {
        "type": "area",
        "area_id": area_id,
        "status": "active",
        "description": _normalize_optional(description),
        "created": timestamp,
        "updated": timestamp,
        "revision": 1,
    }
    relative = _personal_path(AREAS_DIR, title)
    content = _render(fields, title)
    return _commit_create(
        vault,
        runtime,
        relative,
        content,
        verb="create_personal_area",
        reason=reason,
        reviewer=reviewer,
        dry_run=dry_run,
        confirmed=confirmed,
        fields={"area_id": area_id, "title": title},
    )


def create_project(
    vault: str | Path,
    runtime: str | Path,
    *,
    name: str,
    area: str | None = None,
    priority: str | None = None,
    due: str | None = None,
    reason: str,
    reviewer: str,
    now: datetime | None = None,
    dry_run: bool = False,
    confirmed: bool = False,
) -> PersonalWriteResult:
    """Create one personal project, optionally under an existing area."""
    _require_reviewer_reason(reviewer, reason)
    title = _normalize_text(name)
    project_id = _identifier(title, "invalid_name", "A project name is required.")
    index = PersonalIndex.from_vault(vault)
    if any(project.project_id.casefold() == project_id for project in index.projects):
        raise PersonalWriteError("duplicate_id", f"A project with id '{project_id}' already exists.")
    if any(project.title.casefold() == title.casefold() for project in index.projects):
        raise PersonalWriteError("duplicate_id", f"A project named '{title}' already exists.")
    area_name = _require_area(index, area)
    timestamp = _timestamp(now)
    fields: dict[str, object | None] = {
        "type": "personal-project",
        "project_id": project_id,
        "title": title,
        "status": "active",
        "area": _wikilink(area_name),
        "priority": _priority_value(priority),
        "due": _date_value(due, "due", "invalid_due"),
        "created": timestamp,
        "updated": timestamp,
        "revision": 1,
    }
    relative = _personal_path(PROJECTS_DIR, title)
    content = _render(fields, title)
    return _commit_create(
        vault,
        runtime,
        relative,
        content,
        verb="create_personal_project",
        reason=reason,
        reviewer=reviewer,
        dry_run=dry_run,
        confirmed=confirmed,
        fields={"project_id": project_id, "title": title},
    )


def capture_task(
    vault: str | Path,
    runtime: str | Path,
    *,
    text: str,
    area: str | None = None,
    project: str | None = None,
    scheduled_date: str | None = None,
    start_time: str | None = None,
    duration_minutes: int | str | None = None,
    priority: str | None = None,
    reason: str,
    reviewer: str,
    now: datetime | None = None,
    dry_run: bool = False,
    confirmed: bool = False,
) -> PersonalWriteResult:
    """Quick-capture one open task under ``11. Personal/Tasks``."""
    _require_reviewer_reason(reviewer, reason)
    title = _normalize_text(text)
    task_id = _identifier(title, "invalid_text", "Captured text must not be empty.")
    index = PersonalIndex.from_vault(vault)
    if any(task.task_id.casefold() == task_id for task in index.tasks):
        raise PersonalWriteError("duplicate_id", f"A task with id '{task_id}' already exists.")
    if any(task.title.casefold() == title.casefold() for task in index.tasks):
        raise PersonalWriteError("duplicate_id", f"A task named '{title}' already exists.")
    area_name = _require_area(index, area)
    project_name = _require_project(index, project)
    timestamp = _timestamp(now)
    fields: dict[str, object | None] = {
        "type": "personal-task",
        "task_id": task_id,
        "title": title,
        "status": "open",
        "area": _wikilink(area_name),
        "project": _wikilink(project_name),
        "priority": _priority_value(priority),
        "due": None,
        "scheduled_date": _date_value(scheduled_date, "scheduled_date", "invalid_date"),
        "start_time": _time_value(start_time, "invalid_time"),
        "duration_minutes": _duration_value(duration_minutes, "invalid_duration"),
        "completed": None,
        "created": timestamp,
        "updated": timestamp,
        "revision": 1,
    }
    relative = _personal_path(TASKS_DIR, title)
    content = _render(fields, title)
    return _commit_create(
        vault,
        runtime,
        relative,
        content,
        verb="capture_personal_task",
        reason=reason,
        reviewer=reviewer,
        dry_run=dry_run,
        confirmed=confirmed,
        fields={"task_id": task_id, "title": title},
    )


def update_task(
    vault: str | Path,
    runtime: str | Path,
    path: str,
    *,
    fields: dict[str, Any],
    reason: str,
    reviewer: str,
    expected: str | None = None,
    today: date | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    confirmed: bool = False,
) -> PersonalWriteResult:
    """Apply an allowlisted edit to one personal task."""
    vault_root, relative, record = _resolve_task(vault, path)
    _require_reviewer_reason(reviewer, reason)
    return _apply_task_fields(
        vault_root,
        runtime,
        relative,
        record,
        fields=fields,
        reason=reason,
        reviewer=reviewer,
        expected=expected,
        today=today,
        now=now,
        dry_run=dry_run,
        confirmed=confirmed,
        verb="update_personal_task",
    )


def complete_task(
    vault: str | Path,
    runtime: str | Path,
    path: str,
    *,
    reason: str,
    reviewer: str,
    expected: str | None = None,
    today: date | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    confirmed: bool = False,
) -> PersonalWriteResult:
    """Mark one personal task done, recording its completion date."""
    vault_root, relative, record = _resolve_task(vault, path)
    _require_reviewer_reason(reviewer, reason)
    if _text(record.frontmatter.get("status")).casefold() == "done":
        raise PersonalWriteError("already_done", "The task is already done.", affected=(relative,))
    return _apply_task_fields(
        vault_root,
        runtime,
        relative,
        record,
        fields={"status": "done"},
        reason=reason,
        reviewer=reviewer,
        expected=expected,
        today=today,
        now=now,
        dry_run=dry_run,
        confirmed=confirmed,
        verb="complete_personal_task",
    )


def _apply_task_fields(
    vault_root: Path,
    runtime: str | Path,
    relative: str,
    record: IndexRecord,
    *,
    fields: dict[str, Any],
    reason: str,
    reviewer: str,
    expected: str | None,
    today: date | None,
    now: datetime | None,
    dry_run: bool,
    confirmed: bool,
    verb: str,
) -> PersonalWriteResult:
    if not isinstance(fields, dict) or not fields:
        raise PersonalWriteError("invalid_op", "Provide at least one field to update.", affected=(relative,))
    unknown = sorted(key for key in fields if key not in TASK_FIELDS)
    if unknown:
        raise PersonalWriteError("unmapped_field", f"Field is not editable: {', '.join(unknown)}", affected=(relative,))
    expected_sha = str(expected).strip() if expected is not None else ""
    if expected_sha and expected_sha != record.content_hash:
        raise PersonalWriteError("stale_hash", f"Target changed since it was read: {relative}", affected=(relative,))

    index = PersonalIndex.from_vault(vault_root)
    frontmatter = record.frontmatter
    values: dict[str, object | None] = {}
    previous_status = _task_status(frontmatter.get("status"), relative)
    status = previous_status
    if "title" in fields:
        title = _normalize_text(fields["title"])
        if not title:
            raise PersonalWriteError("invalid_title", "A task title is required.", affected=(relative,))
        values["title"] = title
    if "status" in fields:
        status = _task_status(fields["status"], relative)
        values["status"] = status
    if "area" in fields:
        target = _require_area(index, _optional_text(fields["area"]))
        values["area"] = _wikilink(target)
    if "project" in fields:
        target = _require_project(index, _optional_text(fields["project"]))
        values["project"] = _wikilink(target)
    if "priority" in fields:
        values["priority"] = _priority_value(fields["priority"])
    if "due" in fields:
        values["due"] = _date_value(fields["due"], "due", "invalid_due")
    if "scheduled_date" in fields:
        values["scheduled_date"] = _date_value(fields["scheduled_date"], "scheduled_date", "invalid_date")
    if "start_time" in fields:
        values["start_time"] = _time_value(fields["start_time"], "invalid_time")
    if "duration_minutes" in fields:
        values["duration_minutes"] = _duration_value(fields["duration_minutes"], "invalid_duration")

    if status == "done":
        existing_completed = _date_value(frontmatter.get("completed"), "completed", "invalid_due")
        values["completed"] = existing_completed or (today or date.today()).isoformat()
    elif "status" in fields:
        values["completed"] = None

    values["updated"] = _timestamp(now)
    values["revision"] = _revision(frontmatter) + 1
    content = set_frontmatter_values(record.content, values)
    planned = content if dry_run else None
    if dry_run:
        return PersonalWriteResult(
            path=relative,
            committed=False,
            sha=record.content_hash,
            journal=None,
            changes=(),
            planned=planned,
            fields=dict(fields),
        )
    op = FileOp("update", Path(relative), "trusted", content=content, expected=record.content_hash)
    committed = _commit(vault_root, runtime, verb, op, reason=reason, reviewer=reviewer, confirmed=confirmed)
    return PersonalWriteResult(
        path=relative,
        committed=committed.committed,
        sha=_sha(content),
        journal=committed.journal,
        changes=committed.changes,
        planned=content,
        fields=dict(fields),
    )


def _commit_create(
    vault: str | Path,
    runtime: str | Path,
    relative: str,
    content: str,
    *,
    verb: str,
    reason: str,
    reviewer: str,
    dry_run: bool,
    confirmed: bool,
    fields: dict[str, Any],
) -> PersonalWriteResult:
    if dry_run:
        return PersonalWriteResult(
            path=relative,
            committed=False,
            sha=None,
            journal=None,
            changes=(),
            planned=content,
            fields=fields,
        )
    op = FileOp("create", Path(relative), "trusted", content=content)
    committed = _commit(vault, runtime, verb, op, reason=reason, reviewer=reviewer, confirmed=confirmed)
    return PersonalWriteResult(
        path=relative,
        committed=committed.committed,
        sha=_sha(content),
        journal=committed.journal,
        changes=committed.changes,
        planned=content,
        fields=fields,
    )


def _commit(
    vault: str | Path,
    runtime: str | Path,
    verb: str,
    op: FileOp,
    *,
    reason: str,
    reviewer: str,
    confirmed: bool,
) -> CommitResult:
    vault_root = Path(vault).expanduser().resolve()
    changeset = ChangeSet(verb, (op,), reviewer=reviewer, reason=reason)
    return commit(changeset, write_zones(vault_root, runtime), confirmed=confirmed)


def _resolve_task(vault: str | Path, path: str) -> tuple[Path, str, IndexRecord]:
    vault_root = Path(vault).expanduser().resolve()
    if not str(path).strip():
        raise PersonalWriteError("invalid_target", "A target path is required.")
    try:
        target = resolve_stored_path(vault_root, path)
    except FileNotFoundError as exc:
        raise PersonalWriteError("missing_target", str(exc), affected=(str(path),)) from exc
    relative = target.relative_to(vault_root).as_posix()
    if target.suffix.casefold() != ".md":
        raise PersonalWriteError("invalid_target", f"Target is not a markdown note: {path}", affected=(relative,))
    record = parse_note(target, vault_root)
    if detect_personal_type(record.frontmatter.get("type")) != "personal-task" or not is_personal_path(relative):
        raise PersonalWriteError(
            "not_personal_task", f"Target is not a personal task note: {relative}", affected=(relative,)
        )
    return vault_root, relative, record


def _require_reviewer_reason(reviewer: str, reason: str) -> None:
    if not str(reviewer or "").strip():
        raise PersonalWriteError("missing_reviewer", "A canonical write requires a named reviewer.")
    if not str(reason or "").strip():
        raise PersonalWriteError("missing_reason", "A canonical write requires a human-readable reason.")


def _require_area(index: PersonalIndex, value: str | None) -> str | None:
    name = _optional_text(value)
    if name is None:
        return None
    area = index.get_area(name)
    if area is None:
        raise PersonalWriteError("unknown_area", f"No personal area matches: {name}")
    return area.title


def _require_project(index: PersonalIndex, value: str | None) -> str | None:
    name = _optional_text(value)
    if name is None:
        return None
    project = index.get_project(name)
    if project is None:
        raise PersonalWriteError("unknown_project", f"No personal project matches: {name}")
    return project.title


def _personal_path(directory: str, title: str) -> str:
    name = safe_name(title)
    if not name:
        raise PersonalWriteError("invalid_name", "A note name is required.")
    return f"{PERSONAL_ROOT}/{directory}/{name}.md"


def _identifier(title: str, code: str, message: str) -> str:
    if not title:
        raise PersonalWriteError(code, message)
    identifier = person_id_slug(title)[:128].rstrip("-")
    if not identifier:
        raise PersonalWriteError(code, message)
    return identifier


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_optional(value: object) -> str | None:
    text = _normalize_text(value)
    return text or None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _wikilink(name: str | None) -> str | None:
    return f"[[{name}]]" if name else None


def _task_status(value: object, relative: str) -> str:
    text = _text(value).casefold()
    canonical = _STATUS_ALIASES.get(text, text)
    if canonical not in TASK_STATUS_VALUES:
        raise PersonalWriteError("unmappable_status", f"Unknown personal task status: {value!r}", affected=(relative,))
    return canonical


def _priority_value(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    canonical = text.upper()
    if canonical not in PRIORITY_VALUES:
        raise PersonalWriteError("invalid_priority", f"Unknown priority: {value!r}")
    return canonical


def _date_value(value: object, field_name: str, code: str) -> str | None:
    text = _text(value)
    if not text:
        return None
    if not _DATE_RE.fullmatch(text):
        raise PersonalWriteError(code, f"{field_name} is not an ISO date: {value!r}")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise PersonalWriteError(code, f"{field_name} is not an ISO date: {value!r}") from exc
    return text


def _time_value(value: object, code: str) -> str | None:
    text = _text(value)
    if not text:
        return None
    if not _TIME_RE.fullmatch(text):
        raise PersonalWriteError(code, f"Start time is not HH:MM: {value!r}")
    return text


def _duration_value(value: object, code: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise PersonalWriteError(code, f"Duration is not a positive integer: {value!r}")
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise PersonalWriteError(code, f"Duration is not a positive integer: {value!r}") from exc
    if minutes <= 0:
        raise PersonalWriteError(code, f"Duration is not a positive integer: {value!r}")
    return minutes


def _revision(frontmatter: dict[str, Any]) -> int:
    try:
        return int(frontmatter.get("revision"))
    except (TypeError, ValueError):
        return 0


def _timestamp(now: datetime | None) -> str:
    when = now or datetime.now(UTC)
    return when.isoformat(timespec="seconds")


def _sha(content: str) -> str:
    from hashlib import sha256

    return sha256(content.encode("utf-8")).hexdigest()


def _render(fields: dict[str, object | None], title: str) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        lines.append(f"{key}: {_scalar(key, value)}")
    lines += ["---", f"# {title}", ""]
    return "\n".join(lines)


def _scalar(key: str, value: object) -> str:
    text = str(value)
    if key in _PLAIN_KEYS and _PLAIN_RE.fullmatch(text):
        return text
    return str(yaml.safe_dump(text, default_style='"', allow_unicode=True).strip())
