"""Spec 9 ticket 10: one-shot, fail-closed migration of legacy lifecycle state."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.lifecycle.migrate_legacy import (
    LegacyMigrationError,
    map_date_state,
    map_issue_state,
    map_report_state,
    map_waiting_lane,
    migrate_legacy,
)
from worksync.work.lifecycle.registry import LifecycleStore

TODAY = date(2026, 10, 10)
PROJECT = "9. Project/Project - Eleos.md"
LEGACY_DIR = "9. Project/Project - Eleos"
TICKET = "Tickets/Issue - Login fails.md"
REPORT = "Tickets/Report - Build 42.md"
ACTION = "7. Task Notes/Active/Chase the vendor.md"
WAITING_ACTION = "7. Task Notes/Active/Wait on finance.md"


def _seed(write_note: Callable[..., Path], vault: Path) -> None:
    write_note(
        vault,
        PROJECT,
        '---\ntype: project\nstatus: active\nproject_id: eleos\nowners:\n  - "[[Myles]]"\n---\n# Project - Eleos\n',
    )
    write_note(vault, TICKET, "---\ntype: ticket\nstatus: open\n---\n# Issue - Login fails\n")
    write_note(vault, REPORT, "---\ntype: ticket\nstatus: open\n---\n# Report - Build 42\n")
    write_note(vault, ACTION, "---\ntype: action\nstatus: waiting\n---\n# Chase the vendor\n")
    write_note(vault, WAITING_ACTION, "---\ntype: action\nstatus: waiting\n---\n# Wait on finance\n")


def _legacy_registries(write_note: Callable[..., Path], vault: Path) -> None:
    write_note(
        vault,
        f"{LEGACY_DIR}/issue-registry.json",
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-10-01T00:00:00+00:00",
                "issues": {
                    TICKET: {
                        "lifecycle_state": "confirmed",
                        "transitions": [
                            {"from": "reported", "to": "confirmed", "by": "Myles", "at": "2026-10-01T00:00:00+00:00"}
                        ],
                    }
                },
            }
        ),
    )
    write_note(
        vault,
        f"{LEGACY_DIR}/delivery-registry.json",
        json.dumps(
            {
                "version": 1,
                "reports": {REPORT: {"lifecycle_state": "testing", "transitions": []}},
                "date_gaps": {ACTION: {"lifecycle_state": "date_provided", "transitions": [], "date": "2026-11-01"}},
                "waiting": {WAITING_ACTION: {"lane": "business_acceptance", "status": "open", "transitions": []}},
                "communications": {},
                "update_reviews": {},
            }
        ),
    )


def test_each_legacy_state_maps() -> None:
    assert map_issue_state("confirmed") == "confirmed"
    assert map_issue_state("retesting") == "retesting"
    assert map_report_state("fix_reported") == "fix_reported"
    assert map_report_state("accepted_exception") == "accepted_exception"
    assert map_date_state("needs_date") == "needs-date"
    assert map_date_state("requested") == "needs-date"
    assert map_date_state("date_provided") == "conditional"
    assert map_date_state("confirmed") == "confirmed"
    assert map_waiting_lane("business_acceptance") == "business-acceptance"
    assert map_waiting_lane("external_dependency") == "external-dependency"
    assert map_waiting_lane("vendor") == "vendor"


def test_migration_imports_every_record_into_the_runtime_home(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    _legacy_registries(write_note, vault)
    runtime = tmp_path / "var"
    legacy_before = (vault / LEGACY_DIR / "issue-registry.json").read_text(encoding="utf-8")

    result = migrate_legacy(
        vault,
        runtime,
        "eleos",
        legacy_dir=vault / LEGACY_DIR,
        reviewer="Myles",
        reason="Cutover",
        today=TODAY,
    )

    assert result.committed is True
    registry = LifecycleStore(runtime, "eleos").load()
    assert registry is not None
    assert registry.entry(TICKET).record_kind == "issue"
    assert registry.entry(TICKET).lifecycle_state == "confirmed"
    assert registry.entry(TICKET).transitions[-1].actor == "Myles"
    assert registry.entry(REPORT).record_kind == "delivery"
    assert registry.entry(REPORT).lifecycle_state == "testing"
    assert registry.entry(ACTION).record_kind == "date_gap"
    assert registry.entry(ACTION).lifecycle_state == "conditional"
    assert registry.entry(WAITING_ACTION).record_kind == "waiting_on"
    assert registry.entry(WAITING_ACTION).lifecycle_state == "open"
    # The legacy vault sidecar is untouched.
    assert (vault / LEGACY_DIR / "issue-registry.json").read_text(encoding="utf-8") == legacy_before
    # The mapping is recorded on the entry provenance and in the journal.
    assert any("legacy" in item for item in registry.entry(TICKET).provenance)
    assert result.journal is not None and result.journal.is_file()


def test_unknown_state_aborts_with_no_writes(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    write_note(
        vault,
        f"{LEGACY_DIR}/issue-registry.json",
        json.dumps({"version": 1, "issues": {TICKET: {"lifecycle_state": "on_fire", "transitions": []}}}),
    )
    runtime = tmp_path / "var"

    with pytest.raises(LegacyMigrationError) as excinfo:
        migrate_legacy(
            vault, runtime, "eleos", legacy_dir=vault / LEGACY_DIR, reviewer="Myles", reason="x", today=TODAY
        )
    assert excinfo.value.code == "unmappable_state"
    assert LifecycleStore(runtime, "eleos").load() is None


def test_unknown_record_aborts_with_no_writes(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    write_note(
        vault,
        f"{LEGACY_DIR}/issue-registry.json",
        json.dumps({"version": 1, "issues": {"Tickets/Ghost.md": {"lifecycle_state": "confirmed", "transitions": []}}}),
    )
    runtime = tmp_path / "var"

    with pytest.raises(LegacyMigrationError) as excinfo:
        migrate_legacy(
            vault, runtime, "eleos", legacy_dir=vault / LEGACY_DIR, reviewer="Myles", reason="x", today=TODAY
        )
    assert excinfo.value.code == "unmappable_record"
    assert LifecycleStore(runtime, "eleos").load() is None


def test_invalid_waiting_status_aborts_with_no_writes(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    write_note(
        vault,
        f"{LEGACY_DIR}/delivery-registry.json",
        json.dumps({"version": 1, "waiting": {WAITING_ACTION: {"lane": "vendor", "status": "snoozing"}}}),
    )
    runtime = tmp_path / "var"

    with pytest.raises(LegacyMigrationError) as excinfo:
        migrate_legacy(
            vault, runtime, "eleos", legacy_dir=vault / LEGACY_DIR, reviewer="Myles", reason="x", today=TODAY
        )
    assert excinfo.value.code == "unmappable_state"
    assert LifecycleStore(runtime, "eleos").load() is None


def test_second_run_is_a_no_op(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    _legacy_registries(write_note, vault)
    runtime = tmp_path / "var"
    migrate_legacy(vault, runtime, "eleos", legacy_dir=vault / LEGACY_DIR, reviewer="Myles", reason="x", today=TODAY)
    before = LifecycleStore(runtime, "eleos").path().read_bytes()

    again = migrate_legacy(
        vault, runtime, "eleos", legacy_dir=vault / LEGACY_DIR, reviewer="Myles", reason="x", today=TODAY
    )

    assert again.changed is False
    assert LifecycleStore(runtime, "eleos").path().read_bytes() == before


def test_mid_run_failure_restores(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    _legacy_registries(write_note, vault)
    runtime = tmp_path / "var"
    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if path.name == "lifecycle.json":
            raise OSError("disk full")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        migrate_legacy(
            vault, runtime, "eleos", legacy_dir=vault / LEGACY_DIR, reviewer="Myles", reason="x", today=TODAY
        )

    assert excinfo.value.code == "rolled_back"
    assert LifecycleStore(runtime, "eleos").load() is None
