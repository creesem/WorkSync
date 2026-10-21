"""Ticket 16 (Block 7, Task 1): the read-only override model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.work.override import (
    KNOWN_OVERRIDE_KINDS,
    OVERRIDES_FILENAME,
    SCHEMA_VERSION,
    OverrideRecord,
    overrides_path,
    read_override_records,
    read_overrides,
)
from worksync.work.prioritization import Override

NOW = "2026-10-20T09:00:00+00:00"


def _record(**overrides: object) -> dict:
    payload = {
        "override_id": "ticket-1",
        "target_id": "ticket-1",
        "kind": "pin",
        "reason": "the exec asked",
        "status": "active",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return payload


def _payload(*records: dict) -> dict:
    return {"version": SCHEMA_VERSION, "overrides": list(records)}


def _write_overrides(tmp_path: Path, payload: object) -> Path:
    path = overrides_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_constants_are_the_r1_shape() -> None:
    assert OVERRIDES_FILENAME == "overrides.json"
    assert SCHEMA_VERSION == 1
    assert KNOWN_OVERRIDE_KINDS == ("pin", "focus_today", "defer", "not_relevant", "always_prioritize")


def test_overrides_path_is_the_user_state_record(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    assert overrides_path(runtime) == runtime.resolve() / "user_state" / OVERRIDES_FILENAME


def test_record_to_dict_round_trips_through_from_dict() -> None:
    record = OverrideRecord(
        override_id="ticket-1",
        target_id="ticket-1",
        kind="defer",
        reason="waiting on legal",
        status="cleared",
        created_at=NOW,
        updated_at=NOW,
    )

    assert OverrideRecord.from_dict(record.to_dict()) == record


def test_from_dict_defaults_the_optional_fields() -> None:
    record = OverrideRecord.from_dict({"override_id": "ticket-1", "target_id": "ticket-1", "kind": "pin"})

    assert record == OverrideRecord(override_id="ticket-1", target_id="ticket-1", kind="pin")


def test_read_override_records_returns_empty_when_absent(tmp_path: Path) -> None:
    assert read_override_records(tmp_path / "runtime") == ()


def test_read_override_records_returns_the_stored_records(tmp_path: Path) -> None:
    _write_overrides(
        tmp_path,
        _payload(
            _record(),
            _record(override_id="ticket-2", target_id="ticket-2", kind="not_relevant", reason=""),
        ),
    )

    records = read_override_records(tmp_path / "runtime")

    assert records == (
        OverrideRecord("ticket-1", "ticket-1", "pin", "the exec asked", "active", NOW, NOW),
        OverrideRecord("ticket-2", "ticket-2", "not_relevant", "", "active", NOW, NOW),
    )


def test_read_override_records_raises_on_malformed_json(tmp_path: Path) -> None:
    path = overrides_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        read_override_records(tmp_path / "runtime")


def test_read_override_records_raises_when_the_path_is_a_directory(tmp_path: Path) -> None:
    overrides_path(tmp_path / "runtime").mkdir(parents=True)

    with pytest.raises(ValueError):
        read_override_records(tmp_path / "runtime")


def test_read_override_records_raises_when_the_path_is_a_dangling_symlink(tmp_path: Path) -> None:
    path = overrides_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    try:
        path.symlink_to(path.parent / "missing-target.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    with pytest.raises(ValueError):
        read_override_records(tmp_path / "runtime")


def test_read_override_records_raises_on_an_unknown_schema_version(tmp_path: Path) -> None:
    _write_overrides(tmp_path, {"version": 999, "overrides": []})

    with pytest.raises(ValueError):
        read_override_records(tmp_path / "runtime")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"overrides": []},
        {"version": SCHEMA_VERSION},
        {"version": SCHEMA_VERSION, "overrides": {}},
        {"version": SCHEMA_VERSION, "overrides": ["ticket-1"]},
        _payload(_record(kind="urgent")),
        _payload(_record(status="done")),
        _payload(_record(override_id=1)),
        _payload(_record(target_id=None)),
        _payload(_record(reason=[])),
        _payload(_record(created_at=3)),
        _payload(_record(updated_at=False)),
        _payload({"override_id": "ticket-1", "kind": "pin"}),
        _payload({"target_id": "ticket-1", "kind": "pin"}),
        _payload({"override_id": "ticket-1", "target_id": "ticket-1"}),
    ],
)
def test_read_override_records_raises_on_a_wrong_shape(tmp_path: Path, payload: object) -> None:
    _write_overrides(tmp_path, payload)

    with pytest.raises(ValueError):
        read_override_records(tmp_path / "runtime")


def test_read_overrides_returns_empty_when_absent(tmp_path: Path) -> None:
    assert read_overrides(tmp_path / "runtime") == ()


def test_read_overrides_returns_only_active_records_in_the_ranker_shape(tmp_path: Path) -> None:
    _write_overrides(
        tmp_path,
        _payload(
            _record(),
            _record(
                override_id="ticket-2",
                target_id="ticket-2",
                kind="focus_today",
                status="cleared",
                updated_at=NOW,
            ),
        ),
    )

    overrides = read_overrides(tmp_path / "runtime")

    assert overrides == (Override("ticket-1", "ticket-1", "pin", "the exec asked"),)
    assert isinstance(overrides[0], Override)
