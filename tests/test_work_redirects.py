"""WP-03: the durable person redirect registry and its acyclic resolver."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from worksync.work.consolidate import redirect_content
from worksync.work.redirects import (
    RedirectError,
    load_redirects,
    rebuild_redirects,
    redirect_registry_path,
    resolve_person,
)

PEOPLE = "People"


def test_load_missing_registry_is_empty(tmp_path: Path) -> None:
    assert load_redirects(tmp_path / "var") == {}


def test_load_corrupt_registry_fails_closed(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    path = redirect_registry_path(runtime)
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(RedirectError) as excinfo:
        load_redirects(runtime)
    assert excinfo.value.code == "redirect_registry_unreadable"


def test_resolve_follows_a_chain() -> None:
    assert resolve_person("a", {"a": "b", "b": "c"}) == "c"


def test_resolve_without_a_redirect_returns_itself() -> None:
    assert resolve_person("carlos-barnes", {}) == "carlos-barnes"


def test_resolve_cycle_fails_closed() -> None:
    with pytest.raises(RedirectError) as excinfo:
        resolve_person("a", {"a": "b", "b": "a"})
    assert excinfo.value.code == "redirect_cycle"


def test_resolve_self_cycle_fails_closed() -> None:
    with pytest.raises(RedirectError) as excinfo:
        resolve_person("a", {"a": "a"})
    assert excinfo.value.code == "redirect_cycle"


def _tombstone(retired: str, retired_id: str, canonical_title: str) -> str:
    content = f"---\ntype: person\nstatus: active\nperson_id: {retired_id}\n---\n# {retired}\n"
    return redirect_content(
        content,
        {"type": "person", "status": "active", "person_id": retired_id},
        canonical_title,
        when="2026-10-10",
        reviewer="Myles",
        reason="same person",
    )


def test_rebuild_reconstructs_from_tombstones(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(
        vault,
        f"{PEOPLE}/Carlos Barnes.md",
        "---\ntype: person\nstatus: active\nperson_id: carlos-barnes\n---\n# Carlos Barnes\n",
    )
    write_note(vault, f"{PEOPLE}/Carlos B.md", _tombstone("Carlos B", "carlos-b", "Carlos Barnes"))
    runtime = tmp_path / "var"

    redirects = rebuild_redirects(vault, runtime)

    assert redirects == {"carlos-b": "carlos-barnes"}
    assert load_redirects(runtime) == {"carlos-b": "carlos-barnes"}
