"""Spec 9 ticket 09: the weekly walkthrough is a reproducible generated artifact."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.safety.models import MutationError
from worksync.safety.zones import write_zones
from worksync.work.repository import WorkIndex
from worksync.work.walkthrough import WALKTHROUGH_FILENAME, build_walkthrough, write_walkthrough

TODAY = date(2026, 10, 10)
PROJECT = "9. Project/Project - Eleos.md"
ACTION = "7. Task Notes/Active/Chase the vendor.md"


def _seed(write_note: Callable[..., Path], vault: Path) -> None:
    write_note(
        vault,
        PROJECT,
        '---\ntype: project\nstatus: active\nproject_id: eleos\nowners:\n  - "[[Myles]]"\n---\n# Project - Eleos\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\nteam: Ops\n---\n# Myles\n")
    write_note(
        vault,
        ACTION,
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\nproject: "[[Project - Eleos]]"\n'
        "due: 2026-10-08\n---\n# Chase the vendor\n",
    )


def test_walkthrough_is_deterministic(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    index = WorkIndex.from_vault(vault)
    first = build_walkthrough(index, today=TODAY)
    second = build_walkthrough(index, today=TODAY)
    assert first.content == second.content
    assert first.filename == WALKTHROUGH_FILENAME


def test_walkthrough_carries_every_section(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    content = build_walkthrough(WorkIndex.from_vault(vault), today=TODAY).content
    for heading in (
        "Team updates",
        "Prior action items",
        "Operations",
        "Projects",
        "Waiting on",
        "Action items / deadlines",
    ):
        assert heading in content
    assert "Not recorded" not in content


def test_empty_vault_is_tolerated(tmp_path: Path) -> None:
    vault = tmp_path / "empty"
    vault.mkdir()
    walkthrough = build_walkthrough(WorkIndex.from_vault(vault), today=TODAY)
    assert walkthrough.content
    assert "Weekly walkthrough" in walkthrough.content


def test_write_creates_the_packet_in_the_generated_zone(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    walkthrough = build_walkthrough(WorkIndex.from_vault(vault), today=TODAY)
    zones = write_zones(vault, tmp_path / "var")

    result = write_walkthrough(walkthrough, zones, confirmed=True)

    assert result.committed is True
    written = zones["generated"] / WALKTHROUGH_FILENAME
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == walkthrough.content


def test_overwrite_requires_confirmation(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    walkthrough = build_walkthrough(WorkIndex.from_vault(vault), today=TODAY)
    zones = write_zones(vault, tmp_path / "var")
    write_walkthrough(walkthrough, zones, confirmed=True)
    before = (zones["generated"] / WALKTHROUGH_FILENAME).read_text(encoding="utf-8")

    with pytest.raises(MutationError) as excinfo:
        write_walkthrough(walkthrough, zones, confirmed=False)
    assert excinfo.value.code == "needs_confirmation"
    assert (zones["generated"] / WALKTHROUGH_FILENAME).read_text(encoding="utf-8") == before

    assert write_walkthrough(walkthrough, zones, confirmed=True, force=True).committed is True


def test_write_refuses_containment_escape(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    walkthrough = build_walkthrough(WorkIndex.from_vault(vault), today=TODAY)
    zones = write_zones(vault, tmp_path / "var")
    from dataclasses import replace

    escaping = replace(walkthrough, filename="../../escape.md")
    with pytest.raises(MutationError) as excinfo:
        write_walkthrough(escaping, zones, confirmed=True)
    assert excinfo.value.code == "containment_escape"
