"""Shared builders for the Command Center prioritization test suites.

The ranker and the override hook are tested in isolation, so both build
``Candidate`` values directly. One builder and one fixed ``TODAY`` keep those
suites from drifting apart, the way ``krisp_fakes`` does for the Krisp suites.
"""

from __future__ import annotations

from datetime import date

from worksync.work.models import EntityType
from worksync.work.prioritization import Candidate

TODAY = date(2026, 10, 12)


def candidate(
    *,
    entity_id: str = "alpha-action",
    entity_type: str = EntityType.ACTION.value,
    title: str = "Alpha",
    status: str = "open",
    priority: str | None = None,
    owner_ids: tuple[str, ...] = ("myles-smith",),
    due: str | None = None,
    project_id: str | None = "eleos",
    blocked: bool = False,
    waiting: bool = False,
    manager_attention: bool = False,
    changed_on: str | None = None,
) -> Candidate:
    """Build one candidate, overriding only the fields a case is about."""
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        path=f"Notes/{entity_id}.md",
        title=title,
        status=status,
        priority=priority,
        owner_ids=owner_ids,
        due=due,
        project_id=project_id,
        blocked=blocked,
        waiting=waiting,
        manager_attention=manager_attention,
        changed_on=changed_on,
    )
