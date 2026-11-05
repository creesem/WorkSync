"""The read-only personal index: personal notes only, grouped area -> project -> task.

The index scans the shared inventory once and keeps only notes that declare a
personal type *and* live under ``11. Personal/``. Work entities are therefore
invisible here, and personal notes can never enter ``WorkIndex`` because the work
schema does not know their types. No write helper is reachable from this module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from worksync.inventory.parse import IndexRecord, scan_vault
from worksync.work.personal.models import PersonalArea, PersonalProject, PersonalTask
from worksync.work.personal.schema import parse_personal_record
from worksync.work.schema import link_target
from worksync.work.validate import ValidationIssue

_PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


@dataclass(frozen=True)
class PersonalIndex:
    """A read-only view of every personal entity in a vault."""

    root: Path
    areas: tuple[PersonalArea, ...] = ()
    projects: tuple[PersonalProject, ...] = ()
    tasks: tuple[PersonalTask, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    _area_lookup: dict[str, PersonalArea] = field(default_factory=dict, repr=False)
    _project_lookup: dict[str, PersonalProject] = field(default_factory=dict, repr=False)

    @classmethod
    def from_vault(cls, vault_root: str | Path) -> PersonalIndex:
        """Scan *vault_root* and keep only personal notes."""
        root = Path(vault_root).expanduser().resolve()
        return cls.from_records(scan_vault(root), root)

    @classmethod
    def from_records(cls, records: Iterable[IndexRecord], root: str | Path) -> PersonalIndex:
        """Build the index from an existing scan (shared with the read seam's cache)."""
        areas: list[PersonalArea] = []
        projects: list[PersonalProject] = []
        tasks: list[PersonalTask] = []
        issues: list[ValidationIssue] = []
        for record in records:
            entity, record_issues = parse_personal_record(record)
            issues.extend(record_issues)
            if isinstance(entity, PersonalArea):
                areas.append(entity)
            elif isinstance(entity, PersonalProject):
                projects.append(entity)
            elif isinstance(entity, PersonalTask):
                tasks.append(entity)
        ordered_areas = tuple(sorted(areas, key=lambda area: (area.title.casefold(), area.path)))
        ordered_projects = tuple(sorted(projects, key=lambda project: (project.title.casefold(), project.path)))
        ordered_tasks = tuple(sorted(tasks, key=_task_sort))
        return cls(
            root=Path(root),
            areas=ordered_areas,
            projects=ordered_projects,
            tasks=ordered_tasks,
            issues=tuple(sorted(issues, key=lambda issue: (issue.path, issue.severity, issue.message))),
            _area_lookup=_lookup(
                ordered_areas,
                id_of=lambda area: area.area_id,
                title_of=lambda area: area.title,
            ),
            _project_lookup=_lookup(
                ordered_projects,
                id_of=lambda project: project.project_id,
                title_of=lambda project: project.title,
            ),
        )

    def get_area(self, name: str) -> PersonalArea | None:
        """Resolve an area by id, title, or note name."""
        return self._area_lookup.get(link_target(name))

    def get_project(self, name: str) -> PersonalProject | None:
        """Resolve a project by id, title, or note name."""
        return self._project_lookup.get(link_target(name))

    def projects_for_area(self, area: str) -> tuple[PersonalProject, ...]:
        """Return the projects directly nested under *area*."""
        target = self.get_area(area)
        if target is None:
            return ()
        keys = _keys(target.area_id, target.title)
        return tuple(project for project in self.projects if link_target(project.area or "") in keys)

    def tasks_for_area(self, area: str) -> tuple[PersonalTask, ...]:
        """Return the tasks directly assigned to *area*."""
        target = self.get_area(area)
        if target is None:
            return ()
        keys = _keys(target.area_id, target.title)
        return tuple(task for task in self.tasks if link_target(task.area or "") in keys)

    def tasks_for_project(self, project: str) -> tuple[PersonalTask, ...]:
        """Return the tasks directly assigned to *project*."""
        target = self.get_project(project)
        if target is None:
            return ()
        keys = _keys(target.project_id, target.title)
        return tuple(task for task in self.tasks if link_target(task.project or "") in keys)


def priority_rank(value: str | None) -> int:
    """Return the ordering rank for a priority, with unset after every set value."""
    return _PRIORITY_RANK.get(value or "", 9)


def _keys(*values: str) -> frozenset[str]:
    return frozenset(link_target(value) for value in values if value)


def _lookup(entities: Iterable[PersonalArea | PersonalProject], *, id_of, title_of) -> dict[str, object]:
    """Map ids, titles, and note stems to entities; the first precedence wins."""
    lookup: dict[str, object] = {}
    for entity in entities:
        stem = Path(entity.path).stem
        for value in (stem, id_of(entity), title_of(entity)):
            key = link_target(value)
            if key:
                lookup.setdefault(key, entity)
    return lookup


def _task_sort(task: PersonalTask) -> tuple[str, str, str]:
    return (task.title.casefold(), task.path, task.task_id)
