"""Ticket 01: the three console entry points are declared and importable."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "worksync": "worksync.cli.main:main",
    "worksync-gui": "worksync.gui.main:main",
    "worksync-mcp": "worksync.mcp.main:main",
}


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_console_scripts_are_declared() -> None:
    assert _pyproject()["project"]["scripts"] == EXPECTED


def test_pyyaml_dependency_is_declared() -> None:
    dependencies = _pyproject()["project"]["dependencies"]
    assert any(dep.lower().startswith("pyyaml") for dep in dependencies)


def test_each_entry_point_callable_imports() -> None:
    for target in EXPECTED.values():
        module_name, func_name = target.split(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func_name))
