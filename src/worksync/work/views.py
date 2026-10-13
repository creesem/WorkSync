"""Generated, reproducible work views and their contained, gated writer.

Views are derived artifacts: rendered from the read-only work index of entities,
relationships, and attention, then written only into the contained ``views`` zone.
Rendering is deterministic for a fixed ``today`` and ``generated_at``; a write requires
explicit confirmation, refuses an existing view without ``force``, and never touches a
canonical note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from worksync.core.names import safe_name
from worksync.core.paths import PathSafetyError
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp, MutationError
from worksync.safety.zones import write_zones
from worksync.work.models import EntityType
from worksync.work.render import render_attention, render_projects_review, render_team_review
from worksync.work.repository import WorkIndex
from worksync.work.review import (
    AttentionKind,
    attention_by_path,
    attention_items,
    person_workloads,
    project_reviews,
)

GENERATOR = "worksync"
VIEW_ZONE = "views"
VIEW_NAMES = ("today", "projects", "team", "tickets", "waiting", "manager-review")
VIEW_TITLES = {
    "today": "Today",
    "projects": "Projects",
    "team": "Team",
    "tickets": "Tickets",
    "waiting": "Waiting",
    "manager-review": "Manager Review",
}
VIEW_SOURCES = {
    "today": ("attention_items",),
    "projects": ("active_projects", "build_project_review", "attention_items"),
    "team": ("active_people", "build_person_workload", "attention_items"),
    "tickets": ("list_type:ticket", "attention_items"),
    "waiting": ("attention_items",),
    "manager-review": ("attention_items", "active_projects", "build_project_review"),
}


@dataclass(frozen=True)
class GeneratedView:
    """One rendered, provenance-carrying view."""

    name: str
    filename: str
    content: str
    sources: tuple[str, ...]


def build_view(index: WorkIndex, name: str, *, today: date, generated_at: datetime) -> GeneratedView:
    """Render one named view deterministically for *today* and *generated_at*."""
    if name not in VIEW_NAMES:
        raise ValueError(f"Unknown view: {name}")
    sources = VIEW_SOURCES[name]
    body = _BODIES[name](index, today)
    content = _with_provenance(name, sources, today, generated_at, body)
    return GeneratedView(name=name, filename=f"{safe_name(VIEW_TITLES[name])}.md", content=content, sources=sources)


def build_views(index: WorkIndex, *, today: date, generated_at: datetime) -> tuple[GeneratedView, ...]:
    """Render every view in a fixed order."""
    return tuple(build_view(index, name, today=today, generated_at=generated_at) for name in VIEW_NAMES)


def view_zones(runtime_root: str | Path, *, vault_root: str | Path | None = None) -> dict[str, Path]:
    """Return the writable roots for generated views, refusing a root inside the vault."""
    runtime = Path(runtime_root).expanduser().resolve()
    vault = Path(vault_root).expanduser().resolve() if vault_root is not None else runtime
    views = write_zones(vault, runtime)["views"]
    if vault_root is not None and (views == vault or views.is_relative_to(vault)):
        raise PathSafetyError(f"Generated views root must stay outside the vault: {views}")
    return {"views": views, "runtime": runtime}


def write_views(
    views: tuple[GeneratedView, ...],
    zones: dict[str, Path],
    *,
    confirmed: bool = False,
    force: bool = False,
    now: datetime | None = None,
) -> CommitResult:
    """Write rendered views as one derived transaction; no canonical note is touched."""
    if not views:
        raise MutationError("invalid_op", "A view write requires at least one view.")
    if not confirmed:
        raise MutationError("needs_confirmation", "Writing generated views requires explicit confirmation.")
    root = Path(zones[VIEW_ZONE])
    ops: list[FileOp] = []
    for view in views:
        existing = root / view.filename
        if existing.is_file():
            ops.append(
                FileOp("update", Path(view.filename), VIEW_ZONE, content=view.content, expected=sha256_file(existing))
            )
        else:
            ops.append(FileOp("create", Path(view.filename), VIEW_ZONE, content=view.content))
    return commit(ChangeSet("regen_view", tuple(ops)), zones, force=force, now=now)


def _with_provenance(name: str, sources: tuple[str, ...], today: date, generated_at: datetime, body: str) -> str:
    header = [
        "---",
        f"view: {name}",
        f"generator: {GENERATOR}",
        f"reference_date: {today.isoformat()}",
        f"generated_at: {generated_at.isoformat()}",
        "sources:",
        *[f"  - {source}" for source in sources],
        "---",
        "",
    ]
    return "\n".join(header) + body + "\n"


def _render_today(index: WorkIndex, today: date) -> str:
    return render_attention("Today", attention_items(index, today))


def _render_projects(index: WorkIndex, today: date) -> str:
    return render_projects_review(project_reviews(index, today))


def _render_team(index: WorkIndex, today: date) -> str:
    return render_team_review(person_workloads(index, today))


def _render_tickets(index: WorkIndex, today: date) -> str:
    tickets = index.list_type(EntityType.TICKET.value)
    by_path = attention_by_path(index, today)
    lines = [f"# Tickets ({len(tickets)})"]
    for ticket in tickets:
        lines.append(f"{ticket.status or '-':<12} {ticket.title} ({ticket.path})")
        lines.extend(f"    [{item.severity}] {item.kind} — {item.reason}" for item in by_path.get(ticket.path, ()))
    if not tickets:
        lines.append("  (none)")
    return "\n".join(lines)


def _render_waiting(index: WorkIndex, today: date) -> str:
    items = tuple(item for item in attention_items(index, today) if item.kind == AttentionKind.WAITING.value)
    return render_attention("Waiting", items)


def _render_manager_review(index: WorkIndex, today: date) -> str:
    high = tuple(item for item in attention_items(index, today) if item.severity == "high")
    return "\n".join(
        [
            render_attention("Manager review — high severity", high),
            "",
            render_projects_review(project_reviews(index, today)),
        ]
    )


_BODIES = {
    "today": _render_today,
    "projects": _render_projects,
    "team": _render_team,
    "tickets": _render_tickets,
    "waiting": _render_waiting,
    "manager-review": _render_manager_review,
}
