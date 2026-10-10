"""Ticket 02: the ``worksync krisp pull`` CLI seam."""

from __future__ import annotations

import json
from pathlib import Path

from krisp_fakes import FakeKrispClient
from krisp_fakes import meeting as _meeting
from worksync.cli.main import main


def _write_config(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "worksync.json"
    path.write_text(json.dumps({"vault_path": str(vault)}), encoding="utf-8")
    return path


def test_cli_krisp_pull_missing_key_fails_closed(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _write_config(tmp_path)
    monkeypatch.setenv("WORKSYNC_CONFIG", str(config))
    monkeypatch.delenv("KRISP_API_KEY", raising=False)
    code = main(["krisp", "pull", "--runtime", str(tmp_path / "var"), "--json"])
    assert code == 2
    assert "key" in capsys.readouterr().err.lower()


def test_cli_krisp_pull_succeeds_with_injected_client(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _write_config(tmp_path)
    monkeypatch.setenv("WORKSYNC_CONFIG", str(config))
    monkeypatch.setenv("KRISP_API_KEY", "test-key")
    monkeypatch.setattr("worksync.cli.main.build_client", lambda key, **kw: FakeKrispClient((_meeting(),)))
    code = main(["krisp", "pull", "--runtime", str(tmp_path / "var"), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pulled"] == ["a1b2c3d4e5f6"]


def test_cli_krisp_pull_accepts_a_vault_override(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _write_config(tmp_path)
    monkeypatch.setenv("WORKSYNC_CONFIG", str(config))
    monkeypatch.setenv("KRISP_API_KEY", "test-key")
    monkeypatch.setattr("worksync.cli.main.build_client", lambda key, **kw: FakeKrispClient((_meeting(),)))
    code = main(["krisp", "pull", "--vault", str(tmp_path / "vault"), "--runtime", str(tmp_path / "var"), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pulled"] == ["a1b2c3d4e5f6"]


def test_cli_krisp_pull_rebases_the_inbox_onto_the_runtime(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _write_config(tmp_path)
    monkeypatch.setenv("WORKSYNC_CONFIG", str(config))
    monkeypatch.setenv("KRISP_API_KEY", "test-key")
    monkeypatch.setattr("worksync.cli.main.build_client", lambda key, **kw: FakeKrispClient((_meeting(),)))
    runtime = tmp_path / "other-runtime"
    code = main(["krisp", "pull", "--runtime", str(runtime), "--json"])
    assert code == 0
    assert (runtime / "krisp" / "inbox" / "2026-10-07 - Q3 Sync [a1b2c3d4].txt").is_file()
    assert not (tmp_path / "var" / "krisp" / "inbox" / "2026-10-07 - Q3 Sync [a1b2c3d4].txt").exists()


def test_cli_ingest_scan_rebases_the_krisp_inbox_onto_the_runtime(tmp_path: Path, monkeypatch, capsys) -> None:
    vault = tmp_path / "vault"
    (vault / "7. Task Notes" / "Inbox").mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "worksync.json"
    config.write_text(json.dumps({"vault_path": str(vault)}), encoding="utf-8")
    monkeypatch.setenv("WORKSYNC_CONFIG", str(config))

    runtime = tmp_path / "other-runtime"
    inbox = runtime / "krisp" / "inbox"
    inbox.mkdir(parents=True)
    transcript = inbox / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    transcript.write_text("Myles Creese | 0:00\nHello\n", encoding="utf-8")
    (inbox / "2026-10-07 - Q3 Sync [a1b2c3d4].krisp.json").write_text(
        json.dumps(
            {
                "meeting_id": "a1b2c3d4e5f6",
                "title": "Q3 Sync",
                "started_at": "2026-10-07T14:00:00Z",
                "speakers": [],
                "segments": [],
                "notes": {"blocks": []},
            }
        ),
        encoding="utf-8",
    )
    code = main(["ingest", "scan", "--vault", str(vault), "--runtime", str(runtime), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(proposal["action"] == "meeting" for proposal in payload["proposals"])
