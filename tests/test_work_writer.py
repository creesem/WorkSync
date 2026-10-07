"""Spec 3: canonical action write service (allowlisted edits and completion)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.writer import ActionWriteError, complete_action, update_action

WHEN = date(2026, 10, 6)

ACTION = (
    "---\n"
    "type: action\n"
    "status: open\n"
    "priority: P2\n"
    "owners:\n"
    '  - "[[Myles Creese]]"\n'
    'project: "[[Project - Alpha]]"\n'
    "due: 2026-10-01\n"
    "revision: 3\n"
    "---\n"
    "# Task One\n"
    "Body line\n"
)


def _seed(vault: Path) -> Path:
    path = vault / "7. Task Notes/Active/Task One.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ACTION, encoding="utf-8")
    return path


def _backups(runtime: Path) -> list[Path]:
    return sorted((runtime / "backups").glob("backup-*/file-*"))


def test_update_changes_only_named_fields_and_writes_history(vault: Path, tmp_path: Path) -> None:
    path = _seed(vault)
    runtime = tmp_path / "var"
    result = update_action(
        vault,
        runtime,
        "7. Task Notes/Active/Task One.md",
        fields={"status": "in_progress", "due": "2026-10-09"},
        reason="Reschedule and start",
        reviewer="myles",
        today=WHEN,
    )
    assert result.committed is True
    expected = (
        "---\n"
        "type: action\n"
        "status: in_progress\n"
        "priority: P2\n"
        "owners:\n"
        '  - "[[Myles Creese]]"\n'
        'project: "[[Project - Alpha]]"\n'
        "due: 2026-10-09\n"
        "revision: 4\n"
        "updated: 2026-10-06\n"
        "updated_by: myles\n"
        "last_action: Reschedule and start\n"
        "---\n"
        "# Task One\n"
        "Body line\n"
    )
    assert path.read_text(encoding="utf-8") == expected
    assert result.changes[0]["reviewer"] == "myles"
    assert result.changes[0]["reason"] == "Reschedule and start"


def test_update_creates_a_recoverable_backup(vault: Path, tmp_path: Path) -> None:
    _seed(vault)
    runtime = tmp_path / "var"
    update_action(
        vault,
        runtime,
        "7. Task Notes/Active/Task One.md",
        fields={"status": "in_progress"},
        reason="Start it",
        reviewer="myles",
        today=WHEN,
    )
    backups = _backups(runtime)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == ACTION


def test_dry_run_writes_nothing(vault: Path, tmp_path: Path) -> None:
    path = _seed(vault)
    runtime = tmp_path / "var"
    result = update_action(
        vault,
        runtime,
        "7. Task Notes/Active/Task One.md",
        fields={"status": "in_progress"},
        reason="Start it",
        reviewer="myles",
        today=WHEN,
        dry_run=True,
    )
    assert result.committed is False
    assert path.read_text(encoding="utf-8") == ACTION
    assert not (runtime / "journal").exists()
    assert not (runtime / "backups").exists()


def test_stale_expected_hash_fails_closed(vault: Path, tmp_path: Path) -> None:
    path = _seed(vault)
    with pytest.raises(ActionWriteError) as excinfo:
        update_action(
            vault,
            tmp_path / "var",
            "7. Task Notes/Active/Task One.md",
            fields={"status": "in_progress"},
            reason="Start it",
            reviewer="myles",
            expected="deadbeef",
            today=WHEN,
        )
    assert excinfo.value.code == "stale_hash"
    assert path.read_text(encoding="utf-8") == ACTION


def test_missing_target_fails_closed(vault: Path, tmp_path: Path) -> None:
    with pytest.raises(ActionWriteError) as excinfo:
        update_action(
            vault,
            tmp_path / "var",
            "7. Task Notes/Active/Missing.md",
            fields={"status": "in_progress"},
            reason="Start it",
            reviewer="myles",
            today=WHEN,
        )
    assert excinfo.value.code == "missing_target"


def test_non_action_target_is_rejected(vault: Path, tmp_path: Path) -> None:
    project = vault / "9. Project/Alpha.md"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text('---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n---\n# Alpha\n', encoding="utf-8")
    with pytest.raises(ActionWriteError) as excinfo:
        update_action(
            vault,
            tmp_path / "var",
            "9. Project/Alpha.md",
            fields={"status": "in_progress"},
            reason="Wrong entity",
            reviewer="myles",
            today=WHEN,
        )
    assert excinfo.value.code == "not_action"


def test_unknown_field_is_rejected_before_writing(vault: Path, tmp_path: Path) -> None:
    path = _seed(vault)
    with pytest.raises(ActionWriteError) as excinfo:
        update_action(
            vault,
            tmp_path / "var",
            "7. Task Notes/Active/Task One.md",
            fields={"bogus": "x"},
            reason="Typo",
            reviewer="myles",
            today=WHEN,
        )
    assert excinfo.value.code == "unmapped_field"
    assert path.read_text(encoding="utf-8") == ACTION


def test_waiting_requires_waiting_on(vault: Path, tmp_path: Path) -> None:
    _seed(vault)
    with pytest.raises(ActionWriteError) as excinfo:
        update_action(
            vault,
            tmp_path / "var",
            "7. Task Notes/Active/Task One.md",
            fields={"status": "waiting"},
            reason="Blocked",
            reviewer="myles",
            today=WHEN,
        )
    assert excinfo.value.code == "waiting_requires_waiting_on"


def test_waiting_with_waiting_on_succeeds(vault: Path, tmp_path: Path) -> None:
    path = _seed(vault)
    update_action(
        vault,
        tmp_path / "var",
        "7. Task Notes/Active/Task One.md",
        fields={"status": "waiting", "waiting_on": "Vendor response"},
        reason="Wait for vendor",
        reviewer="myles",
        today=WHEN,
    )
    text = path.read_text(encoding="utf-8")
    assert "status: waiting" in text
    assert "waiting_on: Vendor response" in text


def test_complete_sets_done_and_completed(vault: Path, tmp_path: Path) -> None:
    path = _seed(vault)
    result = complete_action(
        vault,
        tmp_path / "var",
        "7. Task Notes/Active/Task One.md",
        reason="Finished",
        reviewer="myles",
        today=WHEN,
    )
    assert result.committed is True
    text = path.read_text(encoding="utf-8")
    assert "status: done" in text
    assert "completed: 2026-10-06" in text
    assert "last_action: Finished" in text


def test_mid_transaction_failure_rolls_back(vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _seed(vault)
    runtime = tmp_path / "var"
    real = gateway.atomic_write_text

    def flaky(target, content, **kwargs):
        if str(target).endswith("Task One.md"):
            raise RuntimeError("disk full")
        return real(target, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        update_action(
            vault,
            runtime,
            "7. Task Notes/Active/Task One.md",
            fields={"status": "in_progress"},
            reason="Start it",
            reviewer="myles",
            today=WHEN,
        )
    assert excinfo.value.code == "rolled_back"
    assert path.read_text(encoding="utf-8") == ACTION


DONE_ACTION = (
    "---\ntype: action\nstatus: done\npriority: P2\ncompleted: 2026-09-01\nrevision: 3\n---\n# Task One\nBody line\n"
)


def test_editing_a_done_action_does_not_rewrite_completed(vault: Path, tmp_path: Path) -> None:
    path = vault / "7. Task Notes/Active/Task One.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DONE_ACTION, encoding="utf-8")
    update_action(
        vault,
        tmp_path / "var",
        "7. Task Notes/Active/Task One.md",
        fields={"priority": "P1"},
        reason="Reprioritise",
        reviewer="myles",
        today=WHEN,
    )
    text = path.read_text(encoding="utf-8")
    assert "completed: 2026-09-01" in text
    assert "status: done" in text
    assert "priority: P1" in text


def test_completing_an_already_done_action_fails_clearly(vault: Path, tmp_path: Path) -> None:
    path = vault / "7. Task Notes/Active/Task One.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DONE_ACTION, encoding="utf-8")
    with pytest.raises(ActionWriteError) as excinfo:
        complete_action(
            vault,
            tmp_path / "var",
            "7. Task Notes/Active/Task One.md",
            reason="Done again",
            reviewer="myles",
            today=WHEN,
        )
    assert excinfo.value.code == "already_done"
    assert path.read_text(encoding="utf-8") == DONE_ACTION


def test_unknown_field_is_rejected_before_any_read(vault: Path, tmp_path: Path) -> None:
    with pytest.raises(ActionWriteError) as excinfo:
        update_action(
            vault,
            tmp_path / "var",
            "7. Task Notes/Active/Missing.md",
            fields={"bogus": "x"},
            reason="Typo",
            reviewer="myles",
            today=WHEN,
        )
    assert excinfo.value.code == "unmapped_field"
    assert not (vault / "7. Task Notes/Active/Missing.md").exists()
