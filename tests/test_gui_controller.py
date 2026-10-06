"""Ticket 11: the read-only GUI controller maps one-to-one onto the retrieval service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from worksync.context import service
from worksync.context.association import index_associations
from worksync.gui.controller import GuiService
from worksync.inventory.index import index_vault

TODAY = date(2026, 2, 1)
PROJECT_NOTE = "9. Project/Project - Alpha.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: alpha\n'
        "next_review: 2026-01-10\nlast_reviewed: 2026-01-01\n---\n# Project - Alpha\n",
    )
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\n'
        'project: "[[Project - Alpha]]"\ndue: 2026-01-05\n---\n# Action One\n',
    )
    write_note(vault, "Tickets/T1.md", "---\ntype: ticket\nstatus: in_progress\nmanager_attention: true\n---\n# T1\n")


def _service(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> tuple[GuiService, Path]:
    _seed(vault, write_note)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    gui = GuiService(vault=vault, db_path=db, runtime_root=tmp_path / "var", vault_name="vault", reviewer="Myles")
    return gui, db


def test_today_and_review_carry_equivalent_cli_and_match_service(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    gui, _db = _service(vault, write_note, tmp_path)
    today = gui.today(TODAY)
    assert today["equivalent_cli"] == "worksync review today --today 2026-02-01"
    assert today["attention"] == service.attention(vault, TODAY)

    review = gui.review(TODAY)
    assert review["equivalent_cli"] == "worksync review projects --today 2026-02-01"
    assert review["projects"] == service.project_reviews(vault, TODAY)


def test_projects_board_and_detail(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    gui, db = _service(vault, write_note, tmp_path)
    board = gui.projects()
    assert board["equivalent_cli"] == "worksync project list"
    assert board["projects"] == service.list_projects(vault, db)

    detail = gui.project("Alpha", TODAY)
    assert detail["state"] == "ok"
    assert detail["equivalent_cli"] == "worksync review projects --today 2026-02-01 --project Alpha"
    assert detail["review"]["project"]["project_id"] == "alpha"

    assert gui.project("Missing", TODAY) == {
        "state": "not_found",
        "equivalent_cli": "worksync review projects --today 2026-02-01 --project Missing",
    }


def test_team_board_and_detail(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    gui, _db = _service(vault, write_note, tmp_path)
    board = gui.team(TODAY)
    assert board["equivalent_cli"] == "worksync review team --today 2026-02-01"
    assert [item["person"]["title"] for item in board["workloads"]] == ["Myles"]

    detail = gui.person("Myles", TODAY)
    assert detail["state"] == "ok"
    assert detail["equivalent_cli"] == "worksync review team --today 2026-02-01 --person Myles"
    assert detail["workload"]["person"]["title"] == "Myles"

    assert gui.person("Nobody", TODAY)["state"] == "not_found"


def test_tickets_search_and_settings(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    gui, _db = _service(vault, write_note, tmp_path)
    tickets = gui.tickets(TODAY)
    assert tickets["equivalent_cli"] == "worksync ticket list"
    assert [ticket["title"] for ticket in tickets["tickets"]] == ["T1"]
    assert all("attention" in ticket for ticket in tickets["tickets"])

    search = gui.search("Alpha", project_id="alpha")
    assert search["equivalent_cli"] == 'worksync search "Alpha" --project alpha'
    assert search["result"] == service.search_evidence(vault, gui.db_path, "Alpha", project_id="alpha")

    health = gui.health()
    assert health["equivalent_cli"] == "worksync health"
    assert health["errors"] == 0
    assert isinstance(health["issues"], list)

    settings = gui.settings()
    assert settings["equivalent_cli"] == "worksync config show"
    assert settings["index_present"] is True
    assert settings["reviewer"] == "Myles"
    assert settings["project_count"] == 1
    assert settings["errors"] == health["errors"]


def test_every_controller_payload_has_an_equivalent_command(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    gui, _db = _service(vault, write_note, tmp_path)
    payloads = [
        gui.today(TODAY),
        gui.review(TODAY),
        gui.projects(),
        gui.project("Alpha", TODAY),
        gui.team(TODAY),
        gui.person("Myles", TODAY),
        gui.tickets(TODAY),
        gui.search("Alpha"),
        gui.health(),
        gui.settings(),
    ]
    assert all(payload["equivalent_cli"].startswith("worksync ") for payload in payloads)
