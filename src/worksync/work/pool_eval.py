"""Human evaluation, advisory rubric scoring, and deterministic pool context.

This module is read/compose-only: it turns human input into a new immutable
``PoolCandidate`` value for ``work.pool_store.write_pool`` and builds deterministic
context facts for the API/UI. It never writes the vault, never changes an action,
never promotes, and never calls a model. The score is advisory only; state changes
are limited to the first human evaluation's ``new -> evaluating`` transition.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from worksync.work.models import EntityType
from worksync.work.pool import (
    PRIORITIES,
    SCORING_VERSION,
    HistoryEntry,
    PoolCandidate,
    PoolError,
    Rubric,
    TaskFieldValue,
    score_for_ratings,
    scoring_model,
)
from worksync.work.projects import ProjectIdentity, associate_note, load_project_identities
from worksync.work.repository import WorkIndex

EVALUATE_OP = "pool-evaluate"
RATING_KEYS: tuple[str, ...] = ("impact", "urgency", "effort", "strategic_fit")
_PLACEHOLDER_PROJECTS = frozenset(
    {
        "unassigned",
        "none",
        "null",
        "n/a",
        "na",
        "tbd",
        "unknown",
        "project_unassigned",
        "no project",
        "unassigned project",
    }
)
_UNSET = object()


@dataclass(frozen=True)
class CanonicalProject:
    """One existing canonical WorkSync project identity, never a placeholder."""

    project_id: str
    name: str
    path: str
    status: str = ""
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class PromotionRequirements:
    """The specific human-evaluation requirements that still block promotion."""

    project_id: str | None
    project_resolved: bool
    missing_ratings: tuple[str, ...]
    note_present: bool
    score_present: bool
    state: str

    @property
    def state_ready(self) -> bool:
        return self.state == "evaluating"

    @property
    def evaluation_complete(self) -> bool:
        return not self.missing_ratings and self.note_present and self.score_present

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.project_resolved:
            blockers.append("project_unresolved")
        if not self.evaluation_complete:
            blockers.append("incomplete_evaluation")
        if not self.state_ready:
            blockers.append("invalid_state")
        return tuple(blockers)

    @property
    def ready(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "project_resolved": self.project_resolved,
            "missing_ratings": list(self.missing_ratings),
            "note_present": self.note_present,
            "score_present": self.score_present,
            "state": self.state,
            "state_ready": self.state_ready,
            "evaluation_complete": self.evaluation_complete,
            "blockers": list(self.blockers),
            "ready": self.ready,
        }


@dataclass(frozen=True)
class ProjectContext:
    """Deterministic project facts for a candidate's context panel."""

    project_id: str | None
    name: str | None
    status: str | None
    resolved: bool
    action_count: int
    priority_counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status,
            "resolved": self.resolved,
            "action_count": self.action_count,
            "priority_counts": dict(self.priority_counts),
        }


@dataclass(frozen=True)
class CandidateContext:
    """Read-only, model-free context for the pool API/UI."""

    project: ProjectContext
    meeting_date: str | None
    meeting_age_days: int | None
    source: dict[str, object]
    parse_quality: str | None
    parse_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project.to_dict(),
            "meeting_date": self.meeting_date,
            "meeting_age_days": self.meeting_age_days,
            "source": dict(self.source),
            "parse_quality": self.parse_quality,
            "parse_reasons": list(self.parse_reasons),
        }


def load_canonical_projects(vault_root: str | Path) -> tuple[CanonicalProject, ...]:
    """Load existing canonical project identities from the vault, read-only."""
    return canonical_projects_from_index(WorkIndex.from_vault(vault_root))


def canonical_projects_from_index(index: WorkIndex) -> tuple[CanonicalProject, ...]:
    """Return canonical project identities from an already-built work index."""
    projects = [
        CanonicalProject(
            project_id=record.project_id,
            name=record.name,
            path=record.path,
            status=record.status,
            aliases=record.aliases,
        )
        for record in load_project_identities(index)
        if record.project_id
    ]
    return tuple(sorted(projects, key=lambda project: (project.project_id, project.path)))


def score_if_complete(
    impact: object,
    urgency: object,
    effort: object,
    strategic_fit: object,
    *,
    version: str = SCORING_VERSION,
) -> float | None:
    """Return the advisory score only when all four valid ratings exist."""
    values = {
        "impact": impact,
        "urgency": urgency,
        "effort": effort,
        "strategic_fit": strategic_fit,
    }
    for key in RATING_KEYS:
        value = values[key]
        if value is None:
            return None
        if not _valid_rating(value):
            raise PoolError("invalid_rubric", f"{key} must be an integer from 1 to 5.", 422)
    return score_for_ratings(
        values["impact"],
        values["urgency"],
        values["effort"],
        values["strategic_fit"],
        version=version,
    )  # type: ignore[arg-type]


def score_explanation(version: str = SCORING_VERSION) -> dict[str, object]:
    """Explain one scoring version's weights without changing any stored score."""
    model = scoring_model(version)
    return {
        "version": model.version,
        "formula": model.formula,
        "weights": {
            "impact": model.impact_weight,
            "urgency": model.urgency_weight,
            "strategic_fit": model.strategic_fit_weight,
            "effort": model.effort_weight,
        },
        "effort_inverted": model.effort_inverted,
        "scale": "0-100",
        "rounding": "one decimal",
        "advisory": True,
        "effects": "Advisory only; never assigns priority, changes state, or promotes.",
    }


def evaluate_candidate(
    candidate: PoolCandidate,
    *,
    impact: object = None,
    urgency: object = None,
    effort: object = None,
    strategic_fit: object = None,
    note: object = None,
    rated_by: str,
    reason: str,
    at: datetime | None = None,
    expected_revision: int | None = None,
    project: object = _UNSET,
    projects: Iterable[CanonicalProject] | None = None,
    scoring_version: str | None = None,
) -> PoolCandidate:
    """Apply one explicit human evaluation without promoting or setting priority.

    All four integer ratings and a non-empty note are required. The first evaluation
    moves ``new -> evaluating``; later evaluations preserve the current state. A
    project is assigned only by an exact canonical project id (or ``None`` for
    Unassigned); no placeholder or inferred association is accepted. The stored
    score keeps the rubric version used to produce it unless a caller explicitly
    asks for another registered version.
    """
    _check_expected_revision(candidate, expected_revision)
    if candidate.state not in ("new", "evaluating"):
        raise PoolError(
            "invalid_state",
            f"Cannot evaluate a candidate in state {candidate.state}; reopen it first.",
            422,
        )
    reviewer = _required_text(rated_by, "missing_reviewer", "A rated_by reviewer is required.")
    evaluation_reason = _required_text(reason, "missing_reason", "An evaluation reason is required.")

    ratings = _validate_ratings(impact, urgency, effort, strategic_fit)
    clean_note = _validate_note(note)
    version = _resolve_scoring_version(candidate, scoring_version)
    score = score_for_ratings(
        ratings["impact"],
        ratings["urgency"],
        ratings["effort"],
        ratings["strategic_fit"],
        version=version,
    )

    task_fields = dict(candidate.task_fields)
    if project is not _UNSET:
        task_fields["project"] = _assign_project(task_fields["project"], project, projects)

    when = _as_utc(at)
    was_new = candidate.state == "new"
    new_state = "evaluating" if was_new else candidate.state
    rubric = Rubric(
        **ratings,
        note=clean_note,
        scoring_version=version,
        score=score,
        rated_by=reviewer,
        rated_at=when.isoformat(),
    )
    entry = HistoryEntry(
        at=when.isoformat(),
        by=reviewer,
        from_state=candidate.state,
        to_state=new_state,
        reason=evaluation_reason,
        op=EVALUATE_OP,
        ratings=dict(ratings),
        scoring_version=version,
        score=score,
    )
    return replace(
        candidate,
        state=new_state,
        state_reason=evaluation_reason if was_new else candidate.state_reason,
        task_fields=task_fields,
        rubric=rubric,
        history=(*candidate.history, entry),
        revision=candidate.revision + 1,
        updated_at=when.isoformat(),
    )


def promotion_requirements(
    candidate: PoolCandidate,
    *,
    projects: Iterable[CanonicalProject] | None = None,
) -> PromotionRequirements:
    """Return the evaluation-specific promotion blockers tickets 04/05/06 expose.

    When *projects* is supplied, a stored project id must resolve to exactly one
    canonical project. Without a catalog, a non-placeholder project id is treated as
    present so callers that only have the candidate can still use the report.
    """
    project_id = candidate.task_fields["project"].effective
    catalog = _project_catalog(projects) if projects is not None else None
    project_resolved = _project_resolved(project_id, catalog)
    rubric = candidate.rubric
    missing = tuple(key for key in RATING_KEYS if rubric is None or not _valid_rating(getattr(rubric, key, None)))
    note_present = bool(rubric is not None and isinstance(rubric.note, str) and rubric.note.strip())
    score_present = bool(rubric is not None and rubric.score is not None)
    return PromotionRequirements(
        project_id=project_id,
        project_resolved=project_resolved,
        missing_ratings=missing,
        note_present=note_present,
        score_present=score_present,
        state=candidate.state,
    )


def project_is_resolved(
    candidate: PoolCandidate,
    *,
    projects: Iterable[CanonicalProject] | None = None,
) -> bool:
    """True only for a non-placeholder project identity, optionally catalog-checked."""
    catalog = _project_catalog(projects) if projects is not None else None
    return _project_resolved(candidate.task_fields["project"].effective, catalog)


def project_blocked_candidates(
    candidates: Iterable[PoolCandidate],
    *,
    projects: Iterable[CanonicalProject] | None = None,
) -> tuple[PoolCandidate, ...]:
    """Return the project-blocked candidates in their input order."""
    return tuple(candidate for candidate in candidates if not project_is_resolved(candidate, projects=projects))


def build_context(
    candidate: PoolCandidate,
    *,
    index: WorkIndex,
    as_of: date | datetime | str | None = None,
    projects: Iterable[CanonicalProject] | None = None,
) -> CandidateContext:
    """Build deterministic, read-only context from an already-built work index."""
    today = _as_date(as_of)
    canonical = tuple(projects) if projects is not None else canonical_projects_from_index(index)
    meeting_date = candidate.source.meeting_date
    meeting_age = None
    parsed_meeting = _parse_iso_date(meeting_date)
    if parsed_meeting is not None:
        meeting_age = (today - parsed_meeting).days
    return CandidateContext(
        project=_project_context(candidate, index, canonical),
        meeting_date=meeting_date,
        meeting_age_days=meeting_age,
        source=candidate.source.to_dict(),
        parse_quality=candidate.parse_quality,
        parse_reasons=candidate.parse_reasons,
    )


def read_context(
    candidate: PoolCandidate,
    vault_root: str | Path,
    *,
    as_of: date | datetime | str | None = None,
    index: WorkIndex | None = None,
    projects: Iterable[CanonicalProject] | None = None,
) -> CandidateContext:
    """Build context from the vault (or a caller-supplied index) without writing."""
    work_index = index if index is not None else WorkIndex.from_vault(vault_root)
    return build_context(candidate, index=work_index, as_of=as_of, projects=projects)


def _check_expected_revision(candidate: PoolCandidate, expected: int | None) -> None:
    if expected is None:
        return
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise PoolError("bad_request", "expected_revision must be an integer.", 400)
    if expected != candidate.revision:
        raise PoolError(
            "stale_candidate",
            f"The candidate revision changed (expected {expected}, found {candidate.revision}).",
            409,
        )


def _required_text(value: str, code: str, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PoolError(code, message, 400)
    return text


def _validate_ratings(
    impact: object,
    urgency: object,
    effort: object,
    strategic_fit: object,
) -> dict[str, int]:
    values = {
        "impact": impact,
        "urgency": urgency,
        "effort": effort,
        "strategic_fit": strategic_fit,
    }
    ratings: dict[str, int] = {}
    missing: list[str] = []
    for key in RATING_KEYS:
        value = values[key]
        if value is None:
            missing.append(key)
            continue
        if not _valid_rating(value):
            raise PoolError(
                "invalid_rubric",
                f"{key} must be an integer from 1 to 5.",
                422,
            )
        ratings[key] = value  # type: ignore[assignment]
    if missing:
        raise PoolError(
            "incomplete_evaluation",
            f"All four ratings are required; missing: {', '.join(missing)}.",
            422,
        )
    return ratings


def _validate_note(note: object) -> str:
    if not isinstance(note, str):
        raise PoolError("invalid_rubric", "The evaluation note must be text.", 422)
    clean = note.strip()
    if not clean:
        raise PoolError("incomplete_evaluation", "A non-empty evaluation note is required.", 422)
    return clean


def _resolve_scoring_version(candidate: PoolCandidate, scoring_version: str | None) -> str:
    if scoring_version is None:
        version = candidate.rubric.scoring_version if candidate.rubric is not None else SCORING_VERSION
    else:
        if not isinstance(scoring_version, str) or not scoring_version.strip():
            raise PoolError("bad_request", "scoring_version must be a non-empty string.", 400)
        version = scoring_version.strip()
    scoring_model(version)
    return version


def _assign_project(
    field: TaskFieldValue,
    project: object,
    projects: Iterable[CanonicalProject] | None,
) -> TaskFieldValue:
    if project is None:
        return TaskFieldValue(extracted=field.extracted, human=None, effective=field.extracted)
    if not isinstance(project, str):
        raise PoolError(
            "bad_request",
            "A project assignment must be a canonical project id or Unassigned.",
            400,
        )
    value = project.strip()
    if not value or _is_placeholder(value):
        raise PoolError(
            "bad_request",
            "A project assignment must be a canonical project id or Unassigned; placeholders are not accepted.",
            400,
        )
    catalog = _project_catalog(projects) if projects is not None else None
    if catalog is None:
        raise PoolError(
            "project_unresolved",
            "A canonical project catalog is required to assign a project.",
            422,
        )
    matches = catalog.get(value, ())
    if len(matches) != 1:
        raise PoolError("project_unresolved", f"No unique canonical project with id: {value}", 422)
    return TaskFieldValue(extracted=field.extracted, human=value, effective=value)


def _project_catalog(
    projects: Iterable[CanonicalProject] | None,
) -> dict[str, tuple[CanonicalProject, ...]]:
    catalog: dict[str, list[CanonicalProject]] = {}
    if projects is None:
        return {}
    for project in projects:
        catalog.setdefault(project.project_id, []).append(project)
    return {key: tuple(sorted(value, key=lambda item: item.path)) for key, value in catalog.items()}


def _project_resolved(
    project_id: str | None,
    catalog: dict[str, tuple[CanonicalProject, ...]] | None,
) -> bool:
    if not isinstance(project_id, str) or not project_id.strip() or _is_placeholder(project_id):
        return False
    if catalog is None:
        return True
    return len(catalog.get(project_id, ())) == 1


def _is_placeholder(value: str) -> bool:
    return value.strip().casefold() in _PLACEHOLDER_PROJECTS


def _valid_rating(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5


def _project_context(
    candidate: PoolCandidate,
    index: WorkIndex,
    projects: tuple[CanonicalProject, ...],
) -> ProjectContext:
    project_id = candidate.task_fields["project"].effective
    catalog = _project_catalog(projects)
    matches = catalog.get(project_id, ()) if isinstance(project_id, str) else ()
    resolved = _project_resolved(project_id, catalog)
    project = matches[0] if resolved and matches else None
    counts = {priority: 0 for priority in (*PRIORITIES, "none")}
    if project is not None:
        records = load_project_identities(index)
        for action in index.list_type(EntityType.ACTION.value):
            if not _action_in_project(action, records, project.project_id):
                continue
            priority = str(getattr(action, "priority", "") or "").strip().upper()
            counts[priority if priority in PRIORITIES else "none"] += 1
    return ProjectContext(
        project_id=project_id,
        name=project.name if project is not None else None,
        status=project.status if project is not None else None,
        resolved=resolved,
        action_count=sum(counts.values()),
        priority_counts=counts,
    )


def _action_in_project(
    action: object,
    records: list[ProjectIdentity],
    project_id: str,
) -> bool:
    raw = getattr(action, "raw", None)
    path = str(getattr(action, "path", "") or "")
    if not isinstance(raw, dict):
        return False
    if any(link.project_id == project_id for link in associate_note(raw, records, path)):
        return True
    # A canonical id may also be stored directly; never infer a name match here.
    for key in ("project", "projects"):
        value = raw.get(key)
        values = value if isinstance(value, list) else [value]
        if any(_project_reference_id(item) == project_id for item in values):
            return True
    return False


def _project_reference_id(value: object) -> str | None:
    text = str(value or "").strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.split("|", 1)[0].split("#", 1)[0].strip()
    return text or None


def _as_utc(value: datetime | None) -> datetime:
    when = value or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def _as_date(value: date | datetime | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        parsed = _parse_iso_date(value)
        if parsed is not None:
            return parsed
    raise PoolError("bad_request", "as_of must be an ISO date.", 400)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
