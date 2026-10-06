"""Tickets 02 and 06: the ``worksync index`` and ``worksync search`` CLI commands."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from worksync.cli.main import main


def test_index_then_search_json(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    write_note(vault, "10. Meetings/Alpha.md", "---\ntype: meeting\n---\n# Alpha\nMYPAC rollout\n")
    db = tmp_path / "index.sqlite3"

    assert main(["index", "--vault", str(vault), "--db", str(db)]) == 0
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["inserted"] == 1
    assert db.is_file()

    assert main(["search", "MYPAC", "--vault", str(vault), "--db", str(db), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["results"][0]["path"] == "10. Meetings/Alpha.md"


def test_search_reports_provenance_and_project_scope(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Eleos.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: eleos\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        "10. Meetings/M1.md",
        '---\ntype: meeting\nproject: "[[Project - Eleos]]"\n---\n# M1\nMYPAC rollout\n',
    )
    write_note(vault, "Notes/Other.md", "---\ntype: reference\n---\n# Other\nMYPAC elsewhere\n")
    db = tmp_path / "index.sqlite3"
    assert main(["index", "--vault", str(vault), "--db", str(db)]) == 0
    capsys.readouterr()

    assert main(["search", "MYPAC", "--project", "eleos", "--vault", str(vault), "--db", str(db), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["path"] for item in payload["results"]] == ["10. Meetings/M1.md"]
    assert payload["results"][0]["association"]["tier"] == "A"

    assert main(["search", "MYPAC", "--vault", str(vault), "--db", str(db), "--json"]) == 0
    by_path = {item["path"]: item for item in json.loads(capsys.readouterr().out)["results"]}
    assert by_path["Notes/Other.md"]["association"] == {"method": None, "authority": "candidate", "tier": "B"}


def test_search_missing_index_errors(vault: Path, tmp_path: Path, capsys) -> None:
    db = tmp_path / "missing.sqlite3"
    assert main(["search", "anything", "--vault", str(vault), "--db", str(db), "--json"]) == 2
    assert "Index not found" in capsys.readouterr().err


def test_index_missing_vault_errors(tmp_path: Path, capsys) -> None:
    db = tmp_path / "index.sqlite3"
    missing = tmp_path / "nope"
    assert main(["index", "--vault", str(missing), "--db", str(db)]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_index_requires_config_when_paths_omitted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("WORKSYNC_CONFIG", str(tmp_path / "config" / "worksync.json"))
    assert main(["index"]) == 2
    assert "worksync.json" in capsys.readouterr().err
