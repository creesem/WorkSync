"""Ticket 09: deterministic generated views and the contained gated view writer."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from worksync.core.paths import PathSafetyError
from worksync.safety.models import MutationError
from worksync.work.models import Action, Person, Project, Ticket
from worksync.work.repository import WorkIndex
from worksync.work.views import VIEW_NAMES, build_views, view_zones, write_views

TODAY = date(2026, 1, 15)
GENERATED_AT = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


def _index() -> WorkIndex:
    project = Project(
        path="p.md",
        title="P",
        status="active",
        owners=("[[Myles]]",),
        last_reviewed="2026-01-01",
        next_review="2026-01-10",
    )
    overdue = Action(
        path="a.md", title="A overdue", status="open", due="2026-01-05", owners=("[[Myles]]",), project="[[P]]"
    )
    waiting = Action(path="w.md", title="W waiting", status="waiting", waiting_on="vendor")
    ticket = Ticket(path="t.md", title="T", status="in_progress", manager_attention=True)
    person = Person(path="people/myles.md", title="Myles", status="active")
    return WorkIndex.from_entities([project, overdue, waiting, ticket, person])


def test_views_render_deterministically_for_fixed_inputs() -> None:
    first = build_views(_index(), today=TODAY, generated_at=GENERATED_AT)
    second = build_views(_index(), today=TODAY, generated_at=GENERATED_AT)
    assert tuple(view.name for view in first) == VIEW_NAMES
    assert [view.content for view in first] == [view.content for view in second]
    for view in first:
        assert f"view: {view.name}" in view.content
        assert "generator: worksync" in view.content
        assert "reference_date: 2026-01-15" in view.content
        assert "generated_at: 2026-01-15T09:00:00+00:00" in view.content
        assert view.sources
        assert view.filename.endswith(".md")


def test_unconfirmed_write_reports_needs_confirmation_and_writes_nothing(tmp_path: Path) -> None:
    views = build_views(_index(), today=TODAY, generated_at=GENERATED_AT)
    zones = view_zones(tmp_path / "var")
    with pytest.raises(MutationError) as excinfo:
        write_views(views, zones)
    assert excinfo.value.code == "needs_confirmation"
    assert not zones["views"].exists()


def test_confirmed_write_targets_only_the_contained_views_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("canonical", encoding="utf-8")
    zones = view_zones(tmp_path / "var", vault_root=vault)
    views = build_views(_index(), today=TODAY, generated_at=GENERATED_AT)

    result = write_views(views, zones, confirmed=True)

    assert result.committed is True
    for view in views:
        assert (zones["views"] / view.filename).read_text(encoding="utf-8") == view.content
    assert note.read_text(encoding="utf-8") == "canonical"
    assert [path for path in vault.rglob("*.md")] == [note]


def test_existing_view_is_refused_without_force_then_overwritten_with_it(tmp_path: Path) -> None:
    zones = view_zones(tmp_path / "var")
    views = build_views(_index(), today=TODAY, generated_at=GENERATED_AT)
    write_views(views, zones, confirmed=True)
    target = zones["views"] / views[0].filename
    target.write_text("edited by hand", encoding="utf-8")

    with pytest.raises(MutationError) as excinfo:
        write_views(views, zones, confirmed=True)
    assert excinfo.value.code == "needs_force"
    assert target.read_text(encoding="utf-8") == "edited by hand"

    assert write_views(views, zones, confirmed=True, force=True).committed is True
    assert target.read_text(encoding="utf-8") == views[0].content


def test_a_partly_existing_write_is_all_or_nothing(tmp_path: Path) -> None:
    zones = view_zones(tmp_path / "var")
    zones["views"].mkdir(parents=True)
    existing = zones["views"] / "Today.md"
    existing.write_text("manual", encoding="utf-8")
    views = build_views(_index(), today=TODAY, generated_at=GENERATED_AT)

    with pytest.raises(MutationError) as excinfo:
        write_views(views, zones, confirmed=True)
    assert excinfo.value.code == "needs_force"
    assert existing.read_text(encoding="utf-8") == "manual"
    for view in views[1:]:
        assert not (zones["views"] / view.filename).exists()


def test_view_zones_refuses_a_views_root_inside_the_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(PathSafetyError):
        view_zones(vault / "var", vault_root=vault)
