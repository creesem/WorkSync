"""The personal Today rollup: scheduled today, overdue, and unscheduled.

Classification is mutually exclusive so a row never appears twice:
scheduled-today tasks include every open task planned for the day (even one whose
hard ``due`` has passed); overdue covers open tasks with a past ``due`` that are
not planned for today; unscheduled covers open tasks with no planned day that are
not overdue. Future-planned tasks are intentionally absent from Today.

Ordering is deterministic: scheduled rows by local start time (untimed last),
then priority; overdue rows by due date; unscheduled rows by priority with an
undated row last. No wall clock is read; ``generated_at`` is injectable.
"""

from __future__ import annotations

from datetime import date

from worksync.work.personal.models import (
    PersonalTask,
    area_to_payload,
    project_to_payload,
    task_to_payload,
)
from worksync.work.personal.repository import PersonalIndex, priority_rank

CONTRACT_VERSION = 1
UNTIMED = "99:99"
UNDATED = "9999-12-31"


def build_today(index: PersonalIndex, today: date, *, generated_at: str) -> dict:
    """Return the Today contract payload for one personal index and day."""
    iso = today.isoformat()
    open_tasks = tuple(task for task in index.tasks if task.status == "open")
    scheduled = tuple(task for task in open_tasks if task.scheduled_date == iso)
    overdue = tuple(
        task for task in open_tasks if task.scheduled_date != iso and task.due is not None and task.due < iso
    )
    unscheduled = tuple(
        task for task in open_tasks if task.scheduled_date is None and not (task.due is not None and task.due < iso)
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "today": iso,
        "sections": [
            {
                "key": "scheduled",
                "title": "Scheduled today",
                "items": [task_to_payload(task) for task in sorted(scheduled, key=_scheduled_sort)],
            },
            {
                "key": "overdue",
                "title": "Overdue",
                "items": [task_to_payload(task) for task in sorted(overdue, key=_overdue_sort)],
            },
            {
                "key": "unscheduled",
                "title": "Unscheduled",
                "items": [task_to_payload(task) for task in sorted(unscheduled, key=_unscheduled_sort)],
            },
        ],
        "areas": [area_to_payload(area) for area in index.areas],
        "projects": [project_to_payload(project) for project in index.projects],
    }


def _scheduled_sort(task: PersonalTask) -> tuple[str, int, str, str]:
    return (task.start_time or UNTIMED, priority_rank(task.priority), task.title.casefold(), task.path)


def _overdue_sort(task: PersonalTask) -> tuple[str, int, str, str]:
    return (task.due or UNDATED, priority_rank(task.priority), task.title.casefold(), task.path)


def _unscheduled_sort(task: PersonalTask) -> tuple[int, str, str, str]:
    return (priority_rank(task.priority), task.due or UNDATED, task.title.casefold(), task.path)
