"""Five-slot workday plan: selection, steering, ranking, persistence, and import.

The plan is a human-curated daily view over the canonical active actions, never a second
action store. It is persisted as derived runtime state, is dated, and never carries
yesterday's selections or steering into a new workday. Reading ignores stale persisted
references; writing rejects them. Ranking is deterministic for a fixed ``today``,
selected set, and steering, and always carries human-readable reasons.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from worksync.safety.derived import write_json
from worksync.safety.files import sha256_file
from worksync.work.models import EntityBase
from worksync.work.repository import WorkIndex
from worksync.work.schema import priority_rank
from worksync.work.writer import complete_action

SLOTS = ("must_win", "support_one", "support_two", "unblock", "quick_win")
ACTIVE_ACTION_STATUSES = frozenset({"open", "in_progress", "waiting", "watch", "parked"})
MONITORING_STATUSES = frozenset({"waiting", "watch", "parked"})
PLAN_VERSION = 1
PLAN_FILENAME = "workday-plan.json"
NOTE_LIMIT = 240
URGENT_LIMIT = 5
SUGGESTION_LIMIT = 4
_UNBLOCK_WORDS = re.compile(r"\b(follow up|schedule|confirm|contact|provide|forward|engage|obtain|clarify)\b", re.I)


@dataclass(frozen=True)
class Steering:
    """The focus/urgent/note steering persisted with a dated plan."""

    focus_project: str = ""
    urgent_paths: tuple[str, ...] = ()
    note: str = ""


def plan_path(runtime_root: str | Path) -> Path:
    """Return the runtime path holding the workday plan."""
    return Path(runtime_root).expanduser().resolve() / PLAN_FILENAME


def build_workday(index: WorkIndex, *, today: date, runtime_root: str | Path) -> dict:
    """Build the dated plan: validated selections, ranked suggestions, and steering."""
    return _plan_from(index, _load_stored(runtime_root), today=today)


def set_selection(
    index: WorkIndex,
    runtime_root: str | Path,
    slot: str,
    action_path: str,
    *,
    today: date,
    dry_run: bool = False,
) -> dict:
    """Select or clear one slot, rejecting a path that is not a current active action."""
    if slot not in SLOTS:
        raise ValueError(f"Unsupported workday slot: {slot}")
    selections, steering = _current(index, runtime_root, today=today)
    target = str(action_path or "").strip()
    if target and target not in _active_actions(index):
        raise ValueError("Workday selection must be a current active action.")
    selections = {key: value for key, value in selections.items() if value != target}
    if target:
        selections[slot] = target
    else:
        selections.pop(slot, None)
    return _commit_plan(index, runtime_root, today=today, selections=selections, steering=steering, dry_run=dry_run)


def set_steering(
    index: WorkIndex,
    runtime_root: str | Path,
    changes: dict[str, Any],
    *,
    today: date,
    dry_run: bool = False,
) -> dict:
    """Apply focus/urgent/note steering; clearing steering preserves the selected slots."""
    selections, steering = _current(index, runtime_root, today=today)
    active = _active_actions(index)
    projects = _active_projects(active)
    if changes.get("clear"):
        steering = {}
    if "focus_project" in changes:
        focus = str(changes.get("focus_project") or "").strip()
        if focus and focus not in projects:
            raise ValueError("Project focus must reference the current active-action set.")
        steering["focus_project"] = focus
    urgent = [path for path in steering.get("urgent_paths", []) if path in active]
    urgent_path = str(changes.get("urgent_path") or "").strip()
    if urgent_path:
        if urgent_path not in active:
            raise ValueError("Urgent work must be a current active action.")
        urgent = [path for path in urgent if path != urgent_path]
        urgent.insert(0, urgent_path)
    remove = str(changes.get("remove_urgent") or "").strip()
    if remove:
        urgent = [path for path in urgent if path != remove]
    steering["urgent_paths"] = urgent[:URGENT_LIMIT]
    if "note" in changes:
        steering["note"] = str(changes.get("note") or "").strip()[:NOTE_LIMIT]
    return _commit_plan(index, runtime_root, today=today, selections=selections, steering=steering, dry_run=dry_run)


def import_legacy(
    index: WorkIndex,
    runtime_root: str | Path,
    legacy_path: str | Path,
    *,
    today: date,
    dry_run: bool = False,
) -> dict:
    """Map a legacy plan file into the new plan, dropping stale references."""
    try:
        legacy = json.loads(Path(legacy_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Legacy workday plan could not be read: {legacy_path}") from exc
    if not isinstance(legacy, dict):
        raise ValueError("Legacy workday plan must be a JSON object.")

    active = _active_actions(index)
    projects = _active_projects(active)
    kept: list[str] = []
    dropped: list[str] = []
    selections: dict[str, str] = {}
    for slot, path in _as_dict(legacy.get("selections")).items():
        if slot in SLOTS and path in active:
            selections[slot] = path
            kept.append(path)
        elif path:
            dropped.append(path)

    raw_steering = _as_dict(legacy.get("steering"))
    focus = str(raw_steering.get("focus_project") or "").strip()
    if focus and focus not in projects:
        dropped.append(focus)
        focus = ""
    urgent: list[str] = []
    for path in raw_steering.get("urgent_paths") or []:
        if path in active:
            urgent.append(path)
        elif path:
            dropped.append(str(path))
    note = str(raw_steering.get("note") or "")[:NOTE_LIMIT]
    steering = {"focus_project": focus, "urgent_paths": urgent[:URGENT_LIMIT], "note": note}
    plan = _commit_plan(index, runtime_root, today=today, selections=selections, steering=steering, dry_run=dry_run)
    return {"kept": kept, "dropped": dropped, "plan": plan}


def complete_from_plan(
    vault: str | Path,
    runtime_root: str | Path,
    path: str,
    *,
    sha: str,
    reason: str,
    reviewer: str,
    today: date | None = None,
    dry_run: bool = False,
) -> dict:
    """Complete a plan action through the canonical writer and return the refreshed plan."""
    when = today or date.today()
    result = complete_action(
        vault, runtime_root, path, reason=reason, reviewer=reviewer, expected=sha, today=when, dry_run=dry_run
    )
    plan = build_workday(WorkIndex.from_vault(vault), today=when, runtime_root=runtime_root)
    return {
        "completion": {
            "committed": result.committed,
            "dry_run": dry_run,
            "path": result.path,
            "sha": result.sha,
            "journal": str(result.journal) if result.journal is not None else None,
            "changes": [dict(change) for change in result.changes],
        },
        "plan": plan,
    }


def _current(index: WorkIndex, runtime_root: str | Path, *, today: date) -> tuple[dict, dict]:
    """Return today's persisted selections and steering, dropping a prior-day plan."""
    stored = _load_stored(runtime_root)
    if stored.get("date") != today.isoformat():
        return {}, {}
    return _as_dict(stored.get("selections")), _as_dict(stored.get("steering"))


def _commit_plan(
    index: WorkIndex,
    runtime_root: str | Path,
    *,
    today: date,
    selections: dict,
    steering: dict,
    dry_run: bool,
) -> dict:
    stored = {"date": today.isoformat(), "selections": selections, "steering": steering}
    if not dry_run:
        _save(runtime_root, today=today, selections=selections, steering=steering)
    return _plan_from(index, stored, today=today, dry_run=dry_run)


def _plan_from(index: WorkIndex, stored: dict, *, today: date, dry_run: bool = False) -> dict:
    active = _active_actions(index)
    projects = _active_projects(active)
    same_day = stored.get("date") == today.isoformat()
    raw_selections = _as_dict(stored.get("selections")) if same_day else {}
    selections = {slot: path for slot, path in raw_selections.items() if slot in SLOTS and path in active}
    steering = _steering_from(raw_steering=stored.get("steering") if same_day else {}, active=active, projects=projects)
    selected_paths = set(selections.values())
    suggestions = {slot: _rank(slot, active, selected_paths, today, steering, root=index.root) for slot in SLOTS}
    return {
        "date": today.isoformat(),
        "dry_run": dry_run,
        "slots": list(SLOTS),
        "selections": {slot: _action_payload(active[path], index.root) for slot, path in selections.items()},
        "selected_count": len(selections),
        "suggestions": suggestions,
        "steering": {
            "focus_project": steering.focus_project,
            "urgent_paths": list(steering.urgent_paths),
            "note": steering.note,
            "urgent_actions": [_action_payload(active[path], index.root) for path in steering.urgent_paths],
        },
        "projects": sorted(projects, key=str.casefold),
        "active_actions": [
            _action_payload(action, index.root)
            for action in sorted(active.values(), key=lambda entity: entity.title.casefold())
        ],
        "steering_effect": {
            "focus_match_count": _focus_match_count(active, steering.focus_project),
            "urgent_match_count": len(steering.urgent_paths),
        },
    }


def _active_actions(index: WorkIndex) -> dict[str, EntityBase]:
    return {entity.path: entity for entity in index.list_type("action") if entity.status in ACTIVE_ACTION_STATUSES}


def _active_projects(active: dict[str, EntityBase]) -> set[str]:
    return {name for entity in active.values() if (name := _project_name(entity))}


def _rank(
    slot: str,
    active: dict[str, EntityBase],
    selected: set[str],
    today: date,
    steering: Steering,
    *,
    root: Path,
) -> list[dict]:
    today_iso = today.isoformat()
    recent_cutoff = (today - timedelta(days=30)).isoformat()
    focus = steering.focus_project.casefold()
    urgent = set(steering.urgent_paths)
    ranked: list[dict] = []
    for path, action in active.items():
        if path in selected:
            continue
        project = _project_name(action)
        if action.status in MONITORING_STATUSES and slot != "unblock" and path not in urgent:
            continue

        rank = priority_rank(getattr(action, "priority", None))
        number = rank or 99
        score = max(0, 8 - number) * 8
        reasons: list[str] = []
        if path in urgent:
            score += 70
            reasons.append("manually elevated today")
        if focus and project.casefold() == focus:
            score += 45
            reasons.append("today's project focus")
        due = getattr(action, "due", None) or ""
        if due and due < today_iso:
            score += 45
            reasons.append("overdue")
        elif due == today_iso:
            score += 40
            reasons.append("due today")
        elif due and due <= (today + timedelta(days=7)).isoformat():
            score += 30
            reasons.append("due within 7 days")
        elif not due:
            score -= 8
            reasons.append("no due date")
        if rank is not None:
            if number <= 2:
                score += 25 if slot == "must_win" else 15
            reasons.append(getattr(action, "priority", "") or "")
        created = str(action.raw.get("source_date") or action.raw.get("created") or action.raw.get("updated") or "")
        recent_meeting = str(action.raw.get("source") or "").startswith("[[Meeting -") and created >= recent_cutoff
        if recent_meeting:
            reasons.append("recent meeting source")
        is_unblock = bool(_UNBLOCK_WORDS.search(action.title))
        if slot == "unblock":
            score += 30 if is_unblock else -20
            if is_unblock:
                reasons.append("coordination/unblock action")
        if slot == "quick_win":
            if is_unblock:
                score += 18
                reasons.append("likely quick coordination win")
            score += max(0, 90 - len(action.title)) // 6
        ranked.append(
            {
                "action": _action_payload(action, root),
                "score": score,
                "reasons": list(dict.fromkeys(reason for reason in reasons if reason))[:4] or ["active action"],
                "recent_meeting": recent_meeting,
                "focus_match": bool(focus and project.casefold() == focus),
                "urgent_match": path in urgent,
                "due": due,
            }
        )
    ranked.sort(
        key=lambda item: (
            not item["urgent_match"],
            not item["focus_match"],
            -item["score"],
            item["due"] or "9999-99-99",
            item["action"]["title"].casefold(),
        )
    )
    return ranked[:SUGGESTION_LIMIT]


def _action_payload(entity: EntityBase, root: Path) -> dict:
    path = Path(entity.path)
    target = (Path(root) / path).resolve()
    sha = sha256_file(target) if target.is_file() else ""
    return {
        "path": entity.path,
        "title": entity.title,
        "status": entity.status,
        "priority": getattr(entity, "priority", None),
        "due": getattr(entity, "due", None),
        "project": _project_name(entity),
        "owners": list(entity.owners),
        "sha": sha,
    }


def _project_name(entity: EntityBase) -> str:
    value = getattr(entity, "project", None)
    return str(value or "").strip().strip("\"'").strip("[]").strip()


def _focus_match_count(active: dict[str, EntityBase], focus: str) -> int:
    if not focus:
        return 0
    target = focus.casefold()
    return sum(1 for entity in active.values() if _project_name(entity).casefold() == target)


def _steering_from(raw_steering: Any, *, active: dict[str, EntityBase], projects: set[str]) -> Steering:
    raw = _as_dict(raw_steering)
    focus = str(raw.get("focus_project") or "").strip()
    if focus not in projects:
        focus = ""
    urgent = tuple(path for path in raw.get("urgent_paths") or [] if path in active)[:URGENT_LIMIT]
    note = str(raw.get("note") or "")[:NOTE_LIMIT]
    return Steering(focus_project=focus, urgent_paths=urgent, note=note)


def _load_stored(runtime_root: str | Path) -> dict:
    try:
        data = json.loads(plan_path(runtime_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(runtime_root: str | Path, *, today: date, selections: dict, steering: Any) -> None:
    payload = {
        "version": PLAN_VERSION,
        "date": today.isoformat(),
        "selections": selections,
        "steering": _as_dict(steering),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    write_json(runtime_root, PLAN_FILENAME, payload)


def _as_dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}
