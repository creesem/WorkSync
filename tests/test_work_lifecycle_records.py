"""Spec 9 ticket 01: lifecycle record mapping and the derived registry home."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from worksync.work.lifecycle.loader import LifecycleRecord, load_project_records
from worksync.work.lifecycle.records import (
    DATE_FIELDS,
    ISSUE_FIELDS,
    RECORD_ENTITY_TYPE,
    WAITING_FIELDS,
    RecordKind,
    record_entity_type,
)
from worksync.work.lifecycle.registry import (
    LifecycleEntry,
    LifecycleRegistry,
    LifecycleStore,
    RegistryError,
    Transition,
    project_registry_dir,
    registry_path,
)
from worksync.work.repository import WorkIndex

PROJECT_NOTE = "9. Project/Project - Eleos.md"
TICKET_NOTE = "Tickets/Issue - Login fails.md"
ACTION_NOTE = "7. Task Notes/Active/Chase the vendor.md"


def _seed(write_note: Callable[..., Path], vault: Path) -> None:
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nproject_id: eleos\nowners:\n  - "[[Myles]]"\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        TICKET_NOTE,
        '---\ntype: ticket\nstatus: open\nproject: "[[Project - Eleos]]"\n---\n# Issue - Login fails\n',
    )
    write_note(
        vault,
        ACTION_NOTE,
        '---\ntype: action\nstatus: open\nproject: "[[Project - Eleos]]"\n---\n# Chase the vendor\n',
    )


def _registry(project_id: str = "eleos", *entries: LifecycleEntry) -> LifecycleRegistry:
    return LifecycleRegistry(project_id=project_id, records=tuple(entries))


def test_record_mapping_reuses_the_five_entities() -> None:
    assert RECORD_ENTITY_TYPE[RecordKind.ISSUE] == "ticket"
    assert RECORD_ENTITY_TYPE[RecordKind.DELIVERY] == "ticket"
    assert RECORD_ENTITY_TYPE[RecordKind.DATE_GAP] == "action"
    assert RECORD_ENTITY_TYPE[RecordKind.WAITING_ON] == "action"
    assert RECORD_ENTITY_TYPE[RecordKind.DECISION] == "meeting"
    assert record_entity_type("issue") == "ticket"
    assert record_entity_type("date_gap") == "action"


def test_record_entity_type_rejects_an_unknown_kind() -> None:
    with pytest.raises(RegistryError) as excinfo:
        record_entity_type("saga")
    assert excinfo.value.code == "unknown_record_kind"


def test_new_frontmatter_fields_are_declared() -> None:
    assert "date_class" in DATE_FIELDS
    assert "date_previous" in DATE_FIELDS
    assert "waiting_on_lane" in WAITING_FIELDS
    assert "waiting_on_review" in WAITING_FIELDS
    assert ISSUE_FIELDS


def test_registry_path_lives_under_the_runtime_project_zone(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    assert project_registry_dir(runtime, "eleos") == (runtime / "project" / "eleos").resolve()
    assert registry_path(runtime, "eleos") == (runtime / "project" / "eleos" / "lifecycle.json").resolve()


def test_registry_rejects_an_unsafe_project_id(tmp_path: Path) -> None:
    with pytest.raises(RegistryError) as excinfo:
        registry_path(tmp_path / "var", "../escape")
    assert excinfo.value.code == "invalid_project_id"


def test_registry_round_trips_with_transitions(tmp_path: Path) -> None:
    entry = LifecycleEntry(
        record_id=TICKET_NOTE,
        record_kind=RecordKind.ISSUE,
        lifecycle_state="confirmed",
        provenance=("meeting 2026-10-01",),
        transitions=(
            Transition(
                at="2026-10-01T10:00:00+00:00",
                actor="Myles",
                reason="Reproduced",
                from_state="reported",
                to_state="confirmed",
                evidence="[[Meeting - Triage]]",
            ),
        ),
    )
    registry = _registry("eleos", entry)
    store = LifecycleStore(tmp_path / "var", "eleos")
    store.save(registry, expected_absent=True)

    loaded = store.load()

    assert loaded == registry
    assert store.load_with_hash() is not None


def test_registry_save_is_stale_safe(tmp_path: Path) -> None:
    store = LifecycleStore(tmp_path / "var", "eleos")
    store.save(_registry("eleos"), expected_absent=True)
    current = store.sha256()
    assert current is not None

    with pytest.raises(RuntimeError):
        store.save(_registry("eleos"), expected="deadbeef")

    store.save(_registry("eleos"), expected=current)


def test_registry_op_is_a_runtime_operation(tmp_path: Path) -> None:
    store = LifecycleStore(tmp_path / "var", "eleos")
    op = store.registry_op(_registry("eleos"), expected="abc")
    assert op.zone == "runtime"
    assert op.path == Path("project") / "eleos" / "lifecycle.json"
    assert op.expected == "abc"


def test_loader_joins_canonical_records_with_the_registry(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    index = WorkIndex.from_vault(vault)
    registry = _registry(
        "eleos",
        LifecycleEntry(record_id=TICKET_NOTE, record_kind=RecordKind.ISSUE, lifecycle_state="reported"),
        LifecycleEntry(record_id=ACTION_NOTE, record_kind=RecordKind.WAITING_ON, lifecycle_state="vendor"),
    )

    records = load_project_records(index, registry)

    by_id = {record.record_id: record for record in records}
    assert isinstance(by_id[TICKET_NOTE], LifecycleRecord)
    assert by_id[TICKET_NOTE].entity.title == "Issue - Login fails"
    assert by_id[ACTION_NOTE].state == "vendor"


def test_loader_is_deterministically_ordered(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    index = WorkIndex.from_vault(vault)
    registry = _registry(
        "eleos",
        LifecycleEntry(record_id=ACTION_NOTE, record_kind=RecordKind.WAITING_ON, lifecycle_state="vendor"),
        LifecycleEntry(record_id=TICKET_NOTE, record_kind=RecordKind.ISSUE, lifecycle_state="reported"),
    )

    first = [record.record_id for record in load_project_records(index, registry)]
    second = [record.record_id for record in load_project_records(index, registry)]

    assert first == second


def test_loader_fails_closed_on_unknown_record(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    index = WorkIndex.from_vault(vault)
    registry = _registry(
        "eleos",
        LifecycleEntry(record_id="Tickets/Missing.md", record_kind=RecordKind.ISSUE, lifecycle_state="reported"),
    )

    with pytest.raises(RegistryError) as excinfo:
        load_project_records(index, registry)
    assert excinfo.value.code == "unknown_record"


def test_loader_fails_closed_on_unknown_project(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    index = WorkIndex.from_vault(vault)

    with pytest.raises(RegistryError) as excinfo:
        load_project_records(index, _registry("ghost"))
    assert excinfo.value.code == "unknown_project"
