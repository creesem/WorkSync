"""Ticket 04: relationships derive only from explicit links and resolve stem-then-alias."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.work.models import EntityType
from worksync.work.relationships import related_to
from worksync.work.repository import WorkIndex


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "9. Project/P.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        'people:\n  - "[[Tracy]]"\n---\n# Project Alpha\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(vault, "People/Tracy.md", "---\ntype: person\nstatus: active\n---\n# Tracy\n")
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\nproject: "[[Project Alpha]]"\n---\n# Action One\n',
    )
    write_note(
        vault,
        "Tickets/T1.md",
        '---\ntype: ticket\nstatus: open\nassignee: "[[Myles]]"\nproject: "[[Project Alpha]]"\n---\n# Ticket One\n',
    )
    write_note(
        vault,
        "Meetings/M1.md",
        "---\ntype: meeting\nstatus: held\ndate: 2026-01-01\n"
        'attendees:\n  - "[[Myles]]"\nprojects:\n  - "[[Project Alpha]]"\n---\n# Meeting One\n',
    )


def test_project_relationships(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = WorkIndex.from_vault(vault)
    project = index.get("project", "Project Alpha")
    assert project is not None
    related = related_to(index, project)
    assert [person.title for person in related.people] == ["Myles", "Tracy"]
    assert [action.title for action in related.actions] == ["Action One"]
    assert [ticket.title for ticket in related.tickets] == ["Ticket One"]
    assert [meeting.title for meeting in related.meetings] == ["Meeting One"]


def test_person_relationships(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = WorkIndex.from_vault(vault)
    person = index.get("person", "Myles")
    assert person is not None
    related = related_to(index, person)
    assert [project.title for project in related.projects] == ["Project Alpha"]
    assert [action.title for action in related.actions] == ["Action One"]
    assert [ticket.title for ticket in related.tickets] == ["Ticket One"]
    assert [meeting.title for meeting in related.meetings] == ["Meeting One"]


def test_unresolved_link_never_invents_an_edge(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "9. Project/P.md", '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n---\n# P\n')
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "Actions/Ghost.md",
        '---\ntype: action\nstatus: open\nproject: "[[Does Not Exist]]"\n---\n# Ghost Action\n',
    )
    index = WorkIndex.from_vault(vault)
    project = index.get("project", "P")
    assert project is not None
    assert related_to(index, project).actions == ()
    assert any(issue.rule == "unresolved_link" for issue in index.warnings)


def test_link_resolves_by_filename_stem_before_title(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "9. Project/P.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[MC]]"\n---\n# P\n',
    )
    write_note(vault, "People/MC.md", "---\ntype: person\nstatus: active\n---\n# Myles Creese\n")
    index = WorkIndex.from_vault(vault)
    project = index.get("project", "P")
    assert project is not None
    assert [person.title for person in related_to(index, project).people] == ["Myles Creese"]


def test_link_resolves_by_alias(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "Tickets/T1.md",
        '---\ntype: ticket\nstatus: open\nassignee: "[[Venkat]]"\n---\n# Ticket One\n',
    )
    write_note(
        vault,
        "People/Venkatesh.md",
        "---\ntype: person\nstatus: active\naliases:\n  - Venkat\n---\n# Venkatesh\n",
    )
    index = WorkIndex.from_vault(vault)
    person = index.get("person", "Venkat")
    assert person is not None
    assert person.entity_type is EntityType.PERSON
    assert [ticket.title for ticket in related_to(index, person).tickets] == ["Ticket One"]
