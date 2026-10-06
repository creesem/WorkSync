"""Ticket 03: entity list/show and the health CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "9. Project/Alpha.md",
        '---\ntype: project\nstatus: active\nproject_id: alpha\nowners:\n  - "[[Myles]]"\n'
        "priority: P1\n---\n# Project Alpha\n",
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def test_project_list_json(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["project", "list", "--vault", str(vault), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["title"] for item in payload] == ["Project Alpha"]


def test_project_show_json(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["project", "show", "Project Alpha", "--vault", str(vault), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "project"
    assert payload["priority"] == "P1"
    assert payload["issues"] == []


def test_show_missing_entity_returns_one(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    assert main(["person", "show", "Nobody", "--vault", str(vault)]) == 1


def test_list_excludes_error_entities(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    write_note(vault, "bad.md", "---\ntype: project\nstatus: active\nowners: []\n---\n# Bad\n")
    assert main(["project", "list", "--vault", str(vault), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_health_json_lists_findings(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    write_note(vault, "bad.md", "---\ntype: project\nstatus: active\nowners: []\n---\n# Bad\n")
    assert main(["health", "--vault", str(vault), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["errors"] >= 1
    assert report["counts"]["project"] == 1
    assert any(issue["path"] == "bad.md" for issue in report["issues"])
