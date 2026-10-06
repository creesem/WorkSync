"""Ticket 08: the ``worksync activity`` surface over the derived log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.safety.activity import append_event


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "var"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "worksync.json"
    config.write_text(json.dumps({"vault_path": str(vault), "runtime_root": str(runtime)}), encoding="utf-8")
    monkeypatch.setenv("WORKSYNC_CONFIG", str(config))
    return runtime


def test_activity_lists_recorded_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    runtime = _configure(tmp_path, monkeypatch)
    append_event(runtime, {"type": "write", "verb": "update_status", "result": "ok", "reason": "promoted"})
    append_event(runtime, {"type": "system", "summary": "index built"})

    assert main(["activity", "--json"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert events[0]["verb"] == "update_status"
    assert events[1]["summary"] == "index built"


def test_activity_with_no_events_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _configure(tmp_path, monkeypatch)
    assert main(["activity"]) == 0
    assert capsys.readouterr().out == ""
