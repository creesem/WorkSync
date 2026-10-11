"""Spec 3: the ``worksync task`` and ``worksync workday`` CLI seams."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main
from worksync.inventory.index import connect, index_path

TODAY = "2026-10-06"
A_PATH = "7. Task Notes/Active/Task One.md"

ACTION = (
    "---\n"
    "type: action\n"
    "status: open\n"
    "priority: P2\n"
    "owners:\n"
    '  - "[[Myles Creese]]"\n'
    'project: "[[Project - Alpha]]"\n'
    "due: 2026-10-01\n"
    "revision: 3\n"
    "---\n"
    "# Task One\n"
    "Body line\n"
)


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, A_PATH, ACTION)
    write_note(
        vault,
        "9. Project/Project - Alpha.md",
        '---\ntype: project\nstatus: active\nproject_id: alpha\nowners:\n  - "[[Myles]]"\n---\n# Project - Alpha\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def test_cli_task_update_dry_run_writes_nothing(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    code = main(
        [
            "task",
            "update",
            A_PATH,
            "--status",
            "in_progress",
            "--reason",
            "Start it",
            "--reviewer",
            "myles",
            "--dry-run",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is False
    assert (vault / A_PATH).read_text(encoding="utf-8") == ACTION
    assert not (runtime / "journal").exists()


def test_cli_task_update_commits_and_refreshes(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    code = main(
        [
            "task",
            "update",
            A_PATH,
            "--status",
            "in_progress",
            "--due",
            "2026-10-09",
            "--reason",
            "Reschedule",
            "--reviewer",
            "myles",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert payload["reviewer"] == "myles"
    assert "status: in_progress" in (vault / A_PATH).read_text(encoding="utf-8")
    assert index_path(runtime).is_file()
    con = connect(index_path(runtime))
    try:
        rows = con.execute("SELECT path FROM note_project_links WHERE project_id='alpha'").fetchall()
    finally:
        con.close()
    assert (A_PATH,) in rows


def test_cli_task_complete(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    code = main(
        [
            "task",
            "complete",
            A_PATH,
            "--reason",
            "Finished",
            "--reviewer",
            "myles",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
            "--json",
        ]
    )
    assert code == 0
    json.loads(capsys.readouterr().out)
    text = (vault / A_PATH).read_text(encoding="utf-8")
    assert "status: done" in text
    assert "completed:" in text


def test_cli_task_update_stale_sha_returns_one(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    code = main(
        [
            "task",
            "update",
            A_PATH,
            "--status",
            "in_progress",
            "--reason",
            "Start",
            "--reviewer",
            "myles",
            "--sha",
            "deadbeef",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
        ]
    )
    assert code == 1
    assert (vault / A_PATH).read_text(encoding="utf-8") == ACTION


def test_cli_reviewer_is_remembered(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    first = main(
        [
            "task",
            "update",
            A_PATH,
            "--status",
            "in_progress",
            "--reason",
            "Start",
            "--reviewer",
            "Myles Creese",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
        ]
    )
    assert first == 0
    assert (runtime / "reviewer.json").is_file()
    second = main(
        [
            "task",
            "update",
            A_PATH,
            "--status",
            "open",
            "--reason",
            "Reopen",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
        ]
    )
    assert second == 0


def test_cli_workday_set_then_show_round_trips(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    set_code = main(
        ["workday", "set", "must_win", A_PATH, "--vault", str(vault), "--runtime", str(runtime), "--today", TODAY]
    )
    assert set_code == 0
    capsys.readouterr()
    show_code = main(["workday", "show", "--vault", str(vault), "--runtime", str(runtime), "--today", TODAY, "--json"])
    assert show_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selections"]["must_win"]["path"] == A_PATH
    assert set(payload["suggestions"]) == {"must_win", "support_one", "support_two", "unblock", "quick_win"}


def test_cli_workday_complete_stale_sha_fails_closed(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    code = main(
        [
            "workday",
            "complete",
            A_PATH,
            "--sha",
            "deadbeef",
            "--reason",
            "Done",
            "--reviewer",
            "myles",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
            "--today",
            TODAY,
        ]
    )
    assert code == 1
    assert (vault / A_PATH).read_text(encoding="utf-8") == ACTION


def test_cli_workday_set_dry_run_writes_nothing(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    code = main(
        [
            "workday",
            "set",
            "must_win",
            A_PATH,
            "--dry-run",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
            "--today",
            TODAY,
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["selections"]["must_win"]["path"] == A_PATH
    assert not (runtime / "workday-plan.json").exists()


def test_cli_dry_run_does_not_remember_reviewer(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    code = main(
        [
            "task",
            "update",
            A_PATH,
            "--status",
            "in_progress",
            "--reason",
            "Start",
            "--reviewer",
            "Myles Creese",
            "--dry-run",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
        ]
    )
    assert code == 0
    assert not (runtime / "reviewer.json").exists()


def test_cli_workday_show_renders_suggestions_without_json(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    code = main(["workday", "show", "--vault", str(vault), "--runtime", str(runtime), "--today", TODAY])
    assert code == 0
    assert "Task One" in capsys.readouterr().out
