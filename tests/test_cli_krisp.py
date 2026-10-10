"""Ticket 02: the ``worksync krisp pull`` CLI seam."""

from __future__ import annotations

import json
from pathlib import Path

from worksync.cli.main import main
from worksync.ingest.krisp import KrispMeeting, MeetingStub


class FakeKrispClient:
    def __init__(self, meeting: KrispMeeting) -> None:
        self._meeting = meeting

    def list_meetings(self, *, since_days: int, limit: int | None = None) -> tuple[MeetingStub, ...]:
        return (MeetingStub(self._meeting.meeting_id, self._meeting.title, self._meeting.started_at),)

    def get_meeting(self, meeting_id: str) -> KrispMeeting:
        return self._meeting


def _meeting() -> KrispMeeting:
    return KrispMeeting(
        meeting_id="a1b2c3d4e5f6",
        title="Q3 Sync",
        started_at="2026-10-07T14:00:00Z",
        duration_seconds=60,
        source="krisp",
        tags=("sync",),
        speakers=(),
        segments=({"speaker": "Myles Creese", "start": 0, "end": 4, "text": "Hello"},),
        notes={"blocks": []},
    )


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
    monkeypatch.setattr("worksync.cli.main.build_krisp_client", lambda key, **kw: FakeKrispClient(_meeting()))
    code = main(["krisp", "pull", "--runtime", str(tmp_path / "var"), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pulled"] == ["a1b2c3d4e5f6"]


def test_cli_krisp_pull_accepts_a_vault_override(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _write_config(tmp_path)
    monkeypatch.setenv("WORKSYNC_CONFIG", str(config))
    monkeypatch.setenv("KRISP_API_KEY", "test-key")
    monkeypatch.setattr("worksync.cli.main.build_krisp_client", lambda key, **kw: FakeKrispClient(_meeting()))
    code = main(["krisp", "pull", "--vault", str(tmp_path / "vault"), "--runtime", str(tmp_path / "var"), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pulled"] == ["a1b2c3d4e5f6"]
