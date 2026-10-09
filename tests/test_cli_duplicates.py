"""Spec 7 ticket 02: the `worksync duplicates` CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main
from worksync.safety.zones import staging_root
from worksync.work.duplicates import MANIFEST_REL

ACTIVE = "7. Task Notes/Active"


def _action(write_note: Callable[..., Path], vault: Path, name: str, title: str, *, status: str = "open") -> Path:
    text = f"---\ntype: action\nstatus: {status}\n---\n# {title}\n"
    return write_note(vault, f"{ACTIVE}/{name}.md", text)


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about the invoice")


def test_cli_duplicates_scan_and_dismiss(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]

    assert main(["duplicates", "scan", *base, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["proposals"]) == 1
    assert payload["proposals"][0]["action"] == "merge"
    proposal_id = payload["proposals"][0]["id"]

    assert (
        main(["duplicates", "dismiss", proposal_id, *base, "--reason", "keep both", "--reviewer", "Myles", "--json"])
        == 0
    )
    dismissed = json.loads(capsys.readouterr().out)
    assert dismissed["proposals"][0]["status"] == "dismissed"


def test_cli_duplicates_scan_dry_run_does_not_persist(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]

    assert main(["duplicates", "scan", *base, "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["proposals"]) == 1
    assert not (staging_root(runtime) / MANIFEST_REL).exists()


def test_cli_duplicates_dismiss_without_reviewer_fails(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]
    main(["duplicates", "scan", *base, "--json"])
    capsys.readouterr()
    # A fresh runtime has no remembered reviewer and no configured reviewer.
    assert main(["duplicates", "dismiss", "deadbeef", *base, "--reason", "why"]) == 1


def test_cli_duplicates_apply_merges(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]
    main(["duplicates", "scan", *base, "--json"])
    capsys.readouterr()

    assert (
        main(["duplicates", "apply", *base, "--reason", "Duplicate", "--reviewer", "Myles", "--confirm", "--json"]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert payload["applied"]
    rendered = {path.name: path.read_text(encoding="utf-8") for path in (vault / ACTIVE).glob("*.md")}
    assert any("type: redirect" in text for text in rendered.values())
