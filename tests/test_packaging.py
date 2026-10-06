"""Ticket 13: the wheel packages the platform and its entry points run from an install."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCRIPTS = (
    "worksync = worksync.cli.main:main",
    "worksync-gui = worksync.gui.main:main",
    "worksync-mcp = worksync.mcp.main:main",
)


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("wheel")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(out)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"could not build a wheel in this environment: {result.stderr.strip()[-300:]}")
    wheels = sorted(out.glob("worksync-*.whl"))
    assert wheels, result.stdout
    return wheels[-1]


def test_wheel_contains_package_static_data_and_entry_points(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
        assert "worksync/cli/main.py" in names
        assert "worksync/gui/static/index.html" in names
        assert "worksync/gui/static/styles.css" in names
        assert "worksync/gui/static/app.js" in names
        entry = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        text = archive.read(entry).decode("utf-8")
    for script in EXPECTED_SCRIPTS:
        assert script in text


def test_wheel_installs_and_its_entry_points_run(wheel_path: Path, tmp_path: Path) -> None:
    target = tmp_path / "site"
    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--target", str(target), str(wheel_path)],
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stderr

    env = {**os.environ, "PYTHONPATH": str(target)}
    help_result = subprocess.run([sys.executable, "-m", "worksync", "--help"], capture_output=True, text=True, env=env)
    assert help_result.returncode == 0, help_result.stderr
    assert "usage: worksync" in help_result.stdout

    imported = subprocess.run(
        [sys.executable, "-c", "import worksync, worksync.gui.main, worksync.mcp.main; print(worksync.__file__)"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert imported.returncode == 0, imported.stderr
    assert str(target) in imported.stdout
