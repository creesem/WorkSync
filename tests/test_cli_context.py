"""Ticket 07: ``worksync context read`` and ``worksync context staleness``."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main

PROJECT_NOTE = "9. Project/Project - Eleos.md"
MEETING_NOTE = "10. Meetings/2026-01-01 Kickoff.md"
GENERATED_AT = "2026-09-20T10:00:00+00:00"


def _seed(vault: Path, write_note: Callable[..., Path], repo: Path) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        f'project_id: eleos\nrepos:\n  - "{repo.as_posix()}"\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        MEETING_NOTE,
        '---\ntype: meeting\ndate: 2026-01-01\nproject: "[[Project - Eleos]]"\n---\n# Kickoff\n',
    )


def _write_projection(repo: Path, sources: dict[str, str]) -> None:
    output = repo / ".project"
    output.mkdir(parents=True, exist_ok=True)
    lines = [
        "# WorkSync Project Context — Eleos",
        "",
        f"Generated: {GENERATED_AT}",
        "",
        "## Current State",
        "",
        "Working.",
        "",
        f"<!-- worksync-sources: {json.dumps(sources)} -->",
        "",
    ]
    (output / "WORKSYNC_CONTEXT.md").write_text("\n".join(lines), encoding="utf-8")


def _build(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    _seed(vault, write_note, repo)
    db = tmp_path / "index.sqlite3"
    assert main(["index", "--vault", str(vault), "--db", str(db)]) == 0
    capsys.readouterr()
    return repo, db


def test_context_read_json(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    repo, db = _build(vault, write_note, tmp_path, capsys)
    _write_projection(repo, {MEETING_NOTE: hashlib.sha256((vault / MEETING_NOTE).read_bytes()).hexdigest()})

    assert (
        main(
            [
                "context",
                "read",
                "--project-id",
                "eleos",
                "--vault",
                str(vault),
                "--db",
                str(db),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "ok"
    assert payload["generated_at"] == GENERATED_AT
    assert payload["truncated"] is False
    assert payload["stale"] is False
    assert "Working." in payload["content"]


def test_context_read_not_built_exits_one(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _repo, db = _build(vault, write_note, tmp_path, capsys)
    assert main(["context", "read", "--project-id", "eleos", "--vault", str(vault), "--db", str(db)]) == 1
    assert "context_not_built" in capsys.readouterr().out


def test_context_staleness_fresh_then_stale(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    repo, db = _build(vault, write_note, tmp_path, capsys)
    _write_projection(repo, {MEETING_NOTE: hashlib.sha256((vault / MEETING_NOTE).read_bytes()).hexdigest()})

    assert (
        main(["context", "staleness", "--project-id", "eleos", "--vault", str(vault), "--db", str(db), "--json"]) == 0
    )
    assert json.loads(capsys.readouterr().out) == {"project_id": "eleos", "fresh": True, "reasons": []}

    meeting = vault / MEETING_NOTE
    meeting.write_text(meeting.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")
    assert (
        main(["context", "staleness", "--project-id", "eleos", "--vault", str(vault), "--db", str(db), "--json"]) == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["fresh"] is False
    assert payload["reasons"] == ["source_hash_changed"]


def test_context_staleness_unknown_project_exits_one(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _repo, db = _build(vault, write_note, tmp_path, capsys)
    assert main(["context", "staleness", "--project-id", "missing", "--vault", str(vault), "--db", str(db)]) == 1
    assert "not_found" in capsys.readouterr().out
