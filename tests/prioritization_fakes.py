"""Shared builders for the Command Center prioritization test suites.

The ranker, the override hook, and the eligibility rules are all tested against
the same vault shapes, so the ``Candidate`` builder, the vault seed helpers, the
note-body builders, and the fixed ``TODAY`` live here — one definition each, the
way ``krisp_fakes`` does for the Krisp suites.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from worksync.work.models import EntityType
from worksync.work.prioritization import Candidate

TODAY = date(2026, 10, 12)

PERSON_NOTE = "---\ntype: person\nstatus: active\nperson_id: myles-smith\n---\n# Myles Smith\n"


def seed_person(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    """Seed the owner every shared candidate note links to."""
    write_note(vault, "People/Myles Smith.md", PERSON_NOTE)


def seed_project(vault: Path, write_note: Callable[[Path, str, str], Path]) -> None:
    """Seed the person and the active project the shared note bodies reference."""
    seed_person(vault, write_note)
    project_note = (
        "---\n"
        "type: project\n"
        "status: active\n"
        'owners:\n  - "[[Myles Smith]]"\n'
        "project_id: eleos\n"
        "---\n"
        "# Project - Eleos\n"
    )
    write_note(vault, "Projects/Eleos.md", project_note)


def action_note(body: str) -> str:
    """Wrap one action frontmatter body in its note."""
    return f"---\n{body}---\n# Action note\n"


def ticket_note(body: str) -> str:
    """Wrap one ticket frontmatter body in its note."""
    return f"---\n{body}---\n# Ticket note\n"


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
    waiting_on: str | None = None,
    manager_attention: bool = False,
    changed_on: str | None = None,
    dependency_id: str | None = None,
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
        waiting_on=waiting_on,
        manager_attention=manager_attention,
        changed_on=changed_on,
        dependency_id=dependency_id,
    )
