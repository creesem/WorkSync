"""Ticket 01: the ``worksync`` CLI and its config command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.cli.main import build_parser, main


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "worksync" in capsys.readouterr().out


def test_parser_declares_config_show() -> None:
    parser = build_parser()
    args = parser.parse_args(["config", "show"])
    assert args.handler is not None


def test_config_show_reports_resolved_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "worksync.json"
    config_path.write_text(json.dumps({"vault_path": str(vault), "ui_port": 9999}), encoding="utf-8")
    monkeypatch.setenv("WORKSYNC_CONFIG", str(config_path))

    assert main(["config", "show"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["vault_path"] == str(vault.resolve())
    assert payload["runtime_root"] == str((tmp_path / "var").resolve())
    assert payload["ui_port"] == 9999


def test_config_show_missing_config_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("WORKSYNC_CONFIG", str(tmp_path / "config" / "worksync.json"))
    assert main(["config", "show"]) == 2
    assert "worksync.json" in capsys.readouterr().err
