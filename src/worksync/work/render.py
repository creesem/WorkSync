"""Deterministic text and JSON rendering for work queries."""

from __future__ import annotations

from collections.abc import Iterable

from worksync.work.models import EntityBase
from worksync.work.repository import entity_to_dict
from worksync.work.review import AttentionItem, PersonWorkload, ProjectReview


def attention_to_dict(item: AttentionItem) -> dict:
    """Return a JSON-serializable mapping for one attention item."""
    return {
        "kind": item.kind,
        "severity": item.severity,
        "entity_type": item.entity_type,
        "title": item.title,
        "path": item.path,
        "reason": item.reason,
    }


def project_review_to_dict(review: ProjectReview) -> dict:
    """Return a JSON-serializable mapping for a project review."""
    return {
        "project": entity_to_dict(review.project),
        "people": [entity.title for entity in review.people],
        "tickets": [entity.title for entity in review.tickets],
        "actions": [entity.title for entity in review.actions],
        "meetings": [entity.title for entity in review.meetings],
        "attention": [attention_to_dict(item) for item in review.attention],
        "blockers": [attention_to_dict(item) for item in review.blockers],
    }


def workload_to_dict(workload: PersonWorkload) -> dict:
    """Return a JSON-serializable mapping for a person workload."""
    return {
        "person": entity_to_dict(workload.person),
        "projects": [entity.title for entity in workload.projects],
        "tickets": [entity.title for entity in workload.tickets],
        "actions": [entity.title for entity in workload.actions],
        "meetings": [entity.title for entity in workload.meetings],
        "attention": [attention_to_dict(item) for item in workload.attention],
        "overdue": [attention_to_dict(item) for item in workload.overdue],
    }


def relationships_to_dict(relationships: object) -> dict:
    """Return a JSON-serializable mapping for a project or person's relationships."""
    return {
        "people": [entity.title for entity in relationships.people],
        "projects": [entity.title for entity in relationships.projects],
        "tickets": [entity.title for entity in relationships.tickets],
        "actions": [entity.title for entity in relationships.actions],
        "meetings": [entity.title for entity in relationships.meetings],
    }


def render_attention(title: str, items: Iterable[AttentionItem]) -> str:
    """Render an attention queue."""
    rendered = list(items)
    lines = [f"{title} ({len(rendered)})"]
    for item in rendered:
        lines.append(f"  [{item.severity}] {item.kind}: {item.title} ({item.path}) — {item.reason}")
    if not rendered:
        lines.append("  (none)")
    return "\n".join(lines)


def render_relationships(relationships: object) -> str:
    """Render a project or person's related entities."""
    return "\n".join(
        f"  {label}: {_titles(entities)}"
        for label, entities in (
            ("people", relationships.people),
            ("projects", relationships.projects),
            ("tickets", relationships.tickets),
            ("actions", relationships.actions),
            ("meetings", relationships.meetings),
        )
    )


def render_project_review(review: ProjectReview) -> str:
    """Render one project's management rollup."""
    project = review.project
    lines = [
        f"{project.title}",
        f"  status: {project.status or '-'}",
        f"  priority: {getattr(project, 'priority', None) or '-'}",
        f"  health: {getattr(project, 'health', None) or '-'}",
        f"  owners: {_titles(getattr(project, 'owners', ()))}",
        f"  next review: {getattr(project, 'next_review', None) or '-'}",
        f"  people: {_titles(review.people)}",
        f"  tickets: {_titles(review.tickets)}",
        f"  actions: {_titles(review.actions)}",
        f"  meetings: {_titles(review.meetings)}",
        f"  blockers: {len(review.blockers)}",
    ]
    lines.extend(
        f"    [{blocker.severity}] {blocker.kind}: {blocker.title} — {blocker.reason}" for blocker in review.blockers
    )
    return "\n".join(lines)


def render_projects_review(reviews: Iterable[ProjectReview]) -> str:
    """Render the active-project review board."""
    rendered = list(reviews)
    lines = [f"# Projects review ({len(rendered)})"]
    for review in rendered:
        lines.append(render_project_review(review))
    if not rendered:
        lines.append("  (none)")
    return "\n".join(lines)


def render_workload(workload: PersonWorkload) -> str:
    """Render one person's workload."""
    person = workload.person
    lines = [
        f"{person.title}",
        f"  role: {getattr(person, 'role', None) or '-'}",
        f"  projects: {_titles(workload.projects)}",
        f"  tickets: {_titles(workload.tickets)}",
        f"  actions: {_titles(workload.actions)}",
        f"  meetings: {_titles(workload.meetings)}",
        f"  overdue: {len(workload.overdue)} | attention: {len(workload.attention)}",
    ]
    lines.extend(f"    [{item.severity}] {item.kind}: {item.title} — {item.reason}" for item in workload.attention)
    return "\n".join(lines)


def render_team_review(workloads: Iterable[PersonWorkload]) -> str:
    """Render the team workload board."""
    rendered = list(workloads)
    lines = [f"# Team review ({len(rendered)})"]
    for workload in rendered:
        lines.append(render_workload(workload))
    if not rendered:
        lines.append("  (none)")
    return "\n".join(lines)


def _titles(entities: Iterable[EntityBase]) -> str:
    names = [_display_name(entity) for entity in entities]
    return ", ".join(names) if names else "-"


def _display_name(value: object) -> str:
    if isinstance(value, str):
        return value.strip().strip("[]")
    return str(getattr(value, "title", value))
