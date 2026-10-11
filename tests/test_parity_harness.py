"""Release/cutover ticket 03: the read-only old-vs-new parity harness."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("parity", REPO / "scripts" / "parity.py")
assert _SPEC and _SPEC.loader
parity = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(parity)

SPEC = {
    "hints": [{"project_id": "alpha"}, {"project_id": "ghost"}],
    "queries": [{"label": "login/global", "query": "login", "project_id": None}],
    "staleness": [{"project_id": "alpha"}],
    "project_ids": ["alpha"],
}


def _seed(vault: Path, write_note) -> None:  # noqa: ANN001
    write_note(
        vault,
        "9. Project/Project - Alpha.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        "project_id: alpha\naliases:\n  - Alpha Programme\n---\n# Project - Alpha\n",
    )
    write_note(
        vault,
        "Tickets/Issue - login fails.md",
        '---\ntype: ticket\nstatus: open\nproject: "[[Project - Alpha]]"\n---\n# Login fails\n',
    )


def test_read_capabilities_compare_as_parity(vault: Path, write_note, tmp_path: Path) -> None:  # noqa: ANN001
    _seed(vault, write_note)
    payload = parity.run_new(vault, tmp_path / "new.sqlite3", SPEC)
    report = parity.compare(payload, payload)
    assert report["parity_pass"] is True
    assert payload["authoritative"]["alpha"] == ["Tickets/Issue - login fails.md"]


def test_compare_fails_on_injected_truth_safety_difference(vault: Path, write_note, tmp_path: Path) -> None:  # noqa: ANN001
    _seed(vault, write_note)
    payload = parity.run_new(vault, tmp_path / "new.sqlite3", SPEC)
    corrupted = copy.deepcopy(payload)
    corrupted["authoritative"]["alpha"].append("Ghost.md")
    report = parity.compare(payload, corrupted)
    assert report["parity_pass"] is False


def test_harness_is_read_only_over_the_vault(vault: Path, write_note, tmp_path: Path) -> None:  # noqa: ANN001
    _seed(vault, write_note)
    before = {path: path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    parity.run_new(vault, tmp_path / "new.sqlite3", SPEC)
    after = {path: path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    assert after == before
