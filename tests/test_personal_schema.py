"""Personal core: personal note types, parsing, and validation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.inventory.parse import parse_note
from worksync.work.personal.schema import (
    detect_personal_type,
    is_personal_path,
    parse_personal_record,
)

AREA = "---\ntype: area\narea_id: career\nstatus: active\ndescription: Work life\nrevision: 2\n---\n# Career\n"
PROJECT = (
    "---\ntype: personal-project\nproject_id: job-applications\ntitle: Job applications\n"
    'status: active\narea: "[[Career]]"\npriority: P2\nrevision: 1\n---\n# Job applications\n'
)
TASK = (
    "---\ntype: personal-task\ntask_id: polish-cv\ntitle: Polish CV\nstatus: open\n"
    'area: "[[Career]]"\nproject: "[[Job applications]]"\npriority: P1\n'
    "due: 2026-11-07\nscheduled_date: 2026-11-05\nstart_time: 09:30\n"
    "duration_minutes: 45\nrevision: 4\n---\n# Polish CV\n"
)


def _record(vault: Path, write_note: Callable[..., Path], relative: str, text: str):
    return parse_note(write_note(vault, relative, text), vault)


def test_detect_personal_type_selects_only_personal_types() -> None:
    assert detect_personal_type("area") == "area"
    assert detect_personal_type("personal-project") == "personal-project"
    assert detect_personal_type('"personal-task"') == "personal-task"
    assert detect_personal_type("Personal-Task") == "personal-task"
    assert detect_personal_type("action") is None
    assert detect_personal_type("project") is None
    assert detect_personal_type(None) is None


def test_personal_path_is_under_the_personal_root_only() -> None:
    assert is_personal_path("11. Personal/Tasks/Polish CV.md")
    assert is_personal_path("11. Personal/Areas/Career.md")
    assert not is_personal_path("11. Personal Secret/Tasks/Polish CV.md")
    assert not is_personal_path("9. Project/Polish CV.md")
    assert not is_personal_path("Polish CV.md")


def test_area_parses_its_fields(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(vault, write_note, "11. Personal/Areas/Career.md", AREA)
    entity, issues = parse_personal_record(record)
    assert issues == ()
    assert entity is not None
    assert entity.type == "area"
    assert entity.area_id == "career"
    assert entity.title == "Career"
    assert entity.status == "active"
    assert entity.description == "Work life"
    assert entity.revision == 2
    assert entity.path == "11. Personal/Areas/Career.md"


def test_personal_project_parses_links_and_priority(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(vault, write_note, "11. Personal/Projects/Job applications.md", PROJECT)
    entity, issues = parse_personal_record(record)
    assert issues == ()
    assert entity is not None
    assert entity.type == "personal-project"
    assert entity.project_id == "job-applications"
    assert entity.title == "Job applications"
    assert entity.area == "Career"
    assert entity.priority == "P2"
    assert entity.due is None


def test_personal_task_parses_native_fields(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(vault, write_note, "11. Personal/Tasks/Polish CV.md", TASK)
    entity, issues = parse_personal_record(record)
    assert issues == ()
    assert entity is not None
    assert entity.type == "personal-task"
    assert entity.task_id == "polish-cv"
    assert entity.scheduled_date == "2026-11-05"
    assert entity.start_time == "09:30"
    assert entity.duration_minutes == 45
    assert entity.due == "2026-11-07"
    assert entity.area == "Career"
    assert entity.project == "Job applications"
    assert entity.priority == "P1"
    assert entity.completed is None


def test_done_task_requires_a_completed_date(vault: Path, write_note: Callable[..., Path]) -> None:
    missing = TASK.replace("status: open", "status: done")
    record = _record(vault, write_note, "11. Personal/Tasks/Polish CV.md", missing)
    entity, issues = parse_personal_record(record)
    assert entity is None
    assert any(issue.rule == "completed" for issue in issues)

    valid = TASK.replace("status: open", "status: done").replace("revision: 4", "completed: 2026-11-05\nrevision: 4")
    record = _record(vault, write_note, "11. Personal/Tasks/Polish CV.md", valid)
    entity, issues = parse_personal_record(record)
    assert issues == ()
    assert entity is not None
    assert entity.status == "done"
    assert entity.completed == "2026-11-05"


def test_malformed_task_fields_are_reported_and_excluded(vault: Path, write_note: Callable[..., Path]) -> None:
    cases = {
        "due": ("due: 2026-11-07", "due: 07/11/2026", "date"),
        "scheduled_date": ("scheduled_date: 2026-11-05", "scheduled_date: tomorrow", "date"),
        "start_time": ("start_time: 09:30", "start_time: 25:90", "time"),
        "duration_minutes": ("duration_minutes: 45", "duration_minutes: 0", "duration"),
        "priority": ("priority: P1", "priority: P9", "priority"),
    }
    for name, (good, bad, rule) in cases.items():
        text = TASK.replace(good, bad)
        record = _record(vault, write_note, f"11. Personal/Tasks/Bad {name}.md", text)
        entity, issues = parse_personal_record(record)
        assert entity is None, name
        assert any(issue.rule == rule for issue in issues), (name, issues)


def test_missing_required_fields_are_errors(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(
        vault,
        write_note,
        "11. Personal/Tasks/No id.md",
        "---\ntype: personal-task\ntitle: No id\nstatus: open\n---\n# No id\n",
    )
    entity, issues = parse_personal_record(record)
    assert entity is None
    assert any(issue.rule == "required" for issue in issues)

    record = _record(
        vault,
        write_note,
        "11. Personal/Tasks/Bad id.md",
        "---\ntype: personal-task\ntask_id: Not Kebab\nstatus: open\n---\n# Bad id\n",
    )
    entity, issues = parse_personal_record(record)
    assert entity is None
    assert any(issue.rule == "personal_id" for issue in issues)

    record = _record(
        vault,
        write_note,
        "11. Personal/Tasks/No status.md",
        "---\ntype: personal-task\ntask_id: no-status\ntitle: No status\n---\n# No status\n",
    )
    entity, issues = parse_personal_record(record)
    assert entity is None
    assert any(issue.rule == "required" for issue in issues)


def test_work_records_are_excluded_from_the_personal_layer(vault: Path, write_note: Callable[..., Path]) -> None:
    work_inside = "---\ntype: action\ntask_id: disguise\nstatus: open\n---\n# Disguise\n"
    record = _record(vault, write_note, "11. Personal/Tasks/Disguise.md", work_inside)
    entity, issues = parse_personal_record(record)
    assert entity is None
    assert issues == ()

    personal_outside = TASK
    record = _record(vault, write_note, "9. Project/Polish CV.md", personal_outside)
    entity, issues = parse_personal_record(record)
    assert entity is None
    assert issues == ()


def test_non_personal_types_are_skipped_silently(vault: Path, write_note: Callable[..., Path]) -> None:
    record = _record(
        vault,
        write_note,
        "11. Personal/Tasks/Reference.md",
        "---\ntype: reference\n---\n# Reference\n",
    )
    entity, issues = parse_personal_record(record)
    assert entity is None
    assert issues == ()
