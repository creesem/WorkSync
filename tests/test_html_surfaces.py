"""Ticket 03: the generated interface surfaces beyond the home page."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from worksync.html.generator import (
    AttentionRef,
    DetailSection,
    EntityDetail,
    EntityLink,
    Navigation,
    PersonRow,
    ProjectRow,
    WorkdayPlan,
    WorkdaySlot,
    build_home,
    build_pages,
    build_projects,
    build_team,
    build_today,
)

TODAY = date(2026, 1, 15)
GENERATED_AT = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
VAULT = "WorkSync"

PROJECT = ProjectRow(
    "Project Eleos",
    "9. Project/Project - Eleos.md",
    status="active",
    priority="P2",
    owner="Myles",
    health="green",
)
PERSON = PersonRow("Myles", "People/Myles.md", role="Engineer", projects=1, tickets=2, actions=3, attention=1)
WORKDAY = WorkdayPlan(
    date="2026-01-15",
    slots=(
        WorkdaySlot("must_win", EntityLink("Task A", "Actions/A.md", status="open", detail="P1")),
        WorkdaySlot("support_one"),
        WorkdaySlot("support_two"),
        WorkdaySlot("unblock"),
        WorkdaySlot("quick_win"),
    ),
)
ATTENTION = (
    AttentionRef("waiting", "medium", "Ticket W", "Tickets/W.md", "Waiting on vendor"),
    AttentionRef("blocked", "high", "Ticket B", "Tickets/B.md", "Blocked on access"),
)
PROJECT_DETAIL = EntityDetail(
    "Project Eleos",
    "project",
    "9. Project/Project - Eleos.md",
    fields=(("Status", "active"), ("Priority", "P2"), ("Health", "green"), ("Owner", "Myles")),
    sections=(DetailSection("Tickets", (EntityLink("Ticket X", "Tickets/X.md"),)),),
)
PERSON_DETAIL = EntityDetail(
    "Myles",
    "person",
    "People/Myles.md",
    fields=(("Role", "Engineer"),),
    sections=(DetailSection("Actions", (EntityLink("Task A", "Actions/A.md"),)),),
)


def _build(**overrides):
    data = dict(vault_name=VAULT, today=TODAY, generated_at=GENERATED_AT)
    data.update(overrides)
    return build_pages(**data)


def _page(pages, filename: str):
    return next(page for page in pages if page.filename == filename)


def test_build_pages_returns_every_surface_in_order() -> None:
    pages = _build(
        project_rows=(PROJECT,),
        person_rows=(PERSON,),
        workday=WORKDAY,
        attention=ATTENTION,
        project_details=(PROJECT_DETAIL,),
        person_details=(PERSON_DETAIL,),
    )
    assert [page.filename for page in pages] == [
        "index.html",
        "today.html",
        "projects.html",
        "team.html",
        "project/Project Eleos.html",
        "person/Myles.html",
    ]


def test_build_pages_with_empty_inputs_still_renders_the_base_surfaces() -> None:
    pages = _build()
    assert [page.filename for page in pages] == ["index.html", "today.html", "projects.html", "team.html"]
    assert all(page.content.rstrip().endswith("</html>") for page in pages)


def test_home_navigation_links_the_built_surfaces() -> None:
    content = _page(_build(), "index.html").content
    for name in ("today.html", "projects.html", "team.html"):
        assert f"file={name}" in content


def test_home_navigation_omits_a_page_that_was_not_built() -> None:
    page = build_home(
        vault_name=VAULT,
        nav=(Navigation("Today", "today.html"), Navigation("Ghost", "ghost.html")),
        existing=frozenset({"today.html"}),
        today=TODAY,
        generated_at=GENERATED_AT,
    )
    assert "file=today.html" in page.content
    assert "ghost.html" not in page.content


def test_today_renders_slots_attention_and_waiting() -> None:
    content = build_today(
        vault_name=VAULT, plan=WORKDAY, attention=ATTENTION, today=TODAY, generated_at=GENERATED_AT
    ).content
    assert "Must win" in content
    assert "Task A" in content
    assert "file=Actions/A" in content
    assert "(open)" in content
    assert "Ticket B" in content
    assert "Ticket W" in content


def test_today_renders_without_a_plan_or_attention() -> None:
    page = build_today(vault_name=VAULT, today=TODAY, generated_at=GENERATED_AT)
    assert "No workday plan" in page.content
    assert page.content.rstrip().endswith("</html>")


def test_projects_lists_fields_and_links_to_detail_pages() -> None:
    content = build_projects(
        vault_name=VAULT,
        rows=(PROJECT,),
        existing=frozenset({"project/Project Eleos.html"}),
        today=TODAY,
        generated_at=GENERATED_AT,
    ).content
    assert "active" in content
    assert "P2" in content
    assert "Myles" in content
    assert "green" in content
    assert "file=project/Project%20Eleos.html" in content


def test_projects_renders_with_no_rows() -> None:
    content = build_projects(vault_name=VAULT, today=TODAY, generated_at=GENERATED_AT).content
    assert "No active projects." in content


def test_team_lists_workload_and_links_to_detail_pages() -> None:
    content = build_team(
        vault_name=VAULT,
        rows=(PERSON,),
        existing=frozenset({"person/Myles.html"}),
        today=TODAY,
        generated_at=GENERATED_AT,
    ).content
    assert "Engineer" in content
    assert "2 tickets" in content
    assert "file=person/Myles.html" in content


def test_team_renders_with_no_rows() -> None:
    content = build_team(vault_name=VAULT, today=TODAY, generated_at=GENERATED_AT).content
    assert "No active people." in content


def test_project_detail_shows_fields_source_and_relations() -> None:
    content = _page(_build(project_details=(PROJECT_DETAIL,)), "project/Project Eleos.html").content
    assert "Status" in content
    assert "file=9.%20Project/Project%20-%20Eleos" in content
    assert "Ticket X" in content
    assert "file=Tickets/X" in content


def test_person_detail_shows_fields_and_source() -> None:
    content = _page(_build(person_details=(PERSON_DETAIL,)), "person/Myles.html").content
    assert "Role" in content
    assert "Engineer" in content
    assert "file=People/Myles" in content
    assert "Task A" in content


def test_detail_omits_an_unresolved_reference() -> None:
    detail = EntityDetail(
        "Orphan",
        "project",
        "",
        sections=(DetailSection("Tickets", (EntityLink("Ghost", ""),)),),
    )
    content = _page(_build(project_details=(detail,)), "project/Orphan.html").content
    assert "Ghost" in content
    assert "obsidian://" not in content


def test_detail_renders_with_no_fields_or_sections() -> None:
    detail = EntityDetail("Bare", "person", "People/Bare.md")
    page = _page(_build(person_details=(detail,)), "person/Bare.html")
    assert "People/Bare" in page.content
    assert page.content.rstrip().endswith("</html>")


def test_build_pages_rejects_colliding_detail_filenames() -> None:
    collision = EntityDetail("A/B", "project", "one.md")
    same = EntityDetail("A-B", "project", "two.md")
    with pytest.raises(ValueError):
        _build(project_details=(collision, same))


def test_pages_escape_dynamic_text_and_ban_script_and_forms() -> None:
    evil_project = ProjectRow("<script>alert(1)</script>", "X.md")
    evil_attention = (AttentionRef("blocked", "high", "<script>x</script>", "Y.md", "<b>bold</b>"),)
    pages = _build(project_rows=(evil_project,), attention=evil_attention)
    for page in pages:
        assert "<script" not in page.content.lower()
        assert "<form" not in page.content.lower()


def test_full_build_is_deterministic() -> None:
    data = dict(
        project_rows=(PROJECT,),
        person_rows=(PERSON,),
        workday=WORKDAY,
        attention=ATTENTION,
        project_details=(PROJECT_DETAIL,),
        person_details=(PERSON_DETAIL,),
    )
    assert [page.content for page in _build(**data)] == [page.content for page in _build(**data)]
