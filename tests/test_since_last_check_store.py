"""Ticket 05 (Task 2): the since-last-check checkpoint store."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from worksync.inventory.parse import scan_vault
from worksync.safety.files import sha256_file
from worksync.work.checkpoint import acknowledge_checkpoint
from worksync.work.since_last_check import (
    CHECKPOINT_FILENAME,
    Checkpoint,
    checkpoint_path,
    current_hashes,
    read_checkpoint,
)

NOW = datetime(2026, 10, 18, 12, 30, 0, tzinfo=UTC)


def _write_action(write_note: Callable[[Path, str, str], Path], vault: Path, relative: str, body: str = "") -> Path:
    text = f"---\ntype: action\nstatus: open\n---\n{body or relative}\n"
    return write_note(vault, relative, text)


def test_read_checkpoint_is_none_before_any_acknowledge(vault: Path, tmp_path: Path) -> None:
    assert read_checkpoint(tmp_path / "runtime") is None


def test_checkpoint_path_is_the_user_state_file(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    assert checkpoint_path(runtime) == runtime.resolve() / "user_state" / CHECKPOINT_FILENAME


def test_acknowledge_round_trips_the_snapshot(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    write_note(vault, "a.md", "first\n")
    snapshot = current_hashes(vault)
    runtime = tmp_path / "runtime"

    result = acknowledge_checkpoint(vault, runtime, snapshot, now=NOW)

    assert result.committed
    checkpoint = read_checkpoint(runtime)
    assert checkpoint == Checkpoint(acknowledged_at=NOW.isoformat(), notes=snapshot)
    assert checkpoint_path(runtime).is_file()


def test_second_acknowledge_overwrites(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    write_note(vault, "a.md", "first\n")
    runtime = tmp_path / "runtime"
    acknowledge_checkpoint(vault, runtime, current_hashes(vault), now=NOW)

    write_note(vault, "a.md", "second\n")
    second = current_hashes(vault)
    acknowledge_checkpoint(vault, runtime, second, now=NOW)

    checkpoint = read_checkpoint(runtime)
    assert checkpoint is not None
    assert checkpoint.notes == second


def test_acknowledge_leaves_open_notes_untouched(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    first = _write_action(write_note, vault, "actions/a.md")
    second = _write_action(write_note, vault, "actions/b.md")
    before = {path: sha256_file(path) for path in (first, second)}

    acknowledge_checkpoint(vault, tmp_path / "runtime", current_hashes(vault), now=NOW)

    after = {path: sha256_file(path) for path in (first, second)}
    assert after == before


def test_read_checkpoint_raises_on_malformed_json(tmp_path: Path) -> None:
    path = checkpoint_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        read_checkpoint(tmp_path / "runtime")


def test_read_checkpoint_raises_on_wrong_shape(tmp_path: Path) -> None:
    path = checkpoint_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"acknowledged_at": "x", "notes": ["a"]}), encoding="utf-8")

    with pytest.raises(ValueError):
        read_checkpoint(tmp_path / "runtime")


def test_read_checkpoint_raises_on_unknown_schema_version(tmp_path: Path) -> None:
    path = checkpoint_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": 999, "acknowledged_at": "x", "notes": {}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        read_checkpoint(tmp_path / "runtime")


def test_read_checkpoint_raises_when_version_is_missing(tmp_path: Path) -> None:
    path = checkpoint_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"acknowledged_at": "x", "notes": {}}), encoding="utf-8")

    with pytest.raises(ValueError):
        read_checkpoint(tmp_path / "runtime")


def test_read_checkpoint_raises_when_the_path_is_not_a_file(tmp_path: Path) -> None:
    path = checkpoint_path(tmp_path / "runtime")
    path.mkdir(parents=True)

    with pytest.raises(ValueError):
        read_checkpoint(tmp_path / "runtime")


def test_read_checkpoint_raises_when_the_path_is_a_dangling_symlink(tmp_path: Path) -> None:
    path = checkpoint_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    try:
        path.symlink_to(path.parent / "missing-target.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    with pytest.raises(ValueError):
        read_checkpoint(tmp_path / "runtime")


def test_acknowledge_repairs_a_malformed_checkpoint(
    vault: Path, write_note: Callable[[Path, str, str], Path], tmp_path: Path
) -> None:
    write_note(vault, "a.md", "first\n")
    runtime = tmp_path / "runtime"
    path = checkpoint_path(runtime)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    snapshot = current_hashes(vault)
    result = acknowledge_checkpoint(vault, runtime, snapshot, now=NOW)

    assert result.committed
    assert read_checkpoint(runtime) == Checkpoint(acknowledged_at=NOW.isoformat(), notes=snapshot)


def test_current_hashes_matches_the_scanner(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    write_note(vault, "a.md", "alpha\n")
    write_note(vault, "nested/b.md", "beta\n")
    write_note(vault, "nested/c.txt", "not a note\n")

    expected = {record.path: record.content_hash for record in scan_vault(vault)}

    assert current_hashes(vault) == expected
    assert set(current_hashes(vault)) == {"a.md", "nested/b.md"}
