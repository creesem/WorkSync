"""Ticket 05 (Task 3): the "Since Last Check" read model."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.work.since_last_check import (
    ChangeKind,
    Checkpoint,
    NoteChange,
    SinceLastCheckResult,
    current_hashes,
    since_last_check,
)

GENERATED_AT = "2026-10-18T13:00:00+00:00"
ACKNOWLEDGED_AT = "2026-10-18T12:30:00+00:00"


def _checkpoint(vault: Path, *, acknowledged_at: str = ACKNOWLEDGED_AT) -> Checkpoint:
    return Checkpoint(acknowledged_at=acknowledged_at, notes=current_hashes(vault))


def _titled(title: str, body: str = "body\n") -> str:
    return f"---\ntitle: {title}\n---\n{body}"


def test_no_checkpoint_is_unavailable(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    write_note(vault, "a.md", _titled("Alpha"))

    result = since_last_check(vault, None, generated_at=GENERATED_AT)

    assert result == SinceLastCheckResult(
        availability="unavailable",
        error_state="no_checkpoint",
        acknowledged_at=None,
        generated_at=GENERATED_AT,
        items=(),
        total_count=0,
    )


def test_no_checkpoint_does_not_list_every_note_as_added(
    vault: Path, write_note: Callable[[Path, str, str], Path]
) -> None:
    write_note(vault, "a.md", _titled("Alpha"))
    write_note(vault, "b.md", _titled("Bravo"))

    result = since_last_check(vault, None, generated_at=GENERATED_AT)

    assert result.items == ()
    assert result.total_count == 0


def test_empty_checkpoint_lists_every_note_as_added_with_titles(
    vault: Path, write_note: Callable[[Path, str, str], Path]
) -> None:
    write_note(vault, "a.md", _titled("Alpha"))
    write_note(vault, "nested/b.md", _titled("Bravo"))
    checkpoint = Checkpoint(acknowledged_at=ACKNOWLEDGED_AT, notes={})
    hashes = current_hashes(vault)

    result = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)

    assert result.availability == "available"
    assert result.error_state is None
    assert result.acknowledged_at == ACKNOWLEDGED_AT
    assert result.generated_at == GENERATED_AT
    assert result.total_count == 2
    assert result.items == (
        NoteChange(
            path="a.md",
            kind=ChangeKind.ADDED,
            title="Alpha",
            current_hash=hashes["a.md"],
            previous_hash=None,
        ),
        NoteChange(
            path="nested/b.md",
            kind=ChangeKind.ADDED,
            title="Bravo",
            current_hash=hashes["nested/b.md"],
            previous_hash=None,
        ),
    )


def test_edited_note_is_changed_with_both_hashes(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    write_note(vault, "a.md", _titled("Alpha", "first\n"))
    write_note(vault, "b.md", _titled("Bravo"))
    checkpoint = _checkpoint(vault)
    previous = checkpoint.notes["a.md"]

    write_note(vault, "a.md", _titled("Alpha", "second\n"))
    current = current_hashes(vault)["a.md"]

    result = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)

    assert result.items == (
        NoteChange(
            path="a.md",
            kind=ChangeKind.CHANGED,
            title="Alpha",
            current_hash=current,
            previous_hash=previous,
        ),
    )
    assert result.total_count == 1


def test_added_note_after_acknowledge(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    write_note(vault, "a.md", _titled("Alpha"))
    checkpoint = _checkpoint(vault)

    write_note(vault, "b.md", _titled("Bravo"))

    result = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)

    assert result.items == (
        NoteChange(
            path="b.md",
            kind=ChangeKind.ADDED,
            title="Bravo",
            current_hash=current_hashes(vault)["b.md"],
            previous_hash=None,
        ),
    )


def test_removed_note_has_empty_title_and_no_current_hash(
    vault: Path, write_note: Callable[[Path, str, str], Path]
) -> None:
    write_note(vault, "a.md", _titled("Alpha"))
    write_note(vault, "b.md", _titled("Bravo"))
    checkpoint = _checkpoint(vault)
    previous = checkpoint.notes["b.md"]

    (vault / "b.md").unlink()

    result = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)

    assert result.items == (
        NoteChange(
            path="b.md",
            kind=ChangeKind.REMOVED,
            title="",
            current_hash=None,
            previous_hash=previous,
        ),
    )


def test_unchanged_notes_are_not_listed(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    write_note(vault, "a.md", _titled("Alpha"))
    checkpoint = _checkpoint(vault)

    write_note(vault, "a.md", _titled("Alpha"))

    result = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)

    assert result.items == ()
    assert result.total_count == 0


def test_duplicate_import_of_identical_bytes_makes_no_change(
    vault: Path, write_note: Callable[[Path, str, str], Path]
) -> None:
    text = _titled("Alpha")
    write_note(vault, "a.md", text)
    checkpoint = _checkpoint(vault)

    write_note(vault, "a.md", text)

    result = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)

    assert [item.path for item in result.items] == []


def test_items_are_sorted_by_path(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    checkpoint = Checkpoint(acknowledged_at=ACKNOWLEDGED_AT, notes={})
    write_note(vault, "zeta.md", _titled("Zeta"))
    write_note(vault, "alpha.md", _titled("Alpha"))
    write_note(vault, "nested/mid.md", _titled("Mid"))

    result = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)

    assert [item.path for item in result.items] == ["alpha.md", "nested/mid.md", "zeta.md"]


def test_result_is_deterministic(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    write_note(vault, "a.md", _titled("Alpha", "first\n"))
    write_note(vault, "b.md", _titled("Bravo"))
    checkpoint = _checkpoint(vault)
    write_note(vault, "a.md", _titled("Alpha", "second\n"))
    write_note(vault, "c.md", _titled("Charlie"))

    first = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)
    second = since_last_check(vault, checkpoint, generated_at=GENERATED_AT)

    assert first == second
