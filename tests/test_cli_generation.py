"""The work-generation CLI: cut over and reset the legacy boundary."""

from __future__ import annotations

import json
from pathlib import Path

from prioritization_fakes import action_note
from worksync.cli.main import main
from worksync.work.generation import read_generation


def test_cli_cutover_and_reset(vault: Path, write_note, tmp_path: Path, capsys) -> None:
    runtime = tmp_path / "runtime"
    write_note(vault, "Actions/One.md", action_note("type: action\nstatus: open\naction_id: a-1\n", "# One"))

    code = main(
        [
            "work",
            "cutover",
            "--reason",
            "Start clean",
            "--reviewer",
            "Myles",
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
    assert payload["generation"] == 2
    assert payload["legacy_action_count"] == 1
    assert payload["legacy_ticket_count"] == 0
    assert read_generation(runtime).generation == 2

    code = main(
        [
            "work",
            "reset-generation",
            "--reason",
            "Restore legacy work",
            "--reviewer",
            "Myles",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
        ]
    )

    assert code == 0
    assert "legacy work restored" in capsys.readouterr().out
    assert read_generation(runtime).generation == 1


def test_cli_cutover_refuses_a_second_boundary(vault: Path, write_note, tmp_path: Path, capsys) -> None:
    runtime = tmp_path / "runtime"
    write_note(vault, "Actions/One.md", action_note("type: action\nstatus: open\naction_id: a-1\n", "# One"))
    common = [
        "--reason",
        "Start clean",
        "--reviewer",
        "Myles",
        "--vault",
        str(vault),
        "--runtime",
        str(runtime),
    ]
    assert main(["work", "cutover", *common]) == 0
    capsys.readouterr()

    code = main(["work", "cutover", *common])

    assert code == 1
    assert "already_cut_over" in capsys.readouterr().err
