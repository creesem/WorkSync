"""Release/cutover ticket 02: portable wheel distribution and Windows launchers."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = ("Bootstrap.cmd", "Start-WorkSync.cmd", "worksync.cmd")


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_wheels_directory_is_gitignored() -> None:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "wheels/" in lines
    assert ".venv/" in lines


def test_launchers_exist() -> None:
    for name in LAUNCHERS:
        assert (ROOT / name).is_file(), name


def test_start_launcher_opens_the_gui_entry_point() -> None:
    assert "worksync-gui" in _text("Start-WorkSync.cmd")


def test_cli_launcher_passes_arguments_through() -> None:
    text = _text("worksync.cmd")
    assert "worksync" in text
    assert "%*" in text


def test_bootstrap_builds_the_wheel_when_absent_then_installs() -> None:
    text = _text("Bootstrap.cmd")
    assert "wheels" in text
    assert "wheel" in text.lower()
    assert "pip install" in text
    assert ".venv" in text


def test_launchers_carry_no_committed_absolute_path() -> None:
    for name in LAUNCHERS:
        text = _text(name)
        assert ":\\" not in text, f"{name} hardcodes a drive path"
        assert "C:\\" not in text, f"{name} hardcodes an absolute path"
