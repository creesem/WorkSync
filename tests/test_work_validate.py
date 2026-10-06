"""Ticket 03: validation error and warning tiers."""

from __future__ import annotations

from worksync.work.models import Action, Meeting, Person, Project, Ticket
from worksync.work.validate import has_errors, validate_all, validate_entity


def test_missing_status_is_error() -> None:
    issues = validate_entity(Project(path="p.md", title="P", status="", owners=("[[A]]",)))
    assert any(issue.rule == "required" and issue.severity == "error" for issue in issues)


def test_invalid_status_is_error() -> None:
    issues = validate_entity(Person(path="p.md", title="P", status="bogus"))
    assert any(issue.rule == "enum" and issue.severity == "error" for issue in issues)


def test_project_requires_owner() -> None:
    issues = validate_entity(Project(path="p.md", title="P", status="active", owners=()))
    assert any("owner" in issue.message and issue.severity == "error" for issue in issues)


def test_meeting_requires_date() -> None:
    issues = validate_entity(Meeting(path="m.md", title="M", status="held", date=None))
    assert any(issue.rule == "required" and "date" in issue.message for issue in issues)


def test_action_waiting_requires_waiting_on() -> None:
    issues = validate_entity(Action(path="a.md", title="A", status="waiting", waiting_on=None))
    assert any(issue.severity == "error" and "waiting_on" in issue.message for issue in issues)


def test_action_done_requires_completed() -> None:
    issues = validate_entity(Action(path="a.md", title="A", status="done", completed=None))
    assert any(issue.severity == "error" and "completed" in issue.message for issue in issues)


def test_ticket_external_sync_requires_source_and_id() -> None:
    issues = validate_entity(Ticket(path="t.md", title="T", status="open", sync_mode="reference"))
    messages = [issue.message for issue in issues]
    assert any("source_system" in message for message in messages)
    assert any("external_id" in message for message in messages)


def test_project_review_date_order_is_error() -> None:
    issues = validate_entity(
        Project(
            path="p.md",
            title="P",
            status="active",
            owners=("[[A]]",),
            last_reviewed="2026-02-01",
            next_review="2026-01-01",
        )
    )
    assert any(issue.rule == "date_order" and issue.severity == "error" for issue in issues)


def test_source_system_without_sync_mode_is_warning() -> None:
    issues = validate_entity(Meeting(path="m.md", title="M", status="held", date="2026-01-01", source_system="krisp"))
    assert any(issue.severity == "warning" and issue.rule == "conditional" for issue in issues)


def test_invalid_priority_and_health_are_errors() -> None:
    issues = validate_entity(
        Project(
            path="p.md",
            title="P",
            status="active",
            owners=("[[A]]",),
            priority="P9",
            health="blue",
        )
    )
    assert sum(issue.rule == "enum" for issue in issues) >= 2


def test_unresolved_link_is_a_warning_not_an_error() -> None:
    project = Project(path="p.md", title="P", status="active", owners=("[[Ghost]]",))
    issues = validate_all([project], known_targets={"p"})
    unresolved = [issue for issue in issues if issue.rule == "unresolved_link"]
    assert unresolved and unresolved[0].severity == "warning"
    assert not has_errors(unresolved)
