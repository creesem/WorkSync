"""The weekly walkthrough: a reproducible generated artifact.

Rendered deterministically from current records for a fixed ``(vault, today)`` and
written through the generated-zone rules — contained, never a canonical write, never
hand-edited, and never a source of truth. Overwriting an existing packet requires
explicit confirmation. No placeholder text is emitted for an empty section.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp, MutationError
from worksync.work.dates import parse_iso_date
from worksync.work.render import render_attention, render_projects_review, render_team_review
from worksync.work.repository import WorkIndex
from worksync.work.review import AttentionKind, attention_items, person_workloads, project_reviews

GENERATOR = "worksync"
GENERATED_ZONE = "generated"
WALKTHROUGH_FILENAME = "Weekly Walkthrough.md"
WALKTHROUGH_SECTIONS = (
    "team_updates",
    "prior_action_items",
    "operations",
    "projects",
    "waiting_on",
    "action_items",
)
DEADLINE_HORIZON_DAYS = 7
ACTIVE_ACTION_STATUSES = {"open", "in_progress", "waiting", "watch", "parked"}


@dataclass(frozen=True)
class Walkthrough:
    """One rendered, provenance-carrying weekly packet."""

    filename: str
    content: str
    sections: tuple[str, ...] = WALKTHROUGH_SECTIONS


def build_walkthrough(index: WorkIndex, *, today: date) -> Walkthrough:
    """Render the weekly packet deterministically for a fixed vault and date."""
    body = "\n\n".join(
        (
            _render_team_updates(index, today),
            _render_prior_action_items(index, today),
            _render_operations(index, today),
            _render_projects(index, today),
            _render_waiting_on(index, today),
            _render_action_items(index, today),
        )
    )
    content = _with_provenance(today, body)
    return Walkthrough(filename=WALKTHROUGH_FILENAME, content=content)


def write_walkthrough(
    walkthrough: Walkthrough,
    zones: dict[str, Path],
    *,
    confirmed: bool = False,
    force: bool = False,
    now=None,
) -> CommitResult:
    """Write the packet into the generated zone; overwriting requires confirmation."""
    root = Path(zones[GENERATED_ZONE])
    existing = root / walkthrough.filename
    if existing.is_file():
        if not confirmed:
            raise MutationError(
                "needs_confirmation",
                f"Overwriting an existing packet requires confirmation: {walkthrough.filename}",
            )
        op = FileOp(
            "update",
            Path(walkthrough.filename),
            GENERATED_ZONE,
            content=walkthrough.content,
            expected=sha256_file(existing),
        )
    else:
        op = FileOp("create", Path(walkthrough.filename), GENERATED_ZONE, content=walkthrough.content)
    return commit(ChangeSet("regen_walkthrough", (op,)), zones, force=force, now=now)


def _with_provenance(today: date, body: str) -> str:
    header = [
        "---",
        "generated: walkthrough",
        f"generator: {GENERATOR}",
        f"reference_date: {today.isoformat()}",
        "sources:",
        "  - review.team",
        "  - review.projects",
        "  - review.attention",
        "---",
        "",
        f"# Weekly walkthrough — {today.isoformat()}",
        "",
    ]
    return "\n".join(header) + body + "\n"


def _render_team_updates(index: WorkIndex, today: date) -> str:
    return "## Team updates\n\n" + render_team_review(person_workloads(index, today))


def _render_prior_action_items(index: WorkIndex, today: date) -> str:
    items = tuple(item for item in attention_items(index, today) if item.kind == AttentionKind.OVERDUE_ACTION.value)
    return "## Prior action items\n\n" + render_attention("Overdue", items)


def _render_operations(index: WorkIndex, today: date) -> str:
    items = tuple(item for item in attention_items(index, today) if item.severity == "high")
    return "## Operations\n\n" + render_attention("High severity", items)


def _render_projects(index: WorkIndex, today: date) -> str:
    return "## Projects\n\n" + render_projects_review(project_reviews(index, today))


def _render_waiting_on(index: WorkIndex, today: date) -> str:
    items = tuple(item for item in attention_items(index, today) if item.kind == AttentionKind.WAITING.value)
    return "## Waiting on\n\n" + render_attention("Waiting", items)


def _render_action_items(index: WorkIndex, today: date) -> str:
    horizon = today + timedelta(days=DEADLINE_HORIZON_DAYS)
    rows: list[str] = []
    for action in index.list_type("action"):
        if action.status not in ACTIVE_ACTION_STATUSES:
            continue
        due = parse_iso_date(getattr(action, "due", None))
        if due is not None and due.date() <= horizon:
            rows.append(f"  {due.date().isoformat()}  {action.title} ({action.path})")
    rows.sort()
    return "## Action items / deadlines\n\n" + ("\n".join(rows) if rows else "  (none)")


__all__ = ["WALKTHROUGH_FILENAME", "WALKTHROUGH_SECTIONS", "Walkthrough", "build_walkthrough", "write_walkthrough"]
