"""Spec 9 ticket 06: the read-only project control center."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from worksync.work.control_center import build_control_center, render_control_center
from worksync.work.lifecycle.loader import load_project_records
from worksync.work.lifecycle.records import RecordKind
from worksync.work.lifecycle.registry import LifecycleEntry, LifecycleRegistry
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 10)
PROJECT = "9. Project/Project - Eleos.md"
TICKET = "Tickets/Issue - Login fails.md"
ACTION = "7. Task Notes/Active/Chase the vendor.md"
MEETING = "10. Meetings/2026-10-02 Weekly.md"
SECTIONS = {
    "project",
    "summary",
    "issues",
    "testing",
    "dates",
    "decisions",
    "communications",
    "waiting_on",
    "update_candidates",
    "health",
    "timeline",
}


def _seed(write_note: Callable[..., Path], vault: Path) -> None:
    write_note(
        vault,
        PROJECT,
        "---\ntype: project\nstatus: active\nproject_id: eleos\nnext_action: Decide the launch date\n"
        'owners:\n  - "[[Myles]]"\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        TICKET,
        '---\ntype: ticket\nstatus: open\nproject: "[[Project - Eleos]]"\n---\n# Issue - Login fails\n',
    )
    write_note(
        vault,
        ACTION,
        '---\ntype: action\nstatus: waiting\nwaiting_on_lane: vendor\nproject: "[[Project - Eleos]]"\n'
        "---\n# Chase the vendor\n",
    )
    write_note(
        vault,
        MEETING,
        '---\ntype: meeting\nstatus: held\ndate: 2026-10-02\nproject: "[[Project - Eleos]]"\n---\n# Weekly\n',
    )


def _registry() -> LifecycleRegistry:
    return LifecycleRegistry(
        project_id="eleos",
        records=(
            LifecycleEntry(record_id=TICKET, record_kind=RecordKind.ISSUE, lifecycle_state="reported"),
            LifecycleEntry(record_id=ACTION, record_kind=RecordKind.WAITING_ON, lifecycle_state="open"),
            LifecycleEntry(record_id=MEETING, record_kind=RecordKind.DECISION, lifecycle_state="decided"),
        ),
    )


def _report(vault: Path) -> dict:
    index = WorkIndex.from_vault(vault)
    project = index.get("project", "Project - Eleos")
    assert project is not None
    records = load_project_records(index, _registry())
    return build_control_center(index, project, records, today=TODAY)


def test_report_exposes_every_contract_section(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    assert set(_report(vault)) == SECTIONS


def test_report_leads_with_unresolved_outcomes_and_next_decision(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    summary = _report(vault)["summary"]
    assert summary["unresolved_outcomes"]
    assert summary["next_decision"] == "Decide the launch date"
    assert summary["counts"]["issues"] == 1


def test_report_preserves_links_to_authoritative_records(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    report = _report(vault)
    assert report["issues"][0]["path"] == TICKET
    assert report["waiting_on"][0]["path"] == ACTION
    assert report["decisions"][0]["path"] == MEETING


def test_report_is_deterministic(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    assert _report(vault) == _report(vault)


def test_report_never_writes(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    _report(vault)
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before


def test_render_control_center_is_text(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    rendered = render_control_center(_report(vault))
    assert "Project - Eleos" in rendered
    assert "Issue - Login fails" in rendered
