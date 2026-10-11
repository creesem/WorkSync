"""The read-only project control center.

Composes the four lifecycle machines' current state (joined through the registry) with
the existing ``work.review`` rollups and authoritative links. It leads with unresolved
outcomes and the next decision rather than raw activity volume, and it never writes: this
module imports no ``safety``, ``context``, or ``html``, and reaches no write helper.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from worksync.work.lifecycle.loader import LifecycleRecord
from worksync.work.lifecycle.records import RecordKind
from worksync.work.models import EntityBase
from worksync.work.render import attention_to_dict
from worksync.work.repository import WorkIndex, issue_to_dict
from worksync.work.review import attention_items

ISSUE_RESOLVED = frozenset({"verified", "rejected"})
DELIVERY_RESOLVED = frozenset({"accepted", "accepted_exception"})
DATE_UNRESOLVED = frozenset({"stale-missed", "needs-date"})
COMMUNICATIONS_DEFERRED = "communications are deferred (email intake is out of 0.1)"

NEXT_ACTIONS: dict[tuple[str, str], str] = {
    ("issue", "reported"): "Confirm or reject the reported issue",
    ("issue", "confirmed"): "Start the fix",
    ("issue", "fixing"): "Record the fix",
    ("issue", "fixed"): "Start the retest",
    ("issue", "retesting"): "Verify the retest",
    ("issue", "deferred"): "Reopen or close the deferred issue",
    ("delivery", "untracked"): "Mark the build complete",
    ("delivery", "build_complete"): "Mark ready for testing",
    ("delivery", "ready_for_testing"): "Start testing",
    ("delivery", "testing"): "Record the tester's result",
    ("delivery", "defect_found"): "Record the fix",
    ("delivery", "fix_reported"): "Request a retest",
    ("delivery", "retest_pending"): "Start the retest",
    ("date_gap", "needs-date"): "Obtain the date",
    ("date_gap", "stale-missed"): "Revise the missed date",
    ("waiting_on", "open"): "Follow up on the dependency",
}


def build_control_center(
    index: WorkIndex, project: EntityBase, records: Iterable[LifecycleRecord], *, today: date
) -> dict:
    """Build the read-only control center for one project from joined lifecycle records."""
    ordered = tuple(sorted(records, key=lambda record: (record.kind, record.entity.title.casefold(), record.record_id)))
    by_kind: dict[str, list[LifecycleRecord]] = {}
    for record in ordered:
        by_kind.setdefault(record.kind, []).append(record)

    issues = by_kind.get(RecordKind.ISSUE.value, [])
    testing = by_kind.get(RecordKind.DELIVERY.value, [])
    dates = by_kind.get(RecordKind.DATE_GAP.value, [])
    waiting = by_kind.get(RecordKind.WAITING_ON.value, [])
    decisions = by_kind.get(RecordKind.DECISION.value, [])

    unresolved = _unresolved(issues, testing, dates, waiting)
    record_paths = {record.record_id for record in ordered} | {project.path}
    attention = [attention_to_dict(item) for item in attention_items(index, today) if item.path in record_paths]
    errors = [issue_to_dict(item) for item in index.errors if item.path in record_paths]

    return {
        "project": {
            "project_id": getattr(project, "project_id", None),
            "title": project.title,
            "status": project.status,
            "path": project.path,
            "next_review": getattr(project, "next_review", None),
        },
        "summary": {
            "unresolved_outcomes": unresolved,
            "next_decision": _next_decision(project, issues, testing, dates, waiting),
            "counts": {
                "issues": len(issues),
                "testing": len(testing),
                "dates": len(dates),
                "waiting_on": len(waiting),
                "decisions": len(decisions),
            },
        },
        "issues": [_record_dict(record) for record in issues],
        "testing": [_record_dict(record) for record in testing],
        "dates": [_record_dict(record) for record in dates],
        "decisions": [_record_dict(record) for record in decisions],
        "communications": [],
        "waiting_on": [_record_dict(record) for record in waiting],
        "update_candidates": [],
        "health": {"attention": attention, "errors": errors},
        "timeline": _timeline(ordered),
    }


def render_control_center(report: dict) -> str:
    """Render the control center as deterministic text, leading with the next decision."""
    project = report["project"]
    summary = report["summary"]
    lines = [f"# {project['title']} — control center", f"status: {project['status'] or '-'}"]
    lines.append(f"next decision: {summary['next_decision'] or '-'}")
    lines.append(f"unresolved outcomes: {len(summary['unresolved_outcomes'])}")
    lines.extend(f"  - {item}" for item in summary["unresolved_outcomes"])
    for label, key in (
        ("Issues", "issues"),
        ("Testing/reports", "testing"),
        ("Dates", "dates"),
        ("Waiting on", "waiting_on"),
        ("Decisions", "decisions"),
    ):
        lines.append(f"{label} ({len(report[key])})")
        lines.extend(f"  [{row['state']}] {row['title']} ({row['path']})" for row in report[key])
    lines.append(f"Timeline ({len(report['timeline'])})")
    lines.extend(
        f"  {row['at']} {row['from_state']} -> {row['to_state']} ({row['record_id']})" for row in report["timeline"]
    )
    return "\n".join(lines)


def _record_dict(record: LifecycleRecord) -> dict:
    return {
        "record_id": record.record_id,
        "kind": record.kind,
        "state": record.state,
        "title": record.entity.title,
        "path": record.entity.path,
        "links": list(record.provenance),
    }


def _unresolved(
    issues: list[LifecycleRecord],
    testing: list[LifecycleRecord],
    dates: list[LifecycleRecord],
    waiting: list[LifecycleRecord],
) -> list[str]:
    outcomes: list[str] = []
    outcomes.extend(
        f"issue: {record.entity.title} ({record.state})" for record in issues if record.state not in ISSUE_RESOLVED
    )
    outcomes.extend(
        f"report: {record.entity.title} ({record.state})" for record in testing if record.state not in DELIVERY_RESOLVED
    )
    outcomes.extend(
        f"date: {record.entity.title} ({record.state})" for record in dates if record.state in DATE_UNRESOLVED
    )
    outcomes.extend(
        f"waiting-on: {record.entity.title} ({record.state})" for record in waiting if record.state != "resolved"
    )
    return outcomes


def _next_decision(
    project: EntityBase,
    issues: list[LifecycleRecord],
    testing: list[LifecycleRecord],
    dates: list[LifecycleRecord],
    waiting: list[LifecycleRecord],
) -> str | None:
    explicit = str(getattr(project, "next_action", None) or "").strip()
    if explicit:
        return explicit
    for record in (*issues, *testing, *dates, *waiting):
        suggestion = NEXT_ACTIONS.get((record.kind, record.state))
        if suggestion:
            return f"{suggestion}: {record.entity.title}"
    return None


def _timeline(records: tuple[LifecycleRecord, ...]) -> list[dict]:
    entries: list[dict] = []
    for record in records:
        for transition in record.transitions:
            entries.append(
                {
                    "at": transition.at,
                    "record_id": record.record_id,
                    "actor": transition.actor,
                    "reason": transition.reason,
                    "from_state": transition.from_state,
                    "to_state": transition.to_state,
                    "evidence": transition.evidence,
                }
            )
    entries.sort(key=lambda entry: (entry["at"], entry["record_id"], entry["to_state"]))
    return entries


__all__ = ["build_control_center", "render_control_center"]
