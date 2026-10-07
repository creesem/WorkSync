"""Pure, deterministic rendering of the generated HTML interface.

The generator receives already-resolved structured values (entity references, the
vault name, and a reference time) and returns self-contained ``GeneratedPage``
objects. It performs no I/O, resolves no vault paths, imports no ``context``, and
emits no JavaScript and no forms, so HTML Reader's safe mode renders it.

Every page builder is a pure function of its inputs plus ``today`` and
``generated_at``. ``build_pages`` renders the whole set in a fixed order and links to a
generated page only when that page is part of the built set; a reference with no
canonical note path is rendered as plain text rather than as a broken link.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from worksync.core.names import safe_name
from worksync.html.links import attr, external_url, note_url, page_url, text

GENERATOR = "worksync"
DETAIL_DIRS = {"project": "project", "person": "person"}
SLOT_LABELS = {
    "must_win": "Must win",
    "support_one": "Support one",
    "support_two": "Support two",
    "unblock": "Unblock",
    "quick_win": "Quick win",
}

_STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; line-height: 1.5;
       max-width: 56rem; margin: 2rem auto; padding: 0 1.25rem; }
.generated-marker { border: 1px dashed #c2410c; background: #fff7ed; color: #7c2d12;
                    padding: .5rem .75rem; border-radius: .5rem; font-size: .85rem; }
h1 { font-size: 1.5rem; margin-bottom: .25rem; }
section { margin: 1.5rem 0; }
ul { list-style: none; padding-left: 0; }
li { padding: .25rem 0; border-bottom: 1px solid #e4e4e7; }
.status { color: #52525b; font-size: .85rem; margin-left: .5rem; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1rem; margin: 0; }
dt { font-weight: 600; }
dd { margin: 0; }
footer { margin-top: 2rem; color: #52525b; font-size: .85rem; }
""".strip()


@dataclass(frozen=True)
class GeneratedPage:
    """One rendered, provenance-carrying page ready to write."""

    name: str
    filename: str
    content: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Navigation:
    """One entry in the home page's interface index."""

    label: str
    page_path: str


@dataclass(frozen=True)
class EntityLink:
    """A resolved reference to a canonical note, with optional display detail."""

    title: str
    note_path: str
    status: str = ""
    detail: str = ""
    kind: str = ""


@dataclass(frozen=True)
class AttentionRef:
    """One derived attention or waiting signal."""

    kind: str
    severity: str
    title: str
    note_path: str
    reason: str


@dataclass(frozen=True)
class WorkdaySlot:
    """One of the five workday slots, with its selected task when set."""

    slot: str
    task: EntityLink | None = None


@dataclass(frozen=True)
class WorkdayPlan:
    """The dated five-slot plan, as plain values."""

    date: str
    slots: tuple[WorkdaySlot, ...] = ()


@dataclass(frozen=True)
class ProjectRow:
    """A project row for the Projects surface."""

    title: str
    note_path: str
    status: str = ""
    priority: str = ""
    owner: str = ""
    health: str = ""


@dataclass(frozen=True)
class PersonRow:
    """A person row for the Team surface."""

    title: str
    note_path: str
    role: str = ""
    projects: int = 0
    tickets: int = 0
    actions: int = 0
    attention: int = 0


@dataclass(frozen=True)
class DetailSection:
    """One titled section of an entity detail page."""

    title: str
    links: tuple[EntityLink, ...] = ()
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityDetail:
    """Structured fields and related links for one project or person page."""

    title: str
    kind: str
    note_path: str
    fields: tuple[tuple[str, str], ...] = ()
    sections: tuple[DetailSection, ...] = ()


def build_home(
    *,
    vault_name: str,
    projects: tuple[EntityLink, ...] = (),
    people: tuple[EntityLink, ...] = (),
    nav: tuple[Navigation, ...] = (),
    existing: frozenset[str] = frozenset(),
    external_links: tuple[tuple[str, str], ...] = (),
    today: date,
    generated_at: datetime,
) -> GeneratedPage:
    """Render the interface home page deterministically."""
    projects = _sorted_links(projects)
    people = _sorted_links(people)
    body = ["<h1>WorkSync</h1>", _marker(vault_name, today)]
    nav_html = _nav_section(nav, existing=existing, vault_name=vault_name)
    if nav_html:
        body.append(nav_html)
    body.append(_entity_section("Projects", projects, vault_name=vault_name, empty="No active projects."))
    body.append(_entity_section("Team", people, vault_name=vault_name, empty="No active people."))
    if external_links:
        body.append(_external_section(external_links))
    sources = tuple(sorted({link.note_path for link in (*projects, *people) if link.note_path}))
    content = _page(
        title=f"{vault_name} — WorkSync",
        body="\n".join(body),
        vault_name=vault_name,
        today=today,
        generated_at=generated_at,
        sources=sources,
    )
    return GeneratedPage(name="home", filename="index.html", content=content, sources=sources)


def build_today(
    *,
    vault_name: str,
    plan: WorkdayPlan | None = None,
    attention: tuple[AttentionRef, ...] = (),
    today: date,
    generated_at: datetime,
) -> GeneratedPage:
    """Render the Today/Workday surface: the plan, attention, and waiting work."""
    body = ["<h1>Today</h1>", _marker(vault_name, today)]
    if plan is None:
        body.append("<p>No workday plan.</p>")
        plan_sources: set[str] = set()
    else:
        plan_sources = {slot.task.note_path for slot in plan.slots if slot.task and slot.task.note_path}
        if plan.date:
            body.append(f"<p>Workday plan for {text(plan.date)}.</p>")
        body.append(_workday_section(plan, vault_name=vault_name))
    non_waiting = tuple(item for item in attention if item.kind != "waiting")
    waiting = tuple(item for item in attention if item.kind == "waiting")
    body.append(_attention_section("Attention", non_waiting, vault_name=vault_name))
    body.append(_attention_section("Waiting", waiting, vault_name=vault_name))
    sources = tuple(sorted(plan_sources | {item.note_path for item in attention if item.note_path}))
    content = _page(
        title=f"{vault_name} — Today",
        body="\n".join(body),
        vault_name=vault_name,
        today=today,
        generated_at=generated_at,
        sources=sources,
    )
    return GeneratedPage(name="today", filename="today.html", content=content, sources=sources)


def build_projects(
    *,
    vault_name: str,
    rows: tuple[ProjectRow, ...] = (),
    existing: frozenset[str] = frozenset(),
    today: date,
    generated_at: datetime,
) -> GeneratedPage:
    """Render the Projects surface; each row links to its detail page when built."""
    rows = tuple(sorted(rows, key=lambda row: (row.title.casefold(), row.note_path)))
    body = ["<h1>Projects</h1>", _marker(vault_name, today)]
    lines = [f"<section><h2>Active projects ({len(rows)})</h2>"]
    if not rows:
        lines.append("<p>No active projects.</p>")
    else:
        lines.append("<ul>")
        for row in rows:
            link = _link_html(
                vault_name,
                EntityLink(row.title, row.note_path, status=row.status, kind="project"),
                existing=existing,
            )
            meta = " · ".join(part for part in (row.priority, row.owner, row.health) if part)
            meta_html = f'<span class="status">{text(meta)}</span>' if meta else ""
            lines.append(f"<li>{link}{meta_html}</li>")
        lines.append("</ul>")
    lines.append("</section>")
    body.append("\n".join(lines))
    sources = tuple(sorted({row.note_path for row in rows if row.note_path}))
    content = _page(
        title=f"{vault_name} — Projects",
        body="\n".join(body),
        vault_name=vault_name,
        today=today,
        generated_at=generated_at,
        sources=sources,
    )
    return GeneratedPage(name="projects", filename="projects.html", content=content, sources=sources)


def build_team(
    *,
    vault_name: str,
    rows: tuple[PersonRow, ...] = (),
    existing: frozenset[str] = frozenset(),
    today: date,
    generated_at: datetime,
) -> GeneratedPage:
    """Render the Team surface; each row links to its detail page when built."""
    rows = tuple(sorted(rows, key=lambda row: (row.title.casefold(), row.note_path)))
    body = ["<h1>Team</h1>", _marker(vault_name, today)]
    lines = [f"<section><h2>Active people ({len(rows)})</h2>"]
    if not rows:
        lines.append("<p>No active people.</p>")
    else:
        lines.append("<ul>")
        for row in rows:
            link = _link_html(
                vault_name,
                EntityLink(row.title, row.note_path, status=row.role, kind="person"),
                existing=existing,
            )
            meta = (
                f"{row.projects} projects · {row.tickets} tickets · {row.actions} actions · {row.attention} attention"
            )
            lines.append(f'<li>{link}<span class="status">{text(meta)}</span></li>')
        lines.append("</ul>")
    lines.append("</section>")
    body.append("\n".join(lines))
    sources = tuple(sorted({row.note_path for row in rows if row.note_path}))
    content = _page(
        title=f"{vault_name} — Team",
        body="\n".join(body),
        vault_name=vault_name,
        today=today,
        generated_at=generated_at,
        sources=sources,
    )
    return GeneratedPage(name="team", filename="team.html", content=content, sources=sources)


def build_detail(
    detail: EntityDetail,
    *,
    vault_name: str,
    existing: frozenset[str] = frozenset(),
    today: date,
    generated_at: datetime,
) -> GeneratedPage:
    """Render one project or person detail page from structured fields and links."""
    filename = _detail_path(detail.kind, detail.title)
    body = [f"<h1>{text(detail.title)}</h1>", _marker(vault_name, today)]
    if detail.note_path:
        body.append(
            '<p class="source">Source: '
            f'<a href="{attr(note_url(vault_name, detail.note_path))}">{text(detail.note_path)}</a></p>'
        )
    if detail.fields:
        field_lines = ["<section><h2>Details</h2>", "<dl>"]
        for label, value in detail.fields:
            field_lines.append(f"<dt>{text(label)}</dt><dd>{text(value)}</dd>")
        field_lines.append("</dl></section>")
        body.append("\n".join(field_lines))
    for section in detail.sections:
        body.append(_detail_section(section, vault_name=vault_name, existing=existing))
    sources = {detail.note_path} if detail.note_path else set()
    sources.update(link.note_path for section in detail.sections for link in section.links if link.note_path)
    source_tuple = tuple(sorted(sources))
    content = _page(
        title=f"{vault_name} — {detail.title}",
        body="\n".join(body),
        vault_name=vault_name,
        today=today,
        generated_at=generated_at,
        sources=source_tuple,
    )
    return GeneratedPage(name=f"{detail.kind}:{detail.title}", filename=filename, content=content, sources=source_tuple)


def build_pages(
    *,
    vault_name: str,
    projects: tuple[EntityLink, ...] = (),
    people: tuple[EntityLink, ...] = (),
    project_rows: tuple[ProjectRow, ...] = (),
    person_rows: tuple[PersonRow, ...] = (),
    workday: WorkdayPlan | None = None,
    attention: tuple[AttentionRef, ...] = (),
    project_details: tuple[EntityDetail, ...] = (),
    person_details: tuple[EntityDetail, ...] = (),
    external_links: tuple[tuple[str, str], ...] = (),
    today: date,
    generated_at: datetime,
) -> tuple[GeneratedPage, ...]:
    """Render every page of the interface in a fixed order.

    The set of built filenames is computed first so a page never links to a target
    that is not part of the built set.
    """
    details = (*_sorted_details(project_details), *_sorted_details(person_details))
    detail_paths = [_detail_path(detail.kind, detail.title) for detail in details]
    if len(set(detail_paths)) != len(detail_paths):
        raise ValueError("Generated detail pages collide on the same filename.")
    existing = frozenset(
        {
            "index.html",
            "today.html",
            "projects.html",
            "team.html",
            *detail_paths,
        }
    )
    nav = (
        Navigation("Today", "today.html"),
        Navigation("Projects", "projects.html"),
        Navigation("Team", "team.html"),
    )
    home = build_home(
        vault_name=vault_name,
        projects=projects,
        people=people,
        nav=nav,
        existing=existing,
        external_links=external_links,
        today=today,
        generated_at=generated_at,
    )
    pages = [
        home,
        build_today(vault_name=vault_name, plan=workday, attention=attention, today=today, generated_at=generated_at),
        build_projects(
            vault_name=vault_name, rows=project_rows, existing=existing, today=today, generated_at=generated_at
        ),
        build_team(vault_name=vault_name, rows=person_rows, existing=existing, today=today, generated_at=generated_at),
    ]
    pages.extend(
        build_detail(detail, vault_name=vault_name, existing=existing, today=today, generated_at=generated_at)
        for detail in details
    )
    return tuple(pages)


def _detail_path(kind: str, title: str) -> str:
    directory = DETAIL_DIRS.get(kind)
    if directory is None:
        raise ValueError(f"Unsupported detail kind: {kind}")
    return f"{directory}/{safe_name(title, fallback='untitled')}.html"


def _page(*, title: str, body: str, vault_name: str, today: date, generated_at: datetime, sources: tuple) -> str:
    head = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{text(title)}</title>",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta name="generator" content="{text(GENERATOR)}">',
        f'<meta name="worksync-reference-date" content="{attr(today.isoformat())}">',
        f'<meta name="worksync-generated-at" content="{attr(generated_at.isoformat())}">',
        f'<meta name="worksync-vault" content="{attr(vault_name)}">',
        f'<meta name="worksync-sources" content="{attr(", ".join(sources))}">',
        f"<style>{_STYLE}</style>",
        "</head>",
        "<body>",
    ]
    tail = [
        '<footer><a href="https://help.obsidian.md">Obsidian help</a> — rendered by WorkSync; '
        "regenerate rather than edit.</footer>",
        "</body>",
        "</html>",
    ]
    return "\n".join([*head, body, *tail]) + "\n"


def _marker(vault_name: str, today: date) -> str:
    return (
        '<p class="generated-marker">Generated by WorkSync for '
        f"{text(vault_name)} — do not edit. Reference date {today.isoformat()}.</p>"
    )


def _nav_section(nav: tuple[Navigation, ...], *, existing: frozenset[str], vault_name: str) -> str:
    links = [link for link in nav if link.page_path in existing]
    if not links:
        return ""
    lines = ["<section><h2>Interface</h2>", "<ul>"]
    for link in links:
        lines.append(f'<li><a href="{attr(page_url(vault_name, link.page_path))}">{text(link.label)}</a></li>')
    lines.append("</ul></section>")
    return "\n".join(lines)


def _workday_section(plan: WorkdayPlan, *, vault_name: str) -> str:
    lines = ["<section><h2>Workday plan</h2>", "<ul>"]
    for slot in plan.slots:
        label = text(SLOT_LABELS.get(slot.slot, slot.slot))
        if slot.task is None:
            lines.append(f'<li><strong>{label}</strong>: <span class="status">(open)</span></li>')
            continue
        link = _link_html(vault_name, slot.task, existing=frozenset())
        detail = f'<span class="status">{text(slot.task.detail)}</span>' if slot.task.detail else ""
        lines.append(f"<li><strong>{label}</strong>: {link}{detail}</li>")
    lines.append("</ul></section>")
    return "\n".join(lines)


def _attention_section(title: str, items: tuple[AttentionRef, ...], *, vault_name: str) -> str:
    lines = [f"<section><h2>{text(title)} ({len(items)})</h2>"]
    if not items:
        lines.append("<p>(none)</p>")
    else:
        lines.append("<ul>")
        for item in items:
            lines.append(
                f"<li>{_note_link_html(vault_name, item.title, item.note_path)}"
                f'<span class="status">{text(item.severity)} · {text(item.kind)}</span> — '
                f"{text(item.reason)}</li>"
            )
        lines.append("</ul>")
    lines.append("</section>")
    return "\n".join(lines)


def _detail_section(section: DetailSection, *, vault_name: str, existing: frozenset[str]) -> str:
    lines = [f"<section><h2>{text(section.title)} ({len(section.links)})</h2>"]
    if section.links:
        lines.append("<ul>")
        lines.extend(
            f"<li>{_link_html(vault_name, link, existing=existing)}</li>" for link in _sorted_links(section.links)
        )
        lines.append("</ul>")
    if section.lines:
        lines.append("<ul>")
        lines.extend(f"<li>{text(line)}</li>" for line in section.lines)
        lines.append("</ul>")
    if not section.links and not section.lines:
        lines.append("<p>(none)</p>")
    lines.append("</section>")
    return "\n".join(lines)


def _entity_section(title: str, links: tuple[EntityLink, ...], *, vault_name: str, empty: str) -> str:
    lines = [f"<section><h2>{text(title)} ({len(links)})</h2>"]
    if not links:
        lines.append(f"<p>{text(empty)}</p>")
    else:
        lines.append("<ul>")
        for link in links:
            detail = f" {text(link.detail)}" if link.detail else ""
            status = f'<span class="status">{text(link.status)}</span>' if link.status else ""
            lines.append(f"<li>{_note_link_html(vault_name, link.title, link.note_path)}{status}{detail}</li>")
        lines.append("</ul>")
    lines.append("</section>")
    return "\n".join(lines)


def _external_section(links: tuple[tuple[str, str], ...]) -> str:
    lines = ["<section><h2>Links</h2>", "<ul>"]
    for label, url in links:
        lines.append(f'<li><a href="{attr(external_url(url))}">{text(label)}</a></li>')
    lines.append("</ul></section>")
    return "\n".join(lines)


def _link_html(vault_name: str, link: EntityLink, *, existing: frozenset[str]) -> str:
    label = text(link.title)
    href = _href(vault_name, link, existing=existing)
    status = f'<span class="status">{text(link.status)}</span>' if link.status else ""
    if href is None:
        return f"{label}{status}"
    return f'<a href="{attr(href)}">{label}</a>{status}'


def _note_link_html(vault_name: str, label: str, note_path: str) -> str:
    if not note_path:
        return text(label)
    return f'<a href="{attr(note_url(vault_name, note_path))}">{text(label)}</a>'


def _href(vault_name: str, link: EntityLink, *, existing: frozenset[str]) -> str | None:
    if link.kind in DETAIL_DIRS:
        candidate = _detail_path(link.kind, link.title)
        if candidate in existing:
            return page_url(vault_name, candidate)
    if link.note_path:
        return note_url(vault_name, link.note_path)
    return None


def _sorted_links(links: tuple[EntityLink, ...]) -> tuple[EntityLink, ...]:
    return tuple(sorted(links, key=lambda link: (link.title.casefold(), link.note_path)))


def _sorted_details(details: tuple[EntityDetail, ...]) -> tuple[EntityDetail, ...]:
    return tuple(sorted(details, key=lambda detail: (detail.title.casefold(), detail.note_path)))
