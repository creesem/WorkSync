"""Personal core: the explicit, dry-run-first initial seed."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from worksync.work.personal.repository import PersonalIndex
from worksync.work.personal.seed import SEED_AREAS, SEED_PROJECTS, apply_seed, plan_seed
from worksync.work.personal.writer import PersonalWriteError

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
REVIEWER = "Myles"
WORK = '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n---\n# Work Alpha\n'


def test_seed_catalog_matches_the_initial_user_context(vault: Path) -> None:
    plan = plan_seed(vault)
    assert [item.name for item in plan.items if item.kind == "area"] == list(SEED_AREAS)
    projects = [(item.name, item.area, item.due) for item in plan.items if item.kind == "project"]
    assert projects == [
        ("Job applications", "Career", None),
        ("Shibari", "Learning", None),
        ("Star Trek Sealed", "Hobbies", "2026-11-06"),
        ("WorkSync", "Coding", None),
        ("mtgbuddy", "Coding", None),
        ("roadmap lifecycle skill", "Coding", None),
    ]
    assert plan.items and all(item.kind in {"area", "project"} for item in plan.items)
    assert SEED_PROJECTS[-1].name == "roadmap lifecycle skill"


def test_seed_dry_run_writes_nothing(vault: Path, tmp_path: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "9. Project/Project - Alpha.md", WORK)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    result = apply_seed(vault, tmp_path / "var", reviewer=REVIEWER, now=NOW)
    assert result["dry_run"] is True
    assert result["committed"] is False
    assert len(result["created"]) == 10
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before
    assert not (tmp_path / "var" / "journal").exists()


def test_seed_apply_writes_through_the_gateway_and_keeps_work_notes(
    vault: Path, tmp_path: Path, write_note: Callable[..., Path]
) -> None:
    write_note(vault, "9. Project/Project - Alpha.md", WORK)
    work_before = (vault / "9. Project/Project - Alpha.md").read_bytes()
    runtime = tmp_path / "var"
    result = apply_seed(vault, runtime, reviewer=REVIEWER, dry_run=False, now=NOW)
    assert result["committed"] is True
    assert result["skipped"] == []
    index = PersonalIndex.from_vault(vault)
    assert [area.title for area in index.areas] == ["Career", "Coding", "Hobbies", "Learning"]
    assert [project.title for project in index.projects] == [
        "Job applications",
        "mtgbuddy",
        "roadmap lifecycle skill",
        "Shibari",
        "Star Trek Sealed",
        "WorkSync",
    ]
    star_trek = index.get_project("star-trek-sealed")
    assert star_trek is not None and star_trek.due == "2026-11-06"
    assert index.tasks == ()
    assert (vault / "9. Project/Project - Alpha.md").read_bytes() == work_before
    assert (runtime / "journal").is_dir()


def test_seed_is_idempotent_and_never_overwrites(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    apply_seed(vault, runtime, reviewer=REVIEWER, dry_run=False, now=NOW)
    career = (vault / "11. Personal/Areas/Career.md").read_bytes()
    second = apply_seed(vault, runtime, reviewer=REVIEWER, dry_run=False, now=NOW)
    assert second["created"] == []
    assert len(second["skipped"]) == 10
    assert (vault / "11. Personal/Areas/Career.md").read_bytes() == career


def test_seed_requires_a_reviewer(vault: Path, tmp_path: Path) -> None:
    with pytest.raises(PersonalWriteError) as excinfo:
        apply_seed(vault, tmp_path / "var", reviewer="  ", dry_run=False, now=NOW)
    assert excinfo.value.code == "missing_reviewer"
    assert not (vault / "11. Personal").exists()
