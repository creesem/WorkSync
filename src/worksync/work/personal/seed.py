"""The explicit initial personal seed: four areas and six projects.

The seed is deliberately small and idempotent. It creates no tasks, never touches a
work note, and is dry-run by default. A caller must pass ``dry_run=False`` and a
named reviewer before anything is written, and no CLI or server route invokes it,
so it cannot run against the configured vault unattended.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from worksync.core.names import safe_name
from worksync.work.personal.models import AREAS_DIR, PERSONAL_ROOT, PROJECTS_DIR
from worksync.work.personal.repository import PersonalIndex
from worksync.work.personal.writer import PersonalWriteError, create_area, create_project

SEED_AREAS: tuple[str, ...] = ("Career", "Learning", "Hobbies", "Coding")


@dataclass(frozen=True)
class SeedProject:
    """One project in the initial seed."""

    name: str
    area: str
    due: str | None = None


SEED_PROJECTS: tuple[SeedProject, ...] = (
    SeedProject("Job applications", "Career"),
    SeedProject("Shibari", "Learning"),
    SeedProject("Star Trek Sealed", "Hobbies", due="2026-11-06"),
    SeedProject("WorkSync", "Coding"),
    SeedProject("mtgbuddy", "Coding"),
    SeedProject("roadmap lifecycle skill", "Coding"),
)


@dataclass(frozen=True)
class SeedItem:
    """One planned seed note."""

    kind: str
    name: str
    area: str | None = None
    due: str | None = None

    @property
    def path(self) -> str:
        directory = AREAS_DIR if self.kind == "area" else PROJECTS_DIR
        return f"{PERSONAL_ROOT}/{directory}/{safe_name(self.name)}.md"


@dataclass(frozen=True)
class SeedPlan:
    """The creates that are still missing, plus the names already present."""

    items: tuple[SeedItem, ...]
    skipped: tuple[str, ...]


def plan_seed(vault: str | Path) -> SeedPlan:
    """Return the seed items that do not exist yet, without writing anything."""
    index = PersonalIndex.from_vault(vault)
    area_keys = {area.area_id.casefold() for area in index.areas} | {area.title.casefold() for area in index.areas}
    project_keys = {project.project_id.casefold() for project in index.projects} | {
        project.title.casefold() for project in index.projects
    }
    items: list[SeedItem] = []
    skipped: list[str] = []
    for name in SEED_AREAS:
        if name.casefold() in area_keys:
            skipped.append(name)
            continue
        items.append(SeedItem("area", name))
    for project in SEED_PROJECTS:
        if project.name.casefold() in project_keys:
            skipped.append(project.name)
            continue
        items.append(SeedItem("project", project.name, project.area, project.due))
    return SeedPlan(items=tuple(items), skipped=tuple(skipped))


def apply_seed(
    vault: str | Path,
    runtime: str | Path,
    *,
    reviewer: str,
    reason: str = "Seed personal areas and projects",
    dry_run: bool = True,
    now: datetime | None = None,
) -> dict:
    """Plan or apply the initial seed; dry-run unless explicitly disabled."""
    if not str(reviewer or "").strip():
        raise PersonalWriteError("missing_reviewer", "A canonical write requires a named reviewer.")
    if not str(reason or "").strip():
        raise PersonalWriteError("missing_reason", "A canonical write requires a human-readable reason.")
    plan = plan_seed(vault)
    results: list[dict] = []
    if dry_run:
        for item in plan.items:
            results.append(
                {"kind": item.kind, "name": item.name, "path": item.path, "committed": False, "planned": True}
            )
        return {
            "dry_run": True,
            "committed": False,
            "reviewer": reviewer,
            "reason": reason,
            "created": [item.name for item in plan.items],
            "skipped": list(plan.skipped),
            "results": results,
        }

    for item in plan.items:
        if item.kind == "area":
            result = create_area(
                vault, runtime, name=item.name, reason=reason, reviewer=reviewer, now=now, confirmed=False
            )
        else:
            result = create_project(
                vault,
                runtime,
                name=item.name,
                area=item.area,
                due=item.due,
                reason=reason,
                reviewer=reviewer,
                now=now,
                confirmed=False,
            )
        results.append(
            {
                "kind": item.kind,
                "name": item.name,
                "path": result.path,
                "committed": result.committed,
                "planned": False,
            }
        )
    return {
        "dry_run": False,
        "committed": True,
        "reviewer": reviewer,
        "reason": reason,
        "created": [item.name for item in plan.items],
        "skipped": list(plan.skipped),
        "results": results,
    }
