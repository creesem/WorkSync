"""Ticket 02: `worksync interface build` renders and gated-writes the interface."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main

GENERATED_AT = "2026-01-15T09:00:00+00:00"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "9. Project/Project - Eleos.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n---\n# Project Eleos\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def _base(vault: Path, runtime: Path) -> list[str]:
    return [
        "interface",
        "build",
        "--vault",
        str(vault),
        "--runtime",
        str(runtime),
        "--vault-name",
        "WorkSync",
        "--today",
        "2026-01-15",
        "--generated-at",
        GENERATED_AT,
    ]


def test_interface_build_writes_home_page(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    assert main([*_base(vault, runtime), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert payload["pages"] == ["index.html"]
    written = vault / "0. System" / "Interface" / "index.html"
    assert written.is_file()
    assert "obsidian://open?vault=WorkSync&amp;file=People/Myles" in written.read_text(encoding="utf-8")


def test_interface_build_dry_run_writes_nothing(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    assert main([*_base(vault, runtime), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is False
    assert not (vault / "0. System" / "Interface").exists()


def test_interface_build_refuses_to_overwrite_without_force(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    assert main(_base(vault, runtime)) == 0
    capsys.readouterr()
    assert main(_base(vault, runtime)) == 1
    assert "needs_confirmation" in capsys.readouterr().err
    assert main([*_base(vault, runtime), "--confirm", "--force"]) == 0


def test_interface_build_uses_the_configured_vault_name_by_default(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    args = [
        "interface",
        "build",
        "--vault",
        str(vault),
        "--runtime",
        str(runtime),
        "--today",
        "2026-01-15",
        "--generated-at",
        GENERATED_AT,
        "--json",
    ]
    assert main(args) == 0
    written = vault / "0. System" / "Interface" / "index.html"
    assert f"vault={vault.name}&amp;" in written.read_text(encoding="utf-8")
