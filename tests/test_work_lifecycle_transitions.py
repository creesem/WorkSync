"""Spec 9 ticket 08: lifecycle transitions are canonical writes through the gateway."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.cli.main import main as cli_main
from worksync.gui.actions import dispatch_action
from worksync.gui.controller import GuiService
from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.lifecycle.records import RegistryError
from worksync.work.lifecycle.registry import LifecycleEntry, LifecycleRegistry, LifecycleStore
from worksync.work.lifecycle.transitions import apply_lifecycle_transition
from worksync.work.lifecycle.waiting import WaitingError
from worksync.work.writer import complete_action

TODAY = date(2026, 10, 10)
PROJECT = "9. Project/Project - Eleos.md"
TICKET = "Tickets/Issue - Login fails.md"
ACTION = "7. Task Notes/Active/Chase the vendor.md"
MEETING = "10. Meetings/Weekly.md"


def _seed(write_note: Callable[..., Path], vault: Path) -> None:
    write_note(
        vault,
        PROJECT,
        '---\ntype: project\nstatus: active\nproject_id: eleos\nowners:\n  - "[[Myles]]"\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        TICKET,
        '---\ntype: ticket\nstatus: open\nproject: "[[Project - Eleos]]"\n---\n# Issue - Login fails\n',
    )
    write_note(
        vault,
        ACTION,
        '---\ntype: action\nstatus: open\nrevision: 1\nproject: "[[Project - Eleos]]"\n---\n# Chase the vendor\n',
    )


def _state(vault: Path, runtime: Path) -> dict[str, bytes]:
    return {path.as_posix(): path.read_bytes() for path in vault.rglob("*.md")}


def test_transition_writes_content_registry_backup_and_journal(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    before = (vault / TICKET).read_text(encoding="utf-8")

    result = apply_lifecycle_transition(
        vault,
        runtime,
        project_id="eleos",
        record_id=TICKET,
        kind="issue",
        action="confirm",
        actor="Myles",
        reason="Reproduced on staging",
        today=TODAY,
        fields={"status": "in_progress"},
    )

    assert result.committed is True
    assert result.from_state == "reported" and result.to_state == "confirmed"
    text = (vault / TICKET).read_text(encoding="utf-8")
    assert "status: in_progress" in text
    assert "updated_by: Myles" in text
    assert result.journal is not None and result.journal.is_file()

    registry = LifecycleStore(runtime, "eleos").load()
    assert registry is not None
    entry = registry.entry(TICKET)
    assert entry is not None and entry.lifecycle_state == "confirmed"
    assert entry.transitions[-1].from_state == "reported"
    assert entry.transitions[-1].actor == "Myles"

    backups = sorted((runtime / "backups").glob("backup-*/file-*"))
    assert any(backup.read_text(encoding="utf-8") == before for backup in backups)


def test_stale_sha_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    before = _state(vault, runtime)

    with pytest.raises(RegistryError) as excinfo:
        apply_lifecycle_transition(
            vault,
            runtime,
            project_id="eleos",
            record_id=TICKET,
            kind="issue",
            action="confirm",
            actor="Myles",
            reason="Reproduced",
            today=TODAY,
            target_sha="deadbeef",
        )
    assert excinfo.value.code == "stale_hash"
    assert _state(vault, runtime) == before
    assert LifecycleStore(runtime, "eleos").load() is None


def test_registry_failure_restores_the_record_and_leaves_the_transition_pending(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    before = _state(vault, runtime)
    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if path.name == "lifecycle.json":
            raise OSError("metadata write failed")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply_lifecycle_transition(
            vault,
            runtime,
            project_id="eleos",
            record_id=TICKET,
            kind="issue",
            action="confirm",
            actor="Myles",
            reason="Reproduced",
            today=TODAY,
            fields={"status": "in_progress"},
        )

    assert excinfo.value.code == "rolled_back"
    assert _state(vault, runtime) == before
    assert LifecycleStore(runtime, "eleos").load() is None


def test_illegal_transition_fails_closed_without_writing(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    before = _state(vault, runtime)

    with pytest.raises(Exception) as excinfo:
        apply_lifecycle_transition(
            vault,
            runtime,
            project_id="eleos",
            record_id=TICKET,
            kind="issue",
            action="verify",
            actor="Myles",
            reason="Looks fine",
            today=TODAY,
        )
    assert getattr(excinfo.value, "code", "") == "illegal_transition"
    assert _state(vault, runtime) == before


def test_quick_completion_remains_a_canonical_task_mutation(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    before = (vault / ACTION).read_text(encoding="utf-8")

    result = complete_action(vault, runtime, ACTION, reason="Done", reviewer="Myles", today=TODAY)

    assert result.committed is True
    assert "status: done" in (vault / ACTION).read_text(encoding="utf-8")
    backups = sorted((runtime / "backups").glob("backup-*/file-*"))
    assert any(backup.read_text(encoding="utf-8") == before for backup in backups)


def test_gui_action_and_cli_produce_the_same_transition(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    gui_runtime = tmp_path / "gui-var"
    service = GuiService(
        vault=vault,
        db_path=gui_runtime / "index.sqlite3",
        runtime_root=gui_runtime,
        vault_name="vault",
        reviewer="Myles",
    )
    gui = dispatch_action(
        service,
        "lifecycle-transition",
        {
            "project_id": "eleos",
            "record": TICKET,
            "kind": "issue",
            "action": "confirm",
            "reason": "Reproduced",
            "fields": {"status": "in_progress"},
        },
        today=TODAY,
    )
    assert gui["committed"] is True
    assert gui["equivalent_cli"].startswith("worksync project lifecycle")
    assert service.control_center("eleos", TODAY)["state"] == "ok"

    vault2 = tmp_path / "vault2"
    vault2.mkdir()
    _seed(write_note, vault2)
    cli_runtime = tmp_path / "cli-var"
    code = cli_main(
        [
            "project",
            "lifecycle",
            "--project-id",
            "eleos",
            "--record",
            TICKET,
            "--kind",
            "issue",
            "--action",
            "confirm",
            "--reason",
            "Reproduced",
            "--actor",
            "Myles",
            "--field",
            "status=in_progress",
            "--vault",
            str(vault2),
            "--runtime",
            str(cli_runtime),
            "--today",
            TODAY.isoformat(),
            "--json",
        ]
    )

    assert code == 0
    assert (vault2 / TICKET).read_text(encoding="utf-8") == (vault / TICKET).read_text(encoding="utf-8")
    gui_state = LifecycleStore(gui_runtime, "eleos").load()
    cli_state = LifecycleStore(cli_runtime, "eleos").load()
    assert gui_state is not None and cli_state is not None
    assert gui_state.entry(TICKET).lifecycle_state == "confirmed"
    assert cli_state.entry(TICKET).lifecycle_state == "confirmed"


def test_destructive_transition_requires_confirmation(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"

    with pytest.raises(MutationError) as excinfo:
        apply_lifecycle_transition(
            vault,
            runtime,
            project_id="eleos",
            record_id=TICKET,
            kind="issue",
            action="reject",
            actor="Myles",
            reason="Not a real defect",
            today=TODAY,
        )
    assert excinfo.value.code == "needs_confirmation"

    result = apply_lifecycle_transition(
        vault,
        runtime,
        project_id="eleos",
        record_id=TICKET,
        kind="issue",
        action="reject",
        actor="Myles",
        reason="Not a real defect",
        today=TODAY,
        confirmed=True,
    )
    assert result.committed is True and result.to_state == "rejected" and result.destructive is True


def test_unsupported_transition_kind_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    with pytest.raises(RegistryError) as excinfo:
        apply_lifecycle_transition(
            vault,
            tmp_path / "var",
            project_id="eleos",
            record_id=MEETING,
            kind="decision",
            action="confirm",
            actor="Myles",
            reason="Decided",
            today=TODAY,
        )
    assert excinfo.value.code == "unsupported_transition_kind"


def test_revising_a_missed_date_persists_previous_and_revised(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    LifecycleStore(runtime, "eleos").save(
        LifecycleRegistry(
            project_id="eleos",
            records=(LifecycleEntry(record_id=ACTION, record_kind="date_gap", lifecycle_state="stale-missed"),),
        ),
        expected_absent=True,
    )

    apply_lifecycle_transition(
        vault,
        runtime,
        project_id="eleos",
        record_id=ACTION,
        kind="date_gap",
        action="revise",
        actor="Myles",
        reason="Vendor slipped",
        today=TODAY,
        evidence={"previous": "2026-10-01", "revised": "2026-11-01", "source": "[[Meeting - Reset]]"},
    )

    text = (vault / ACTION).read_text(encoding="utf-8")
    assert "date_previous: 2026-10-01" in text
    assert "date_revised: 2026-11-01" in text
    assert "date_reason: Vendor slipped" in text


def test_waiting_on_requires_the_dependency_fields(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    with pytest.raises(WaitingError) as excinfo:
        apply_lifecycle_transition(
            vault,
            tmp_path / "var",
            project_id="eleos",
            record_id=ACTION,
            kind="waiting_on",
            action="resolve",
            actor="Myles",
            reason="Resolved",
            today=TODAY,
            evidence={"lane": "vendor", "owner": "Myles", "project": "Project - Eleos"},
        )
    assert excinfo.value.code == "missing_dependency"
