"""The personal note domain: areas, personal projects, and personal tasks.

These notes are deliberately separate from work ``project``/``action`` entities.
They live under ``11. Personal/`` and are never selected by the work schema, so a
personal view cannot leak work data and a work view cannot see personal notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

PERSONAL_ROOT = "11. Personal"
AREAS_DIR = "Areas"
PROJECTS_DIR = "Projects"
TASKS_DIR = "Tasks"

AREA_STATUS_VALUES = frozenset({"active", "archived"})
PROJECT_STATUS_VALUES = frozenset({"active", "paused", "done", "archived"})
TASK_STATUS_VALUES = frozenset({"open", "done", "cancelled"})
PRIORITY_VALUES = ("P1", "P2", "P3", "P4")
PRIORITY_LABELS = {"P1": "Urgent", "P2": "High", "P3": "Normal", "P4": "Low"}


class PersonalType(StrEnum):
    """The three personal note types selected by the ``type`` frontmatter value."""

    AREA = "area"
    PROJECT = "personal-project"
    TASK = "personal-task"


PERSONAL_TYPE_VALUES = tuple(member.value for member in PersonalType)


@dataclass(frozen=True)
class PersonalArea:
    """One personal area, e.g. Career or Learning."""

    path: str
    title: str
    status: str
    area_id: str
    description: str | None = None
    created: str | None = None
    updated: str | None = None
    revision: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    type = PersonalType.AREA.value


@dataclass(frozen=True)
class PersonalProject:
    """One personal project, optionally nested under an area."""

    path: str
    title: str
    status: str
    project_id: str
    area: str | None = None
    priority: str | None = None
    due: str | None = None
    created: str | None = None
    updated: str | None = None
    revision: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    type = PersonalType.PROJECT.value


@dataclass(frozen=True)
class PersonalTask:
    """One personal task, optionally nested under an area and/or project."""

    path: str
    title: str
    status: str
    task_id: str
    area: str | None = None
    project: str | None = None
    priority: str | None = None
    due: str | None = None
    scheduled_date: str | None = None
    start_time: str | None = None
    duration_minutes: int | None = None
    completed: str | None = None
    created: str | None = None
    updated: str | None = None
    revision: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    type = PersonalType.TASK.value


PersonalEntity = PersonalArea | PersonalProject | PersonalTask


def area_to_payload(area: PersonalArea) -> dict:
    """Serialize an area to the public personal contract."""
    return {
        "area_id": area.area_id,
        "title": area.title,
        "status": area.status,
        "description": area.description,
        "path": area.path,
        "revision": area.revision,
    }


def project_to_payload(project: PersonalProject) -> dict:
    """Serialize a personal project to the public personal contract."""
    return {
        "project_id": project.project_id,
        "title": project.title,
        "status": project.status,
        "area": project.area,
        "priority": project.priority,
        "due": project.due,
        "path": project.path,
        "revision": project.revision,
    }


def task_to_payload(task: PersonalTask) -> dict:
    """Serialize a task to the public personal contract."""
    return {
        "task_id": task.task_id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "area": task.area,
        "project": task.project,
        "scheduled_date": task.scheduled_date,
        "start_time": task.start_time,
        "duration_minutes": task.duration_minutes,
        "due": task.due,
        "completed": task.completed,
        "path": task.path,
        "revision": task.revision,
    }
