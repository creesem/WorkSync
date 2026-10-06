"""Ticket 04: review queues and related entities through the CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "9. Project/P.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        "next_review: 2026-01-10\nlast_reviewed: 2026-01-01\n---\n# Project Alpha\n",
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\n'
        'project: "[[Project Alpha]]"\ndue: 2026-01-05\n---\n# Action One\n',
    )


def test_review_today_json_is_deterministic(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    args = ["review", "today", "--vault", str(vault), "--today", "2026-01-15", "--json"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert first == second
    kinds = {item["kind"] for item in first}
    assert {"review_due", "overdue_action"} <= kinds
    assert all(item["reason"] for item in first)


def test_review_projects_json(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["review", "projects", "--vault", str(vault), "--today", "2026-01-15", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["project"]["title"] == "Project Alpha"
    assert payload[0]["actions"] == ["Action One"]


def test_review_team_json(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["review", "team", "--vault", str(vault), "--today", "2026-01-15", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["person"]["title"] == "Myles"


def test_project_show_includes_related(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["project", "show", "Project Alpha", "--vault", str(vault), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["related"]["people"] == ["Myles"]
    assert payload["related"]["actions"] == ["Action One"]


def test_review_rejects_invalid_today(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["review", "today", "--vault", str(vault), "--today", "not-a-date"]) == 2
    assert "invalid --today" in capsys.readouterr().err
