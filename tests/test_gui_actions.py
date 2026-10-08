"""Spec 6 ticket 01: the GUI write seam dispatches named actions to canonical services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.gui.actions import ActionError, dispatch_action
from worksync.gui.controller import GuiService
from worksync.safety import gateway

TODAY = date(2026, 10, 6)
A_PATH = "7. Task Notes/Active/Task One.md"
A2_PATH = "7. Task Notes/Active/Task Two.md"
ACTION = (
    "---\n"
    "type: action\n"
    "status: open\n"
    "priority: P2\n"
    "owners:\n"
    '  - "[[Myles]]"\n'
    'project: "[[Project - Alpha]]"\n'
    "due: 2026-10-01\n"
    "revision: 3\n"
    "---\n"
    "# Task One\n"
    "Body line\n"
)
ACTION_TWO = ACTION.replace("# Task One", "# Task Two")
PROJECT_PATH = "9. Project/Project - Alpha.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, A_PATH, ACTION)
    write_note(vault, A2_PATH, ACTION_TWO)
    write_note(
        vault,
        PROJECT_PATH,
        '---\ntype: project\nstatus: active\nproject_id: alpha\nowners:\n  - "[[Myles]]"\n---\n# Project - Alpha\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def _service(vault: Path, runtime: Path, *, reviewer: str | None = "Myles") -> GuiService:
    return GuiService(
        vault=vault, db_path=runtime / "index.sqlite3", runtime_root=runtime, vault_name="vault", reviewer=reviewer
    )


def test_complete_action_commits_and_echoes_the_change_set(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    result = dispatch_action(service, "complete-action", {"path": A_PATH, "reason": "Finished"}, today=TODAY)

    assert result["state"] == "ok"
    assert result["committed"] is True
    assert result["reviewer"] == "Myles"
    assert result["equivalent_cli"].startswith("worksync task complete")
    assert result["changes"] and result["changes"][0]["path"].endswith("Task One.md")
    assert result["changes"][0]["reviewer"] == "Myles"
    text = (vault / A_PATH).read_text(encoding="utf-8")
    assert "status: done" in text
    assert "completed:" in text


def test_update_action_dry_run_writes_nothing(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    result = dispatch_action(
        service,
        "update-action",
        {"path": A_PATH, "fields": {"status": "in_progress"}, "reason": "Start", "dry_run": True},
        today=TODAY,
    )
    assert result["committed"] is False
    assert result["planned"]
    assert "status: in_progress" in result["planned"]
    assert (vault / A_PATH).read_text(encoding="utf-8") == ACTION
    assert not (tmp_path / "var" / "journal").exists()


def test_stale_sha_is_rejected(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(
            service,
            "update-action",
            {"path": A_PATH, "fields": {"status": "in_progress"}, "reason": "Start", "expected": "deadbeef"},
            today=TODAY,
        )
    assert excinfo.value.code == "stale_hash"
    assert excinfo.value.status == 409
    assert (vault / A_PATH).read_text(encoding="utf-8") == ACTION


def test_missing_reason_is_rejected(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "complete-action", {"path": A_PATH}, today=TODAY)
    assert excinfo.value.code == "missing_reason"
    assert excinfo.value.status == 400


def test_missing_reviewer_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var", reviewer=None)
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "complete-action", {"path": A_PATH, "reason": "Done"}, today=TODAY)
    assert excinfo.value.code == "missing_reviewer"
    assert excinfo.value.status == 400
    assert (vault / A_PATH).read_text(encoding="utf-8") == ACTION


def test_unknown_field_is_rejected(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(
            service,
            "update-action",
            {"path": A_PATH, "fields": {"owner": "someone"}, "reason": "Reassign"},
            today=TODAY,
        )
    assert excinfo.value.code == "unmapped_field"
    assert excinfo.value.status == 422


def test_non_action_target_is_rejected(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(
            service,
            "update-action",
            {"path": PROJECT_PATH, "fields": {"status": "active"}, "reason": "Touch"},
            today=TODAY,
        )
    assert excinfo.value.code == "not_action"
    assert excinfo.value.status == 422


def test_unknown_action_is_not_found(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "nope", {}, today=TODAY)
    assert excinfo.value.code == "unknown_action"
    assert excinfo.value.status == 404


def test_set_reviewer_persists_and_is_used(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    service = _service(vault, runtime, reviewer=None)
    set_result = dispatch_action(service, "set-reviewer", {"reviewer": "Dana"}, today=TODAY)
    assert set_result["reviewer"] == "Dana"
    assert (runtime / "reviewer.json").is_file()

    result = dispatch_action(service, "complete-action", {"path": A_PATH, "reason": "Done"}, today=TODAY)
    assert result["reviewer"] == "Dana"
    assert result["changes"][0]["reviewer"] == "Dana"


def test_batch_commits_every_valid_intent(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    payload = {
        "reason": "Batch tidy",
        "items": [
            {"action": "complete-action", "path": A_PATH},
            {"action": "update-action", "path": A2_PATH, "fields": {"priority": "P1"}},
        ],
    }
    result = dispatch_action(service, "apply-batch", payload, today=TODAY)

    assert result["action"] == "apply-batch"
    assert result["committed"] is True
    assert len(result["changes"]) == 2
    assert {item["path"] for item in result["items"]} == {A_PATH, A2_PATH}
    assert all(item["equivalent_cli"].startswith("worksync task") for item in result["items"])
    assert "status: done" in (vault / A_PATH).read_text(encoding="utf-8")
    assert "priority: P1" in (vault / A2_PATH).read_text(encoding="utf-8")


def test_batch_with_one_stale_intent_rolls_back_everything(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    payload = {
        "reason": "Batch tidy",
        "items": [
            {"action": "complete-action", "path": A_PATH},
            {"action": "update-action", "path": A2_PATH, "fields": {"priority": "P1"}, "expected": "deadbeef"},
        ],
    }
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "apply-batch", payload, today=TODAY)
    assert excinfo.value.code == "stale_hash"
    assert (vault / A_PATH).read_text(encoding="utf-8") == ACTION
    assert (vault / A2_PATH).read_text(encoding="utf-8") == ACTION_TWO


def test_batch_requires_items(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "apply-batch", {"reason": "Nothing"}, today=TODAY)
    assert excinfo.value.code == "bad_request"
    assert excinfo.value.status == 400


def test_batch_rejects_an_unknown_item_action(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    payload = {"reason": "Batch", "items": [{"action": "nope", "path": A_PATH}]}
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "apply-batch", payload, today=TODAY)
    assert excinfo.value.code == "unknown_action"
    assert excinfo.value.status == 404


def test_batch_rolls_back_on_a_mid_apply_failure(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if path.name == "Task Two.md":
            raise OSError("disk full")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    payload = {
        "reason": "Batch tidy",
        "items": [
            {"action": "complete-action", "path": A_PATH},
            {"action": "complete-action", "path": A2_PATH},
        ],
    }
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "apply-batch", payload, today=TODAY)
    assert excinfo.value.code == "rolled_back"
    assert excinfo.value.status == 500
    assert (vault / A_PATH).read_text(encoding="utf-8") == ACTION
    assert (vault / A2_PATH).read_text(encoding="utf-8") == ACTION_TWO
