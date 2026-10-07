"""Ticket 01: the generated interface is a derived write zone inside the vault."""

from __future__ import annotations

from pathlib import Path

import pytest

from worksync.core.paths import GENERATED_INTERFACE_REL
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import DERIVED_ZONES, ChangeSet, FileOp, MutationError
from worksync.safety.zones import write_zones

GENERATED_FILE = Path("0. System/Interface/index.html")


def _code(excinfo: pytest.ExceptionInfo[MutationError]) -> str:
    return excinfo.value.code


def test_write_zones_maps_generated_inside_the_vault(vault: Path, tmp_path: Path) -> None:
    zones = write_zones(vault, tmp_path / "var")
    generated = zones["generated"]
    assert generated == (vault / GENERATED_INTERFACE_REL).resolve()
    assert generated.is_relative_to(vault.resolve())


def test_generated_is_a_derived_zone() -> None:
    assert "generated" in DERIVED_ZONES


def test_generated_create_commits_without_reviewer(vault: Path, tmp_path: Path) -> None:
    zones = write_zones(vault, tmp_path / "var")
    changeset = ChangeSet(
        "regen_html",
        (FileOp("create", Path("index.html"), "generated", content="<html></html>"),),
    )
    result = commit(changeset, zones)
    assert result.committed is True
    assert (zones["generated"] / "index.html").read_text(encoding="utf-8") == "<html></html>"
    assert result.changes[0]["zone"] == "generated"


def test_generated_update_requires_force(vault: Path, tmp_path: Path) -> None:
    zones = write_zones(vault, tmp_path / "var")
    target = vault / GENERATED_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("old", encoding="utf-8")
    changeset = ChangeSet(
        "regen_html",
        (FileOp("update", Path("index.html"), "generated", content="new", expected=sha256_file(target)),),
    )
    with pytest.raises(MutationError) as excinfo:
        commit(changeset, zones)
    assert _code(excinfo) == "needs_force"
    assert target.read_text(encoding="utf-8") == "old"
    assert commit(changeset, zones, force=True).committed is True


def test_generated_write_refuses_containment_escape(vault: Path, tmp_path: Path) -> None:
    zones = write_zones(vault, tmp_path / "var")
    changeset = ChangeSet(
        "regen_html",
        (FileOp("create", Path("../escape.html"), "generated", content="x"),),
    )
    with pytest.raises(MutationError) as excinfo:
        commit(changeset, zones)
    assert _code(excinfo) == "containment_escape"


def test_generated_write_cannot_escape_to_vault_root(vault: Path, tmp_path: Path) -> None:
    zones = write_zones(vault, tmp_path / "var")
    changeset = ChangeSet(
        "regen_html",
        (FileOp("create", Path("../../note.md"), "generated", content="x"),),
    )
    with pytest.raises(MutationError) as excinfo:
        commit(changeset, zones)
    assert _code(excinfo) == "containment_escape"
