"""Ticket 16 (Block 7, Task 1): the override save/clear store."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from worksync.safety.files import sha256_bytes, sha256_file
from worksync.safety.models import MutationError
from worksync.work.override import (
    OVERRIDES_FILENAME,
    SCHEMA_VERSION,
    OverrideRecord,
    overrides_path,
    read_override_records,
    read_overrides,
)
from worksync.work.override_store import clear_override, save_override
from worksync.work.prioritization import Override

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 20, 10, 30, tzinfo=UTC)


def _snapshot(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in sorted(root.rglob("*")) if path.is_file()}


def test_save_override_creates_the_user_state_record(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    result = save_override(vault, runtime, "ticket-1", "pin", reason="the exec asked", now=NOW)

    target = runtime.resolve() / "user_state" / OVERRIDES_FILENAME
    assert result.committed
    assert target == overrides_path(runtime)
    assert target.is_file()
    assert result.changes[0]["kind"] == "create"
    assert read_override_records(runtime) == (
        OverrideRecord(
            override_id="ticket-1",
            target_id="ticket-1",
            kind="pin",
            reason="the exec asked",
            status="active",
            created_at=NOW.isoformat(),
            updated_at=NOW.isoformat(),
        ),
    )


def test_save_override_journals_a_user_state_write(vault: Path, tmp_path: Path) -> None:
    result = save_override(vault, tmp_path / "runtime", "ticket-1", "pin", now=NOW)

    journal = json.loads(result.journal.read_text(encoding="utf-8"))
    assert journal["verb"] == "save_override"
    assert journal["class"] == "user_state"
    assert journal["reason"] == "Save pin override for ticket-1"
    assert journal["committed"] is True
    assert journal["ops"][0]["zone"] == "user_state"


def test_second_save_replaces_the_target_in_place(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    save_override(vault, runtime, "ticket-1", "pin", reason="the exec asked", now=NOW)
    previous_bytes = overrides_path(runtime).read_bytes()

    second = save_override(vault, runtime, "ticket-1", "defer", reason="waiting on legal", now=LATER)

    after_bytes = overrides_path(runtime).read_bytes()
    assert second.committed
    assert second.changes[0]["kind"] == "update"
    assert second.changes[0]["before"] == sha256_bytes(previous_bytes)
    assert second.changes[0]["after"] == sha256_bytes(after_bytes)
    assert read_override_records(runtime) == (
        OverrideRecord(
            override_id="ticket-1",
            target_id="ticket-1",
            kind="defer",
            reason="waiting on legal",
            status="active",
            created_at=NOW.isoformat(),
            updated_at=LATER.isoformat(),
        ),
    )


def test_second_save_backs_up_the_previous_file(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    save_override(vault, runtime, "ticket-1", "pin", now=NOW)
    previous_bytes = overrides_path(runtime).read_bytes()

    save_override(vault, runtime, "ticket-2", "defer", now=LATER)

    backups = sorted((runtime / "backups").rglob("*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == previous_bytes
    assert backups[0].read_bytes() != overrides_path(runtime).read_bytes()


def test_saving_a_different_target_appends(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    save_override(vault, runtime, "ticket-1", "pin", now=NOW)

    save_override(vault, runtime, "ticket-2", "focus_today", now=LATER)

    records = read_override_records(runtime)
    assert [record.target_id for record in records] == ["ticket-1", "ticket-2"]
    assert [record.kind for record in records] == ["pin", "focus_today"]


def test_clear_override_soft_clears_the_record(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    save_override(vault, runtime, "ticket-1", "pin", reason="the exec asked", now=NOW)

    result = clear_override(vault, runtime, "ticket-1", now=LATER)

    assert result.committed
    assert result.changes[0]["kind"] == "update"
    assert read_override_records(runtime) == (
        OverrideRecord(
            override_id="ticket-1",
            target_id="ticket-1",
            kind="pin",
            reason="the exec asked",
            status="cleared",
            created_at=NOW.isoformat(),
            updated_at=LATER.isoformat(),
        ),
    )
    assert read_overrides(runtime) == ()


def test_clear_override_journals_a_user_state_write(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    save_override(vault, runtime, "ticket-1", "pin", now=NOW)

    result = clear_override(vault, runtime, "ticket-1", now=LATER)

    journal = json.loads(result.journal.read_text(encoding="utf-8"))
    assert journal["verb"] == "clear_override"
    assert journal["class"] == "user_state"
    assert journal["reason"] == "Clear the override for ticket-1"
    assert journal["ops"][0]["zone"] == "user_state"


def test_save_after_clear_reactivates_one_record(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    save_override(vault, runtime, "ticket-1", "pin", now=NOW)
    clear_override(vault, runtime, "ticket-1", now=LATER)

    save_override(vault, runtime, "ticket-1", "always_prioritize", now=LATER)

    records = read_override_records(runtime)
    assert len(records) == 1
    assert records[0].status == "active"
    assert records[0].kind == "always_prioritize"
    assert records[0].created_at == NOW.isoformat()
    assert records[0].updated_at == LATER.isoformat()
    assert read_overrides(runtime) == (Override("ticket-1", "ticket-1", "always_prioritize", ""),)


def test_clear_without_a_record_writes_an_empty_collection(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    result = clear_override(vault, runtime, "ticket-1", now=NOW)

    assert result.committed
    assert result.changes[0]["kind"] == "create"
    assert read_override_records(runtime) == ()


def test_save_rejects_an_unknown_kind_without_writing(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    with pytest.raises(ValueError):
        save_override(vault, runtime, "ticket-1", "urgent", now=NOW)

    assert not overrides_path(runtime).exists()


def test_save_refuses_to_overwrite_a_corrupt_file(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    target = overrides_path(runtime)
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        save_override(vault, runtime, "ticket-1", "pin", now=NOW)

    assert target.read_text(encoding="utf-8") == "{not json"


def test_save_and_clear_leave_every_vault_note_untouched(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    write_note(vault, "actions/a.md", "---\ntype: action\n---\nalpha\n")
    write_note(vault, "tickets/b.md", "---\ntype: ticket\n---\nbravo\n")
    before = _snapshot(vault)
    runtime = tmp_path / "runtime"

    save_override(vault, runtime, "ticket-1", "pin", now=NOW)
    save_override(vault, runtime, "ticket-1", "defer", now=LATER)
    clear_override(vault, runtime, "ticket-1", now=LATER)

    assert _snapshot(vault) == before
    user_state_files = [path.name for path in (runtime / "user_state").rglob("*") if path.is_file()]
    assert user_state_files == [OVERRIDES_FILENAME]


def test_save_keeps_the_stored_json_stable(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    save_override(vault, runtime, "ticket-1", "pin", now=NOW)

    stored = overrides_path(runtime).read_text(encoding="utf-8")
    payload = json.loads(stored)
    assert stored == json.dumps(payload, sort_keys=True, ensure_ascii=False)
    assert payload["version"] == SCHEMA_VERSION
    assert payload == {"version": 1, "overrides": [OverrideRecord.from_dict(payload["overrides"][0]).to_dict()]}


def test_save_refuses_when_the_record_path_is_a_directory(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    overrides_path(runtime).mkdir(parents=True)

    with pytest.raises((ValueError, MutationError)):
        save_override(vault, runtime, "ticket-1", "pin", now=NOW)
