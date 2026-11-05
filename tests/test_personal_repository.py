"""Personal core: the personal-only index, grouping, and the Today rollup."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from worksync.work.personal.repository import PersonalIndex
from worksync.work.personal.today import build_today
from worksync.work.repository import WorkIndex

TODAY = date(2026, 11, 5)
GENERATED = "2026-11-05T12:00:00+00:00"

AREA_CAREER = "---\ntype: area\narea_id: career\nstatus: active\ndescription: Work life\nrevision: 1\n---\n# Career\n"
AREA_LEARNING = "---\ntype: area\narea_id: learning\nstatus: active\nrevision: 1\n---\n# Learning\n"
PROJECT_JOB = (
    "---\ntype: personal-project\nproject_id: job-applications\ntitle: Job applications\n"
    'status: active\narea: "[[Career]]"\npriority: P2\nrevision: 1\n---\n# Job applications\n'
)
PROJECT_SHI = (
    "---\ntype: personal-project\nproject_id: shibari\ntitle: Shibari\n"
    'status: active\narea: "[[Learning]]"\nrevision: 1\n---\n# Shibari\n'
)


def _task(
    task_id: str,
    title: str,
    *,
    status: str = "open",
    priority: str | None = None,
    due: str | None = None,
    scheduled: str | None = None,
    start: str | None = None,
    area: str | None = None,
    project: str | None = None,
    completed: str | None = None,
) -> str:
    lines = ["---", "type: personal-task", f"task_id: {task_id}", f'title: "{title}"', f"status: {status}"]
    if area:
        lines.append(f'area: "[[{area}]]"')
    if project:
        lines.append(f'project: "[[{project}]]"')
    if priority:
        lines.append(f"priority: {priority}")
    if due:
        lines.append(f"due: {due}")
    if scheduled:
        lines.append(f"scheduled_date: {scheduled}")
    if start:
        lines.append(f"start_time: {start}")
    if completed:
        lines.append(f"completed: {completed}")
    lines += ["revision: 1", "---", f"# {title}", ""]
    return "\n".join(lines)


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "11. Personal/Areas/Career.md", AREA_CAREER)
    write_note(vault, "11. Personal/Areas/Learning.md", AREA_LEARNING)
    write_note(vault, "11. Personal/Projects/Job applications.md", PROJECT_JOB)
    write_note(vault, "11. Personal/Projects/Shibari.md", PROJECT_SHI)
    write_note(
        vault,
        "11. Personal/Tasks/Polish CV.md",
        _task(
            "polish-cv",
            "Polish CV",
            priority="P1",
            due="2026-11-07",
            scheduled="2026-11-05",
            start="09:30",
            area="Career",
            project="Job applications",
        ),
    )
    write_note(
        vault,
        "11. Personal/Tasks/Call recruiter.md",
        _task("call-recruiter", "Call recruiter", priority="P2", scheduled="2026-11-05", area="Career"),
    )
    write_note(
        vault,
        "11. Personal/Tasks/Apply to X.md",
        _task("apply-to-x", "Apply to X", priority="P2", due="2026-11-01", area="Career"),
    )
    write_note(
        vault,
        "11. Personal/Tasks/Soon.md",
        _task("soon", "Soon", priority="P3", due="2026-11-06", project="Job applications"),
    )
    write_note(
        vault,
        "11. Personal/Tasks/No due.md",
        _task("no-due", "No due", priority="P4"),
    )
    write_note(
        vault,
        "11. Personal/Tasks/Later.md",
        _task("later", "Later", scheduled="2026-11-08"),
    )
    write_note(
        vault,
        "11. Personal/Tasks/Done task.md",
        _task("done-task", "Done task", status="done", scheduled="2026-11-05", completed="2026-11-04"),
    )
    write_note(
        vault,
        "11. Personal/Tasks/Overdue but scheduled.md",
        _task(
            "overdue-scheduled",
            "Overdue but scheduled",
            priority="P3",
            due="2026-11-01",
            scheduled="2026-11-05",
        ),
    )


def test_index_reads_only_personal_notes(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    write_note(
        vault,
        "9. Project/Work Project.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n---\n# Work Project\n',
    )
    write_note(vault, "Actions/A1.md", "---\ntype: action\nstatus: open\n---\n# A1\n")
    write_note(
        vault,
        "11. Personal/Tasks/Disguised work.md",
        "---\ntype: action\ntask_id: disguised\nstatus: open\n---\n# Disguised work\n",
    )
    index = PersonalIndex.from_vault(vault)
    assert {task.task_id for task in index.tasks} == {
        "polish-cv",
        "call-recruiter",
        "apply-to-x",
        "soon",
        "no-due",
        "later",
        "done-task",
        "overdue-scheduled",
    }
    assert "disguised" not in {task.task_id for task in index.tasks}


def test_areas_and_projects_are_in_deterministic_order(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = PersonalIndex.from_vault(vault)
    assert [area.title for area in index.areas] == ["Career", "Learning"]
    assert [project.title for project in index.projects] == ["Job applications", "Shibari"]


def test_area_project_task_grouping(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = PersonalIndex.from_vault(vault)
    career = index.get_area("career")
    assert career is not None and career.title == "Career"
    assert [project.title for project in index.projects_for_area("Career")] == ["Job applications"]
    assert [task.task_id for task in index.tasks_for_area("career")] == [
        "apply-to-x",
        "call-recruiter",
        "polish-cv",
    ]
    assert [task.task_id for task in index.tasks_for_project("job-applications")] == [
        "polish-cv",
        "soon",
    ]


def test_malformed_personal_note_is_reported_and_excluded(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    write_note(
        vault,
        "11. Personal/Tasks/Broken.md",
        "---\ntype: personal-task\ntask_id: broken\ntitle: Broken\nstatus: open\ndue: soon\n---\n# Broken\n",
    )
    index = PersonalIndex.from_vault(vault)
    assert "broken" not in {task.task_id for task in index.tasks}
    assert any(issue.path == "11. Personal/Tasks/Broken.md" for issue in index.issues)


def test_today_classifies_and_orders_every_section(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = PersonalIndex.from_vault(vault)
    payload = build_today(index, TODAY, generated_at=GENERATED)

    assert payload["contract_version"] == 1
    assert payload["generated_at"] == GENERATED
    assert payload["today"] == "2026-11-05"
    assert [section["key"] for section in payload["sections"]] == ["scheduled", "overdue", "unscheduled"]
    assert [section["title"] for section in payload["sections"]] == ["Scheduled today", "Overdue", "Unscheduled"]

    scheduled, overdue, unscheduled = (section["items"] for section in payload["sections"])
    assert [item["task_id"] for item in scheduled] == ["polish-cv", "call-recruiter", "overdue-scheduled"]
    assert [item["task_id"] for item in overdue] == ["apply-to-x"]
    assert [item["task_id"] for item in unscheduled] == ["soon", "no-due"]

    assert [area["title"] for area in payload["areas"]] == ["Career", "Learning"]
    assert [project["title"] for project in payload["projects"]] == ["Job applications", "Shibari"]


def test_today_task_payload_carries_the_contract_fields(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = PersonalIndex.from_vault(vault)
    payload = build_today(index, TODAY, generated_at=GENERATED)
    polish = payload["sections"][0]["items"][0]
    assert polish == {
        "task_id": "polish-cv",
        "title": "Polish CV",
        "status": "open",
        "priority": "P1",
        "area": "Career",
        "project": "Job applications",
        "scheduled_date": "2026-11-05",
        "start_time": "09:30",
        "duration_minutes": None,
        "due": "2026-11-07",
        "completed": None,
        "path": "11. Personal/Tasks/Polish CV.md",
        "revision": 1,
    }
    career = payload["areas"][0]
    assert career == {
        "area_id": "career",
        "title": "Career",
        "status": "active",
        "description": "Work life",
        "path": "11. Personal/Areas/Career.md",
        "revision": 1,
    }
    assert payload["projects"][0] == {
        "project_id": "job-applications",
        "title": "Job applications",
        "status": "active",
        "area": "Career",
        "priority": "P2",
        "due": None,
        "path": "11. Personal/Projects/Job applications.md",
        "revision": 1,
    }


def test_work_index_never_sees_personal_notes(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = WorkIndex.from_vault(vault)
    assert index.entities == ()
    assert index.counts()["project"] == 0
    assert index.counts()["action"] == 0


def test_today_is_stable_for_the_same_vault_and_day(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = PersonalIndex.from_vault(vault)
    assert build_today(index, TODAY, generated_at=GENERATED) == build_today(index, TODAY, generated_at=GENERATED)
