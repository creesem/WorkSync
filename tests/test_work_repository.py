"""Ticket 03: the read-only work index, view exclusion, and health report."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.work.repository import WorkIndex

PROJECT = '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n---\n# Project One\n'


def test_from_vault_builds_entities_and_skips_non_entities(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "9. Project/P.md", PROJECT)
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(vault, "ref.md", "---\ntype: reference\n---\n# Ref\n")
    index = WorkIndex.from_vault(vault)
    assert index.counts()["project"] == 1
    assert index.counts()["person"] == 1
    assert len(index.entities) == 2
    assert index.resolve("Project One") is not None
    assert index.get("person", "Myles") is not None
    assert index.get("project", "Myles") is None


def test_entity_with_error_is_excluded_from_views_but_in_health(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "p.md", "---\ntype: project\nstatus: active\nowners: []\n---\n# Bad Project\n")
    index = WorkIndex.from_vault(vault)
    assert index.view_entities("project") == ()
    report = index.health()
    assert report["entities"] == 1
    assert report["errors"] >= 1
    assert any(issue["path"] == "p.md" for issue in report["issues"])


def test_list_order_is_deterministic(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "b.md", "---\ntype: person\nstatus: active\n---\n# Beta\n")
    write_note(vault, "a.md", "---\ntype: person\nstatus: active\n---\n# Alpha\n")
    index = WorkIndex.from_vault(vault)
    assert [entity.title for entity in index.list_type("person")] == ["Alpha", "Beta"]


def test_duplicate_keys_warn(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "a.md", "---\ntype: person\nstatus: active\n---\n# Same\n")
    write_note(vault, "b.md", "---\ntype: person\nstatus: active\n---\n# Same\n")
    index = WorkIndex.from_vault(vault)
    assert any(issue.rule == "duplicate" for issue in index.warnings)


def test_malformed_frontmatter_is_listed_in_health(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "bad.md", "---\nfoo: [1, 2\n---\n# Bad\n")
    index = WorkIndex.from_vault(vault)
    assert any(issue.rule == "malformed_frontmatter" for issue in index.warnings)
