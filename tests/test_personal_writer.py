"""Personal core: the gateway-backed personal write service."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.personal.repository import PersonalIndex
from worksync.work.personal.writer import (
    PersonalWriteError,
    capture_task,
    complete_task,
    create_area,
    create_project,
    update_task,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
TODAY = date(2026, 11, 5)
REVIEWER = "Myles"
REASON = "Personal core test"


def _index(vault: Path) -> PersonalIndex:
    return PersonalIndex.from_vault(vault)


def test_create_area_commits_through_the_gateway(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    result = create_area(
        vault,
        runtime,
        name="Career",
        description="Work life",
        reason=REASON,
        reviewer=REVIEWER,
        now=NOW,
    )
    assert result.committed is True
    assert result.path == "11. Personal/Areas/Career.md"
    text = (vault / result.path).read_text(encoding="utf-8")
    assert "type: area" in text
    assert "area_id: career" in text
    assert "status: active" in text
    assert 'description: "Work life"' in text
    assert text.endswith("# Career\n")
    assert (runtime / "journal").is_dir()
    assert result.changes and result.changes[0]["reviewer"] == REVIEWER
    assert result.changes[0]["reason"] == REASON
    area = _index(vault).get_area("career")
    assert area is not None and area.title == "Career"


def test_create_area_refuses_a_duplicate_id_and_never_overwrites(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    create_area(vault, runtime, name="Career", reason=REASON, reviewer=REVIEWER, now=NOW)
    before = (vault / "11. Personal/Areas/Career.md").read_bytes()
    with pytest.raises(PersonalWriteError) as excinfo:
        create_area(vault, runtime, name="career", reason="Again", reviewer=REVIEWER, now=NOW)
    assert excinfo.value.code == "duplicate_id"
    assert (vault / "11. Personal/Areas/Career.md").read_bytes() == before


def test_create_project_links_its_area_priority_and_due(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    create_area(vault, runtime, name="Career", reason=REASON, reviewer=REVIEWER, now=NOW)
    result = create_project(
        vault,
        runtime,
        name="Job applications",
        area="Career",
        priority="P2",
        due="2026-11-30",
        reason=REASON,
        reviewer=REVIEWER,
        now=NOW,
    )
    assert result.path == "11. Personal/Projects/Job applications.md"
    text = (vault / result.path).read_text(encoding="utf-8")
    assert "type: personal-project" in text
    assert 'area: "[[Career]]"' in text
    assert "priority: P2" in text
    assert "due: 2026-11-30" in text
    project = _index(vault).get_project("job-applications")
    assert project is not None
    assert project.area == "Career"
    assert project.due == "2026-11-30"


def test_create_project_requires_a_known_area(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    with pytest.raises(PersonalWriteError) as excinfo:
        create_project(
            vault,
            runtime,
            name="Orphan",
            area="Nope",
            reason=REASON,
            reviewer=REVIEWER,
            now=NOW,
        )
    assert excinfo.value.code == "unknown_area"
    assert not (vault / "11. Personal/Projects/Orphan.md").exists()


def test_quick_capture_writes_a_task_under_tasks(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    create_area(vault, runtime, name="Career", reason=REASON, reviewer=REVIEWER, now=NOW)
    create_project(
        vault,
        runtime,
        name="Job applications",
        area="Career",
        reason=REASON,
        reviewer=REVIEWER,
        now=NOW,
    )
    result = capture_task(
        vault,
        runtime,
        text="  Polish   CV  ",
        area="Career",
        project="Job applications",
        scheduled_date="2026-11-05",
        start_time="09:30",
        duration_minutes=45,
        priority="P1",
        reason="Capture",
        reviewer=REVIEWER,
        now=NOW,
    )
    assert result.path == "11. Personal/Tasks/Polish CV.md"
    task = _index(vault).tasks[0]
    assert task.task_id == "polish-cv"
    assert task.title == "Polish CV"
    assert task.status == "open"
    assert task.area == "Career"
    assert task.project == "Job applications"
    assert task.scheduled_date == "2026-11-05"
    assert task.start_time == "09:30"
    assert task.duration_minutes == 45
    assert task.priority == "P1"
    assert task.revision == 1


def test_quick_capture_rejects_an_unknown_project(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    with pytest.raises(PersonalWriteError) as excinfo:
        capture_task(
            vault,
            runtime,
            text="Polish CV",
            project="Nope",
            reason="Capture",
            reviewer=REVIEWER,
            now=NOW,
        )
    assert excinfo.value.code == "unknown_project"
    assert not (vault / "11. Personal/Tasks/Polish CV.md").exists()


def test_quick_capture_rejects_malformed_native_fields(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    with pytest.raises(PersonalWriteError) as excinfo:
        capture_task(
            vault,
            runtime,
            text="Polish CV",
            start_time="25:00",
            reason="Capture",
            reviewer=REVIEWER,
            now=NOW,
        )
    assert excinfo.value.code == "invalid_time"
    assert not (vault / "11. Personal/Tasks/Polish CV.md").exists()


def test_update_task_bumps_revision_and_uses_a_sha_precondition(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    created = capture_task(vault, runtime, text="Polish CV", reason="Capture", reviewer=REVIEWER, now=NOW)
    original_sha = created.sha
    original = (vault / created.path).read_bytes()
    result = update_task(
        vault,
        runtime,
        created.path,
        fields={"priority": "P1", "scheduled_date": "2026-11-05", "start_time": "09:30"},
        reason="Plan it",
        reviewer=REVIEWER,
        expected=original_sha,
        now=NOW,
    )
    assert result.committed is True
    assert result.sha != original_sha
    task = _index(vault).tasks[0]
    assert task.priority == "P1"
    assert task.scheduled_date == "2026-11-05"
    assert task.start_time == "09:30"
    assert task.revision == 2
    assert task.updated == "2026-11-05T12:00:00+00:00"
    backup_dir = next((runtime / "backups").iterdir())
    backup = next(backup_dir.iterdir())
    assert backup.read_bytes() == original


def test_update_task_rejects_a_stale_sha_and_leaves_the_note_untouched(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    created = capture_task(vault, runtime, text="Polish CV", reason="Capture", reviewer=REVIEWER, now=NOW)
    before = (vault / created.path).read_bytes()
    with pytest.raises(PersonalWriteError) as excinfo:
        update_task(
            vault,
            runtime,
            created.path,
            fields={"priority": "P1"},
            reason="Plan it",
            reviewer=REVIEWER,
            expected="deadbeef",
            now=NOW,
        )
    assert excinfo.value.code == "stale_hash"
    assert (vault / created.path).read_bytes() == before


def test_update_task_rejects_unknown_fields_and_work_targets(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    created = capture_task(vault, runtime, text="Polish CV", reason="Capture", reviewer=REVIEWER, now=NOW)
    with pytest.raises(PersonalWriteError) as excinfo:
        update_task(
            vault,
            runtime,
            created.path,
            fields={"completed": "2026-11-05"},
            reason="Nope",
            reviewer=REVIEWER,
            now=NOW,
        )
    assert excinfo.value.code == "unmapped_field"

    work = vault / "9. Project" / "Work.md"
    work.parent.mkdir(parents=True)
    work.write_text('---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n---\n# Work\n', encoding="utf-8")
    with pytest.raises(PersonalWriteError) as excinfo:
        update_task(
            vault,
            runtime,
            "9. Project/Work.md",
            fields={"title": "Hijack"},
            reason="Nope",
            reviewer=REVIEWER,
            now=NOW,
        )
    assert excinfo.value.code == "not_personal_task"


def test_complete_task_sets_done_and_a_completion_date(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    created = capture_task(vault, runtime, text="Polish CV", reason="Capture", reviewer=REVIEWER, now=NOW)
    result = complete_task(
        vault,
        runtime,
        created.path,
        reason="Finished it",
        reviewer=REVIEWER,
        expected=created.sha,
        today=TODAY,
        now=NOW,
    )
    assert result.committed is True
    task = _index(vault).tasks[0]
    assert task.status == "done"
    assert task.completed == "2026-11-05"
    assert task.revision == 2
    text = (vault / created.path).read_text(encoding="utf-8")
    assert 'status: "done"' in text or "status: done" in text
    assert 'completed: "2026-11-05"' in text or "completed: 2026-11-05" in text

    with pytest.raises(PersonalWriteError) as excinfo:
        complete_task(
            vault,
            runtime,
            created.path,
            reason="Again",
            reviewer=REVIEWER,
            now=NOW,
        )
    assert excinfo.value.code == "already_done"


def test_dry_run_plans_without_writing(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    created = create_area(
        vault,
        runtime,
        name="Career",
        reason=REASON,
        reviewer=REVIEWER,
        now=NOW,
        dry_run=True,
    )
    assert created.committed is False
    assert created.planned and "area_id: career" in created.planned
    assert not (vault / "11. Personal").exists()
    assert not (runtime / "journal").exists()


def test_missing_reviewer_or_reason_fails_closed(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    with pytest.raises(PersonalWriteError) as excinfo:
        create_area(vault, runtime, name="Career", reason="", reviewer=REVIEWER, now=NOW)
    assert excinfo.value.code == "missing_reason"

    with pytest.raises(PersonalWriteError) as excinfo:
        create_area(vault, runtime, name="Career", reason=REASON, reviewer="  ", now=NOW)
    assert excinfo.value.code == "missing_reviewer"
    assert not (vault / "11. Personal").exists()


def test_mid_transaction_failure_rolls_back_and_journals(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "var"
    created = capture_task(vault, runtime, text="Polish CV", reason="Capture", reviewer=REVIEWER, now=NOW)
    before = (vault / created.path).read_bytes()
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("Polish CV.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        update_task(
            vault,
            runtime,
            created.path,
            fields={"priority": "P1"},
            reason="Plan it",
            reviewer=REVIEWER,
            now=NOW,
        )
    assert excinfo.value.code == "rolled_back"
    assert (vault / created.path).read_bytes() == before
    records = [json.loads(journal.read_text(encoding="utf-8")) for journal in (runtime / "journal").glob("*.json")]
    rolled_back = [record for record in records if record.get("rolled_back")]
    assert rolled_back
    assert rolled_back[0]["committed"] is False
