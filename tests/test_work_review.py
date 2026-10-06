"""Ticket 04: attention queues and project/person rollups are deterministic."""

from __future__ import annotations

from datetime import date

from worksync.work.models import Action, Person, Project, Ticket
from worksync.work.repository import WorkIndex
from worksync.work.review import attention_items, build_person_workload, build_project_review

TODAY = date(2026, 1, 15)


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


def test_attention_items_cover_kinds_severity_and_reason() -> None:
    items = attention_items(_index(), TODAY)
    by_kind = {item.kind: item for item in items}
    assert by_kind["overdue_action"].severity == "high"
    assert by_kind["manager_attention"].severity == "high"
    assert by_kind["review_due"].severity == "medium"
    assert by_kind["stale_ticket"].severity == "medium"
    assert by_kind["waiting"].severity == "medium"
    assert by_kind["unassigned_ticket"].severity == "low"
    assert all(item.reason for item in items)


def test_attention_is_severity_ordered_and_deterministic() -> None:
    index = _index()
    first = attention_items(index, TODAY)
    second = attention_items(index, TODAY)
    assert first == second
    severities = [item.severity for item in first]
    assert severities == sorted(severities, key={"high": 0, "medium": 1, "low": 2}.get)


def test_project_review_collects_related_attention_and_blockers() -> None:
    index = _index()
    project = index.get("project", "P")
    assert project is not None
    review = build_project_review(index, project, TODAY)
    assert [action.title for action in review.actions] == ["A overdue"]
    assert any(item.kind == "overdue_action" for item in review.blockers)


def test_person_workload_reports_overdue() -> None:
    index = _index()
    person = index.get("person", "Myles")
    assert person is not None
    workload = build_person_workload(index, person, TODAY)
    assert [action.title for action in workload.actions] == ["A overdue"]
    assert [item.kind for item in workload.overdue] == ["overdue_action"]
