"""Ticket 13 (Task 1): the layout profile save/reset store."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from worksync.safety.files import sha256_bytes, sha256_file
from worksync.safety.models import MutationError
from worksync.work.layout_profile import (
    PROFILE_FILENAME,
    LayoutProfile,
    default_profile,
    profile_path,
    read_profile,
)
from worksync.work.layout_profile_store import reset_profile, save_profile

NOW = "2026-10-18T12:30:00+00:00"
LATER = "2026-10-18T13:45:00+00:00"


def _snapshot(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in sorted(root.rglob("*")) if path.is_file()}


def test_save_profile_creates_the_user_state_record(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    result = save_profile(vault, runtime, default_profile(), now=NOW)

    target = runtime.resolve() / "user_state" / PROFILE_FILENAME
    assert result.committed
    assert target.is_file()
    assert target == profile_path(runtime)
    assert result.changes[0]["kind"] == "create"
    assert read_profile(runtime) == replace(default_profile(), revision=2, updated_at=NOW)


def test_save_profile_journals_a_user_state_write(vault: Path, tmp_path: Path) -> None:
    result = save_profile(vault, tmp_path / "runtime", default_profile(), now=NOW)

    journal = json.loads(result.journal.read_text(encoding="utf-8"))
    assert journal["verb"] == "save_layout"
    assert journal["class"] == "user_state"
    assert journal["reason"] == "Save the Command Center layout profile"
    assert journal["committed"] is True
    assert journal["ops"][0]["zone"] == "user_state"


def test_second_save_updates_with_a_sha_precondition(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    save_profile(vault, runtime, default_profile(), now=NOW)
    before = read_profile(runtime)
    previous_bytes = profile_path(runtime).read_bytes()

    second = save_profile(vault, runtime, before, now=LATER)

    saved = replace(before, revision=before.revision + 1, updated_at=LATER)
    after_bytes = profile_path(runtime).read_bytes()
    assert second.committed
    assert second.changes[0]["kind"] == "update"
    assert second.changes[0]["before"] == sha256_bytes(previous_bytes)
    assert second.changes[0]["after"] == sha256_bytes(after_bytes)
    assert read_profile(runtime) == saved
    assert saved.revision == 3
    assert saved.updated_at == LATER


def test_second_save_backs_up_the_previous_profile(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    first = save_profile(vault, runtime, default_profile(), now=NOW)
    previous_bytes = profile_path(runtime).read_bytes()

    second = save_profile(vault, runtime, read_profile(runtime), now=LATER)

    backups = sorted((runtime / "backups").rglob("*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == previous_bytes
    assert backups[0].read_bytes() != profile_path(runtime).read_bytes()
    assert first.journal != second.journal


def test_save_profile_honours_the_requested_profile_fields(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    requested = replace(
        default_profile(),
        owner_id="person-9",
        section_order=("since_last_check", "needs_attention", "my_priorities"),
        visibility={"needs_attention": True, "my_priorities": False, "since_last_check": True},
    )

    save_profile(vault, runtime, requested, now=NOW)

    assert read_profile(runtime) == replace(requested, revision=2, updated_at=NOW)


def test_save_profile_repairs_a_malformed_profile_without_parsing_it(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    target = profile_path(runtime)
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")

    result = save_profile(vault, runtime, default_profile(), now=NOW)

    assert result.committed
    assert result.changes[0]["kind"] == "update"
    assert read_profile(runtime) == replace(default_profile(), revision=2, updated_at=NOW)


def test_reset_profile_writes_the_default_at_revision_one(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    requested = replace(
        default_profile(),
        owner_id="person-9",
        section_order=("since_last_check", "needs_attention", "my_priorities"),
        revision=6,
        updated_at="2026-10-17T00:00:00+00:00",
    )
    save_profile(vault, runtime, requested, now=NOW)

    result = reset_profile(vault, runtime, now=LATER)

    assert result.committed
    assert result.changes[0]["kind"] == "update"
    assert read_profile(runtime) == replace(default_profile(), updated_at=LATER)


def test_reset_profile_creates_the_record_when_absent(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    result = reset_profile(vault, runtime, now=NOW)

    assert result.committed
    assert result.changes[0]["kind"] == "create"
    assert read_profile(runtime) == replace(default_profile(), updated_at=NOW)


def test_save_and_reset_leave_every_vault_note_untouched(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    write_note(vault, "actions/a.md", "---\ntype: action\n---\nalpha\n")
    write_note(vault, "tickets/b.md", "---\ntype: ticket\n---\nbravo\n")
    before = _snapshot(vault)
    runtime = tmp_path / "runtime"

    save_profile(vault, runtime, default_profile(), now=NOW)
    save_profile(vault, runtime, read_profile(runtime), now=LATER)
    reset_profile(vault, runtime, now=LATER)

    assert _snapshot(vault) == before
    assert profile_path(runtime).is_file()


def test_save_profile_keeps_the_stored_json_stable(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    save_profile(
        vault,
        runtime,
        replace(default_profile(), owner_id="person-9"),
        now=NOW,
    )

    stored = profile_path(runtime).read_text(encoding="utf-8")
    payload = json.loads(stored)
    assert stored == json.dumps(payload, sort_keys=True, ensure_ascii=False)
    assert payload == LayoutProfile.from_dict(payload).to_dict()


def test_save_profile_rejects_a_profile_whose_file_is_a_directory(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    profile_path(runtime).mkdir(parents=True)

    with pytest.raises(MutationError):
        save_profile(vault, runtime, default_profile(), now=NOW)
