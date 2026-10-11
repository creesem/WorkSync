"""Spec 9 ticket 04: date-gap classification, transitions, and the missed-date rule."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.work.lifecycle.date_gaps import (
    DATE_CLASSES,
    DATE_TRANSITIONS,
    DateClass,
    DateError,
    DateRecord,
    apply_transition,
    legal_actions,
    plan_due_change,
    validate_record,
    validate_transition,
)
from worksync.work.writer import ActionWriteError, commit_action_plans

TODAY = date(2026, 10, 10)
ACTION = "7. Task Notes/Active/Confirm the date.md"


def _action(write_note: Callable[..., Path], vault: Path, frontmatter: str = "") -> Path:
    text = f"---\ntype: action\nstatus: open\n{frontmatter}---\n# Confirm the date\n"
    return write_note(vault, ACTION, text)


def test_six_date_classes_are_first_class() -> None:
    assert {
        "confirmed",
        "conditional",
        "internal-working",
        "completed-occurred",
        "stale-missed",
        "needs-date",
    } == DATE_CLASSES
    assert DateClass.INTERNAL_WORKING == "internal-working"


def test_every_legal_transition() -> None:
    for (state, action), target in DATE_TRANSITIONS.items():
        result = apply_transition(
            state,
            action,
            actor="Myles",
            reason="Reviewed",
            source="[[Meeting - Plan]]",
            previous="2026-10-01",
            revised="2026-11-01",
        )
        assert result == target


def test_illegal_and_unknown_fail_closed() -> None:
    with pytest.raises(DateError) as illegal:
        apply_transition("confirmed", "confirm", actor="Myles", reason="Again")
    assert illegal.value.code == "illegal_transition"

    with pytest.raises(DateError) as unknown_state:
        apply_transition("sometime", "confirm", actor="Myles", reason="x")
    assert unknown_state.value.code == "unknown_state"

    with pytest.raises(DateError) as missing_reason:
        apply_transition("needs-date", "confirm", actor="Myles", reason="")
    assert missing_reason.value.code == "missing_reason"


def test_confirm_requires_a_source_or_evidence() -> None:
    with pytest.raises(DateError) as excinfo:
        validate_transition("needs-date", "confirm", actor="Myles", reason="Agreed")
    assert excinfo.value.code == "missing_source"


def test_missed_date_preserve_and_add_is_enforced() -> None:
    with pytest.raises(DateError) as missing_previous:
        validate_transition("stale-missed", "revise", actor="Myles", reason="Slipped", revised="2026-11-01")
    assert missing_previous.value.code == "missing_previous"

    with pytest.raises(DateError) as missing_revised:
        validate_transition("stale-missed", "revise", actor="Myles", reason="Slipped", previous="2026-10-01")
    assert missing_revised.value.code == "missing_revised"

    transition = validate_transition(
        "stale-missed",
        "revise",
        actor="Myles",
        reason="Vendor slipped",
        previous="2026-10-01",
        revised="2026-11-01",
        source="[[Meeting - Reset]]",
    )
    assert transition.to_state == "confirmed"


def test_stale_missed_requires_previous_date_and_reason() -> None:
    with pytest.raises(DateError) as excinfo:
        validate_record(DateRecord(date_class="stale-missed", previous="2026-10-01"))
    assert excinfo.value.code == "missing_reason"

    validate_record(DateRecord(date_class="stale-missed", previous="2026-10-01", reason="Missed"))


def test_needs_date_records_the_undated_work_fields() -> None:
    with pytest.raises(DateError) as excinfo:
        validate_record(DateRecord(date_class="needs-date", owner="Tracy"))
    assert excinfo.value.code == "missing_dependency"

    validate_record(
        DateRecord(
            date_class="needs-date",
            owner="Tracy",
            dependency="Awaiting vendor estimate",
            requested="2026-10-05",
            followup="Chased 2026-10-09",
        )
    )


def test_invalid_iso_date_fails_closed() -> None:
    with pytest.raises(DateError) as excinfo:
        validate_record(DateRecord(date_class="confirmed", value="next Tuesday", source="[[Meeting]]"))
    assert excinfo.value.code == "invalid_date"


def test_confirmed_requires_value_and_source() -> None:
    with pytest.raises(DateError) as missing_source:
        validate_record(DateRecord(date_class="confirmed", value="2026-11-01"))
    assert missing_source.value.code == "missing_source"

    validate_record(DateRecord(date_class="confirmed", value="2026-11-01", source="[[Meeting]]"))


def test_legal_actions_reported_per_class() -> None:
    assert set(legal_actions("needs-date")) == {"confirm", "conditional", "internal"}
    assert legal_actions("stale-missed") == ("revise", "undate")


def test_canonical_due_change_requires_current_sha(vault: Path, write_note: Callable[..., Path]) -> None:
    _action(write_note, vault, "due: 2026-10-01\n")

    with pytest.raises(ActionWriteError) as excinfo:
        plan_due_change(
            vault, ACTION, due="2026-11-01", reason="Reset", reviewer="Myles", expected="deadbeef", today=TODAY
        )
    assert excinfo.value.code == "stale_hash"

    plan = plan_due_change(
        vault, ACTION, due="2026-11-01", reason="Reset", reviewer="Myles", expected=None, today=TODAY
    )
    assert "due: 2026-11-01" in plan.content


def test_canonical_due_change_creates_a_recoverable_backup(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    note = _action(write_note, vault, "due: 2026-10-01\n")
    before = note.read_text(encoding="utf-8")
    runtime = tmp_path / "var"
    plan = plan_due_change(
        vault, ACTION, due="2026-11-01", reason="Reset", reviewer="Myles", expected=None, today=TODAY
    )

    commit_action_plans(vault, runtime, (plan,), verb="update_action", reviewer="Myles", reason="Reset")

    assert "due: 2026-11-01" in note.read_text(encoding="utf-8")
    backups = sorted((runtime / "backups").glob("backup-*/file-*"))
    assert any(backup.read_text(encoding="utf-8") == before for backup in backups)
