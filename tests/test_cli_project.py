"""Ticket 05: project resolve/list and membership through the CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Eleos Automation.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        "project_id: eleos-automation\naliases:\n  - Eleos Automation Service\n"
        'repos:\n  - "C:/repos/eleos"\n---\n# Project - Eleos Automation\n',
    )


def test_project_list_reports_identity(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["project", "list", "--vault", str(vault), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    item = payload[0]
    assert item["project_id"] == "eleos-automation"
    assert item["name"] == "Eleos Automation"
    assert item["registered_repo"] == "C:/repos/eleos"
    assert item["context_available"] is False


def test_project_resolve_by_name_and_repo(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["project", "resolve", "--name", "Eleos Automation", "--vault", str(vault), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "resolved", "project_id": "eleos-automation"}

    assert main(["project", "resolve", "--cwd", "C:/repos/eleos/src", "--vault", str(vault), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "resolved"


def test_project_resolve_not_found_exits_one(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["project", "resolve", "--name", "Missing", "--vault", str(vault)]) == 1
    assert "not_found" in capsys.readouterr().out


def test_project_resolve_requires_a_hint(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["project", "resolve", "--vault", str(vault)]) == 2
    assert "provide at least one" in capsys.readouterr().err


def test_index_materializes_membership(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nproject: "[[Project - Eleos Automation]]"\n---\n# A1\n',
    )
    db = tmp_path / "index.sqlite3"
    assert main(["index", "--vault", str(vault), "--db", str(db)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["links"] == 1
