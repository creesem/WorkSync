"""Shared pytest fixtures for the WorkSync test suite."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root


@pytest.fixture
def write_note() -> Callable[[Path, str, str], Path]:
    def _write(vault: Path, relative: str, text: str) -> Path:
        path = vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    return _write
