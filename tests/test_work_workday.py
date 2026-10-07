"""Spec 3: five-slot workday plan, steering, ranking, import, and quick completion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.work.repository import WorkIndex
from worksync.work.workday import (
    build_workday,
    complete_from_plan,
    import_legacy,
    set_selection,
    set_steering,
)
from worksync.work.writer import ActionWriteError

TODAY = date(2026, 10, 6)
A_PATH = "7. Task Notes/Active/Task A.md"
B_PATH = "7. Task Notes/Active/Task B.md"
W_PATH = "7. Task Notes/Active/Task W.md"
D_PATH = "7. Task Notes/Active/Task D.md"


def _action(status: str, priority: str, project: str, *, due: str = "2026-10-20", extra: str = "") -> str:
    return (
        "---\n"
        "type: action\n"
        f"status: {status}\n"
        f"priority: {priority}\n"
        "owners:\n"
        '  - "[[Myles Creese]]"\n'
        f'project: "[[{project}]]"\n'
        f"due: {due}\n"
        f"{extra}"
        "---\n"
        f"# Task\n"
    )


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Alpha.md",
        '---\ntype: project\nstatus: active\nproject_id: alpha\nowners:\n  - "[[Myles]]"\n---\n# Project - Alpha\n',
    )
    write_note(
        vault,
        "9. Project/Project - Beta.md",
        '---\ntype: project\nstatus: active\nproject_id: beta\nowners:\n  - "[[Myles]]"\n---\n# Project - Beta\n',
    )
    write_note(vault, A_PATH, _action("open", "P3", "Project - Alpha"))
    write_note(vault, B_PATH, _action("open", "P1", "Project - Beta"))
    write_note(vault, W_PATH, _action("waiting", "P2", "Project - Alpha", extra="waiting_on: Vendor\n"))
    write_note(vault, D_PATH, _action("done", "P1", "Project - Beta", extra="completed: 2026-10-01\n"))


def _index(vault: Path, write_note: Callable[..., Path]) -> WorkIndex:
    _seed(vault, write_note)
    return WorkIndex.from_vault(vault)


def test_active_actions_exclude_done(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    plan = build_workday(index, today=TODAY, runtime_root=tmp_path / "var")
    assert len(plan["active_actions"]) == 3
    assert all(task["path"] != D_PATH for task in plan["active_actions"])


def test_suggestions_carry_reasons(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    plan = build_workday(index, today=TODAY, runtime_root=tmp_path / "var")
    top = plan["suggestions"]["must_win"][0]
    assert top["action"]["path"] == B_PATH
    assert "P1" in top["reasons"]


def test_every_suggestion_carries_a_reason(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    plan = build_workday(index, today=TODAY, runtime_root=tmp_path / "var")
    for items in plan["suggestions"].values():
        for item in items:
            assert item["reasons"], item["action"]["path"]


def test_project_focus_changes_ranking(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    runtime = tmp_path / "var"
    set_steering(index, runtime, {"focus_project": "Project - Alpha"}, today=TODAY)
    plan = build_workday(index, today=TODAY, runtime_root=runtime)
    top = plan["suggestions"]["must_win"][0]
    assert top["action"]["path"] == A_PATH
    assert "today's project focus" in top["reasons"]
    assert plan["steering_effect"]["focus_match_count"] >= 1


def test_urgent_elevation_changes_ranking(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    runtime = tmp_path / "var"
    set_steering(index, runtime, {"urgent_path": B_PATH}, today=TODAY)
    plan = build_workday(index, today=TODAY, runtime_root=runtime)
    top = plan["suggestions"]["must_win"][0]
    assert top["action"]["path"] == B_PATH
    assert "manually elevated today" in top["reasons"]
    assert plan["steering_effect"]["urgent_match_count"] == 1


def test_waiting_task_only_suggests_for_unblock(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    plan = build_workday(index, today=TODAY, runtime_root=tmp_path / "var")
    assert all(item["action"]["path"] != W_PATH for item in plan["suggestions"]["must_win"])
    assert any(item["action"]["path"] == W_PATH for item in plan["suggestions"]["unblock"])


def test_set_selection_persists_and_rejects_stale(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    runtime = tmp_path / "var"
    plan = set_selection(index, runtime, "must_win", A_PATH, today=TODAY)
    assert plan["selections"]["must_win"]["path"] == A_PATH
    again = build_workday(index, today=TODAY, runtime_root=runtime)
    assert again["selections"]["must_win"]["path"] == A_PATH
    with pytest.raises(ValueError):
        set_selection(index, runtime, "must_win", "no/such/task.md", today=TODAY)


def test_stale_persisted_selection_is_ignored_on_read(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    index = _index(vault, write_note)
    runtime = tmp_path / "var"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "workday-plan.json").write_text(
        json.dumps(
            {"version": 1, "date": TODAY.isoformat(), "selections": {"must_win": "no/such/task.md"}, "steering": {}}
        ),
        encoding="utf-8",
    )
    plan = build_workday(index, today=TODAY, runtime_root=runtime)
    assert plan["selections"] == {}


def test_previous_day_plan_does_not_carry(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    runtime = tmp_path / "var"
    set_selection(index, runtime, "must_win", A_PATH, today=TODAY)
    tomorrow = build_workday(index, today=date(2026, 10, 7), runtime_root=runtime)
    assert tomorrow["selections"] == {}


def test_clearing_steering_preserves_selections(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    runtime = tmp_path / "var"
    set_selection(index, runtime, "must_win", A_PATH, today=TODAY)
    set_steering(index, runtime, {"focus_project": "Project - Alpha", "note": "Push Alpha"}, today=TODAY)
    plan = set_steering(index, runtime, {"clear": True}, today=TODAY)
    assert plan["selections"]["must_win"]["path"] == A_PATH
    assert plan["steering"]["focus_project"] == ""


def test_import_legacy_drops_stale_references(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    runtime = tmp_path / "var"
    legacy = tmp_path / "legacy-workday-plan.json"
    legacy.write_text(
        json.dumps(
            {
                "version": 1,
                "date": "2026-10-05",
                "selections": {"must_win": A_PATH, "support_one": "stale/path.md"},
                "steering": {
                    "focus_project": "Project - Alpha",
                    "urgent_paths": [B_PATH, "stale/path.md"],
                    "note": "Go",
                },
            }
        ),
        encoding="utf-8",
    )
    report = import_legacy(index, runtime, legacy, today=TODAY)
    plan = report["plan"]
    assert plan["selections"]["must_win"]["path"] == A_PATH
    assert "support_one" not in plan["selections"]
    assert plan["steering"]["focus_project"] == "Project - Alpha"
    assert plan["steering"]["urgent_paths"] == [B_PATH]
    assert "stale/path.md" in report["dropped"]


def test_dry_run_set_selection_does_not_persist(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    index = _index(vault, write_note)
    runtime = tmp_path / "var"
    plan = set_selection(index, runtime, "must_win", A_PATH, today=TODAY, dry_run=True)
    assert plan["dry_run"] is True
    assert plan["selections"]["must_win"]["path"] == A_PATH
    assert not (runtime / "workday-plan.json").exists()


def test_quick_complete_returns_refreshed_plan(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _index(vault, write_note)
    runtime = tmp_path / "var"
    sha = hashlib.sha256((vault / A_PATH).read_bytes()).hexdigest()
    result = complete_from_plan(vault, runtime, A_PATH, sha=sha, reason="Done now", reviewer="myles", today=TODAY)
    assert result["completion"]["committed"] is True
    assert all(task["path"] != A_PATH for task in result["plan"]["active_actions"])
    assert "completed: 2026-10-06" in (vault / A_PATH).read_text(encoding="utf-8")


def test_quick_complete_rejects_stale_sha(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _index(vault, write_note)
    with pytest.raises(ActionWriteError) as excinfo:
        complete_from_plan(
            vault, tmp_path / "var", A_PATH, sha="deadbeef", reason="Done now", reviewer="myles", today=TODAY
        )
    assert excinfo.value.code == "stale_hash"
