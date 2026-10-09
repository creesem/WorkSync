"""Spec 7 ticket 04: the `clarification` CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

from worksync.cli.main import main

TODAY = date(2026, 10, 6)
ACTIVE = "7. Task Notes/Active"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "9. Project/Project - Alpha.md", "---\ntype: project\nstatus: active\n---\n# Project - Alpha\n")
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(vault, f"{ACTIVE}/NoOwner.md", "---\ntype: action\nstatus: open\n---\n# Call the vendor\n")


def test_cli_clarification_scan_and_apply(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]

    assert main(["clarification", "scan", *base, "--today", TODAY.isoformat(), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["proposals"]) == 1
    proposal_id = payload["proposals"][0]["id"]

    override = {proposal_id: {"resolution": "archive"}}
    assert (
        main(
            [
                "clarification",
                "apply",
                *base,
                "--id",
                proposal_id,
                "--set",
                f"{proposal_id}={json.dumps(override[proposal_id])}",
                "--reason",
                "Not work",
                "--reviewer",
                "Myles",
                "--confirm",
                "--today",
                TODAY.isoformat(),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["committed"] is True
    assert "type: redirect" in (vault / ACTIVE / "NoOwner.md").read_text(encoding="utf-8")


def test_cli_clarification_reclassify(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]
    main(["clarification", "scan", *base, "--today", TODAY.isoformat(), "--json"])
    proposal_id = json.loads(capsys.readouterr().out)["proposals"][0]["id"]

    resolved = {
        "resolution": "reclassify",
        "project": "Project - Alpha",
        "owner": "Myles",
        "dependency": "Vendor response",
        "next_review": "2026-11-01",
    }
    assert (
        main(
            [
                "clarification",
                "apply",
                *base,
                "--id",
                proposal_id,
                "--set",
                f"{proposal_id}={json.dumps(resolved)}",
                "--reason",
                "Waiting on vendor",
                "--reviewer",
                "Myles",
                "--confirm",
                "--today",
                TODAY.isoformat(),
            ]
        )
        == 0
    )
    text = (vault / ACTIVE / "NoOwner.md").read_text(encoding="utf-8")
    assert "status: waiting" in text and "waiting_on: Vendor response" in text
