"""Safety file primitives: atomic writes survive transient Windows sharing violations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from worksync.safety.files import REPLACE_RETRIES, atomic_write_bytes, atomic_write_text


def test_atomic_write_retries_a_transient_permission_error(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "job.json"
    real_replace = os.replace
    calls: list[tuple[str, str]] = []

    def flaky(source: str, destination: str) -> None:
        calls.append((source, destination))
        if len(calls) < 3:
            raise PermissionError(32, "The process cannot access the file")
        real_replace(source, destination)

    monkeypatch.setattr("worksync.safety.files.os.replace", flaky)

    atomic_write_text(target, '{"state": "ok"}')

    assert target.read_text(encoding="utf-8") == '{"state": "ok"}'
    assert len(calls) == 3


def test_atomic_write_still_raises_after_bounded_retries(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "job.json"
    calls: list[int] = []

    def locked(source: str, destination: str) -> None:
        calls.append(1)
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr("worksync.safety.files.os.replace", locked)
    monkeypatch.setattr("worksync.safety.files.time.sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        atomic_write_bytes(target, b"content")

    assert len(calls) == REPLACE_RETRIES
    assert list(tmp_path.glob(".worksync-*")) == []
