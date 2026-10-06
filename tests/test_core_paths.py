"""Ticket 01: containment, legacy-path rebasing, and unique targets."""

from __future__ import annotations

from pathlib import Path

import pytest

from worksync.core.names import safe_name
from worksync.core.paths import PathSafetyError, ensure_under, resolve_stored_path, unique_target

LEGACY = "C:/Users/macre/OneDrive/Documents/WorkSync"


def test_ensure_under_allows_descendant(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    assert ensure_under(root, root / "a" / "b.md") == (root / "a" / "b.md").resolve()


def test_ensure_under_refuses_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathSafetyError):
        ensure_under(root, root / ".." / "outside.md")


def test_ensure_under_refuses_absolute_outside(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathSafetyError):
        ensure_under(root, tmp_path / "outside.md")


def test_resolve_stored_relative_path(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "sub" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("x", encoding="utf-8")
    assert resolve_stored_path(vault, "sub/note.md") == note.resolve()


def test_resolve_stored_absolute_path_inside_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "note.md"
    vault.mkdir()
    note.write_text("x", encoding="utf-8")
    assert resolve_stored_path(vault, str(note)) == note.resolve()


def test_resolve_stored_absolute_path_outside_vault_fails(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        resolve_stored_path(vault, str(outside))


def test_resolve_stored_rebases_legacy_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "sub" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("x", encoding="utf-8")
    resolved = resolve_stored_path(vault, f"{LEGACY}/sub/note.md", legacy_roots=(LEGACY,))
    assert resolved == note.resolve()


def test_resolve_stored_legacy_target_missing_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(FileNotFoundError):
        resolve_stored_path(vault, f"{LEGACY}/gone.md", legacy_roots=(LEGACY,))


def test_resolve_stored_missing_relative_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(FileNotFoundError):
        resolve_stored_path(vault, "missing.md")


def test_resolve_stored_empty_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(FileNotFoundError):
        resolve_stored_path(vault, "   ")


def test_unique_target_avoids_collision(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("x", encoding="utf-8")
    (tmp_path / "note 1.md").write_text("x", encoding="utf-8")
    assert unique_target(tmp_path, "note.md").name == "note 2.md"


def test_unique_target_when_free(tmp_path: Path) -> None:
    assert unique_target(tmp_path, "note.md").name == "note.md"


def test_safe_name_strips_forbidden_characters() -> None:
    assert safe_name('a/b:c*d?e"f<g>h|i') == "a-b-c-d-e-f-g-h-i"


def test_safe_name_falls_back_when_empty() -> None:
    assert safe_name("///", fallback="untitled") == "untitled"
