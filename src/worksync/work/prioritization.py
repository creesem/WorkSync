"""Deterministic eligibility and baseline ranking for Command Center.

Read-only derived state: pure functions of the index and the candidates, with no
writes, no model, and no clock read. Every note is either a candidate or an
exclusion carrying exactly one reason code, decided by the first failing rule in
the documented order, so a caller never has to guess why a row is absent. Deadlines
and blockers are recorded on the candidate; they never exclude one.

Every candidate is then scored by one reason per factor — urgency, impact,
dependency, commitment, readiness, recent change — with fixed safety floors on
top. The score is the transparent additive sum of those reasons, so the ranking
is explainable row by row and reproducible for the same input.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from worksync.work.config import DEFAULT_CONFIG, WorkConfig
from worksync.work.dates import parse_iso_date
from worksync.work.models import EntityBase, EntityType, entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.review import (
    CLOSED_TICKET_STATUSES,
    OPEN_ACTION_STATUSES,
    OPEN_TICKET_STATUSES,
)
from worksync.work.schema import link_target, priority_rank

CANDIDATE_TYPES: tuple[EntityType, ...] = (EntityType.ACTION, EntityType.TICKET)
CHANGED_ON_FIELDS: tuple[str, ...] = ("last_checked", "updated", "created", "source_date")


class ExclusionReason(StrEnum):
    """The single reason a note is not a rankable candidate."""

    UNSUPPORTED_TYPE = "unsupported_type"
    UNAUTHORIZED = "unauthorized"
    CLOSED_STATUS = "closed_status"
    UNOWNED = "unowned"
    NO_EVIDENCE = "no_evidence"


@dataclass(frozen=True)
class Candidate:
    """One rankable record with the fields ranking reads."""

    entity_id: str
    entity_type: str
    path: str
    title: str
    status: str
    priority: str | None
    owner_ids: tuple[str, ...]
    due: str | None
    project_id: str | None
    blocked: bool
    waiting: bool
    manager_attention: bool
    changed_on: str | None


@dataclass(frozen=True)
class Exclusion:
    """One excluded note with the reason it was excluded."""

    path: str
    entity_id: str
    entity_type: str
    reason: str


@dataclass(frozen=True)
class Eligibility:
    """The candidates and the exclusions for one index."""

    candidates: tuple[Candidate, ...]
    exclusions: tuple[Exclusion, ...]


def eligibility(index: WorkIndex, *, today: date, config: WorkConfig = DEFAULT_CONFIG) -> Eligibility:
    """Return every rankable candidate and one reason per excluded note.

    ``today`` and ``config`` are accepted so a caller passes the same context it
    passes the ranker; eligibility itself reads neither.
    """
    visible_paths = {
        entity.path for entity_type in CANDIDATE_TYPES for entity in index.view_entities(entity_type.value)
    }
    candidates: list[Candidate] = []
    exclusions: list[Exclusion] = []
    for entity in index.entities:
        reason = _exclusion_reason(index, entity, visible_paths)
        if reason is None:
            candidates.append(_candidate(index, entity))
        else:
            exclusions.append(
                Exclusion(
                    path=entity.path,
                    entity_id=entity_id_of(entity),
                    entity_type=entity.entity_type.value,
                    reason=reason.value,
                )
            )
    return Eligibility(
        candidates=tuple(sorted(candidates, key=lambda candidate: candidate.path)),
        exclusions=tuple(sorted(exclusions, key=lambda exclusion: (exclusion.reason, exclusion.path))),
    )


def _exclusion_reason(index: WorkIndex, entity: EntityBase, visible_paths: set[str]) -> ExclusionReason | None:
    """Return the first failing rule for *entity*, or ``None`` when it is eligible."""
    if entity.entity_type not in CANDIDATE_TYPES:
        return ExclusionReason.UNSUPPORTED_TYPE
    if entity.path not in visible_paths:
        return ExclusionReason.UNAUTHORIZED
    if not _status_is_open(entity):
        return ExclusionReason.CLOSED_STATUS
    if not entity.owners:
        return ExclusionReason.UNOWNED
    if not _has_evidence(entity, _project_id(index, entity)):
        return ExclusionReason.NO_EVIDENCE
    return None


def _status_is_open(entity: EntityBase) -> bool:
    """Return True when the entity's status leaves it in play."""
    if entity.entity_type is EntityType.ACTION:
        return entity.status in OPEN_ACTION_STATUSES
    return entity.status in OPEN_TICKET_STATUSES and entity.status not in CLOSED_TICKET_STATUSES


def _has_evidence(entity: EntityBase, project_id: str | None) -> bool:
    """Return True when the note points at its source of truth.

    A resolvable project link is evidence, and so is a source or related reference;
    a note with neither cannot be ranked without guessing where it came from.
    """
    if project_id is not None:
        return True
    if entity.entity_type is EntityType.ACTION:
        return _is_set(getattr(entity, "related_ticket", None))
    return _is_set(getattr(entity, "source_system", None)) or _is_set(getattr(entity, "external_id", None))


def _is_set(value: object | None) -> bool:
    """Return True when a field carries something other than blank text."""
    return value is not None and bool(str(value).strip())


def _candidate(index: WorkIndex, entity: EntityBase) -> Candidate:
    """Project one eligible entity onto the fields ranking reads."""
    return Candidate(
        entity_id=entity_id_of(entity),
        entity_type=entity.entity_type.value,
        path=entity.path,
        title=entity.title,
        status=entity.status,
        priority=getattr(entity, "priority", None),
        owner_ids=_owner_ids(index, entity),
        due=getattr(entity, "due", None) if entity.entity_type is EntityType.ACTION else None,
        project_id=_project_id(index, entity),
        blocked=entity.status == "blocked",
        waiting=entity.status == "waiting",
        manager_attention=bool(getattr(entity, "manager_attention", False)),
        changed_on=_changed_on(entity),
    )


def _owner_ids(index: WorkIndex, entity: EntityBase) -> tuple[str, ...]:
    """Return the owners' canonical ids, or their link targets when unresolved."""
    owner_ids: list[str] = []
    for owner in entity.owners:
        resolved = index.resolve(owner)
        owner_id = entity_id_of(resolved) if resolved is not None else link_target(owner)
        if owner_id not in owner_ids:
            owner_ids.append(owner_id)
    return tuple(owner_ids)


def _project_id(index: WorkIndex, entity: EntityBase) -> str | None:
    """Return the linked project's canonical id, or ``None`` when it does not resolve."""
    project = index.resolve(getattr(entity, "project", None) or "")
    return entity_id_of(project) if project is not None and project.entity_type is EntityType.PROJECT else None


def _changed_on(entity: EntityBase) -> str | None:
    """Return the original string of the latest date field that parses, or ``None``.

    Dates are compared at day granularity, so two fields written on the same day
    tie and the earlier field in ``CHANGED_ON_FIELDS`` wins.
    """
    latest: tuple[date, str] | None = None
    for field_name in CHANGED_ON_FIELDS:
        value = entity.raw.get(field_name)
        parsed = parse_iso_date(value)
        if parsed is None:
            continue
        if latest is None or parsed.date() > latest[0]:
            latest = (parsed.date(), str(value))
    return None if latest is None else latest[1]


class RankFactor(StrEnum):
    """The transparent additive factors, in the order they are reported."""

    URGENCY = "urgency"
    IMPACT = "impact"
    DEPENDENCY = "dependency"
    COMMITMENT = "commitment"
    READINESS = "readiness"
    RECENT_CHANGE = "recent_change"


class SafetyPolicy(StrEnum):
    """A fixed floor on the band; a policy never drops a row."""

    MANAGER_ATTENTION = "manager_attention"
    OVERDUE = "overdue"
    BLOCKED = "blocked"


POLICY_BAND: dict[SafetyPolicy, int] = {
    SafetyPolicy.MANAGER_ATTENTION: 0,
    SafetyPolicy.OVERDUE: 0,
    SafetyPolicy.BLOCKED: 1,
}
DEFAULT_BAND: int = 2

DUE_SOON_WINDOW = timedelta(days=7)
RECENT_CHANGE_WINDOW = timedelta(days=14)
DUE_OVERDUE_DELTA = 45
DUE_TODAY_DELTA = 40
DUE_SOON_DELTA = 30
NO_DUE_DATE_DELTA = -8
PRIORITY_DELTAS: dict[int, int] = {1: 32, 2: 24, 3: 16, 4: 8}
MANAGER_ATTENTION_DELTA = 20
BLOCKED_DELTA = 25
WAITING_DELTA = 15
COMMITMENT_DELTA = 10
READY_DELTA = 12
NOT_READY_DELTA = -10
RECENT_CHANGE_DELTA = 10


@dataclass(frozen=True)
class RankReason:
    """One factor's contribution: what fired, its code, and why."""

    factor: str
    code: str
    detail: str


@dataclass(frozen=True)
class RankedItem:
    """One candidate with its score, floor band, policies, and reasons."""

    candidate: Candidate
    score: int
    band: int
    policies: tuple[str, ...]
    reasons: tuple[RankReason, ...]


@dataclass(frozen=True)
class Ranking:
    """The ranked items and the conflicts a caller must surface before applying."""

    items: tuple[RankedItem, ...]
    conflicts: tuple = ()


def rank(candidates: Iterable[Candidate], *, today: date, config: WorkConfig = DEFAULT_CONFIG) -> Ranking:
    """Return the baseline ranking, lowest floor band and highest score first.

    ``today`` is injected; nothing here reads a clock. ``config`` is accepted so a
    caller passes the same context it passes ``eligibility``; the weights and the
    safety floors are fixed constants, not configuration.
    """
    items = sorted((_ranked_item(candidate, today) for candidate in candidates), key=_sort_key)
    return Ranking(items=tuple(items))


def _sort_key(item: RankedItem) -> tuple[int, int, int, str, str, str]:
    """Return the documented order: band, then score, then the tie-breakers."""
    return (
        item.band,
        -item.score,
        priority_rank(item.candidate.priority) or 99,
        item.candidate.due or "9999-99-99",
        item.candidate.title.casefold(),
        item.candidate.path,
    )


def _ranked_item(candidate: Candidate, today: date) -> RankedItem:
    """Score one candidate with exactly one reason per contributing factor."""
    scored = [
        *_urgency_reasons(candidate, today),
        *_impact_reasons(candidate),
        *_dependency_reasons(candidate),
        *_commitment_reasons(candidate),
        *_readiness_reasons(candidate),
        *_recent_change_reasons(candidate, today),
    ]
    policies = _policies(candidate, today)
    return RankedItem(
        candidate=candidate,
        score=sum(delta for _, delta in scored),
        band=_band(policies),
        policies=tuple(policy.value for policy in policies),
        reasons=tuple(reason for reason, _ in scored),
    )


def _policies(candidate: Candidate, today: date) -> tuple[SafetyPolicy, ...]:
    """Return the safety policies that apply, ordered by band then name."""
    found: list[SafetyPolicy] = []
    if candidate.manager_attention:
        found.append(SafetyPolicy.MANAGER_ATTENTION)
    due_date = _due_date(candidate)
    if due_date is not None and due_date < today:
        found.append(SafetyPolicy.OVERDUE)
    if candidate.blocked:
        found.append(SafetyPolicy.BLOCKED)
    return tuple(sorted(found, key=lambda policy: (POLICY_BAND[policy], policy.value)))


def _band(policies: tuple[SafetyPolicy, ...]) -> int:
    """Return the lowest floor band the policies assign, else the default band."""
    return min((POLICY_BAND[policy] for policy in policies), default=DEFAULT_BAND)


def _urgency_reasons(candidate: Candidate, today: date) -> list[tuple[RankReason, int]]:
    """Score how pressing the deadline is, or its absence."""
    due = _due_date(candidate)
    if due is None:
        return [(_reason(RankFactor.URGENCY, "no_due_date", "No due date"), NO_DUE_DATE_DELTA)]
    if due < today:
        return [(_reason(RankFactor.URGENCY, "overdue", f"Overdue since {candidate.due}"), DUE_OVERDUE_DELTA)]
    if due == today:
        return [(_reason(RankFactor.URGENCY, "due_today", "Due today"), DUE_TODAY_DELTA)]
    if due <= today + DUE_SOON_WINDOW:
        return [(_reason(RankFactor.URGENCY, "due_soon", f"Due {candidate.due}"), DUE_SOON_DELTA)]
    return [(_reason(RankFactor.URGENCY, "due_scheduled", f"Due {candidate.due}"), 0)]


def _impact_reasons(candidate: Candidate) -> list[tuple[RankReason, int]]:
    """Score the official priority, plus a flag for manager attention."""
    reasons: list[tuple[RankReason, int]] = []
    rank_of_priority = priority_rank(candidate.priority)
    if rank_of_priority is None:
        reasons.append((_reason(RankFactor.IMPACT, "no_priority", "No priority"), 0))
    else:
        reasons.append(
            (
                _reason(RankFactor.IMPACT, "priority", str(candidate.priority)),
                PRIORITY_DELTAS[rank_of_priority],
            )
        )
    if candidate.manager_attention:
        reasons.append(
            (_reason(RankFactor.IMPACT, "manager_attention", "Flagged for manager attention"), MANAGER_ATTENTION_DELTA)
        )
    return reasons


def _dependency_reasons(candidate: Candidate) -> list[tuple[RankReason, int]]:
    """Score whether the record depends on something else moving first."""
    if candidate.blocked:
        return [(_reason(RankFactor.DEPENDENCY, "blocked", "Blocked"), BLOCKED_DELTA)]
    if candidate.waiting:
        return [(_reason(RankFactor.DEPENDENCY, "waiting", "Waiting"), WAITING_DELTA)]
    return [(_reason(RankFactor.DEPENDENCY, "independent", "Independent"), 0)]


def _commitment_reasons(candidate: Candidate) -> list[tuple[RankReason, int]]:
    """Score whether the record carries an explicit commitment."""
    if candidate.due or candidate.manager_attention:
        return [(_reason(RankFactor.COMMITMENT, "explicit_commitment", "Explicit commitment"), COMMITMENT_DELTA)]
    return [(_reason(RankFactor.COMMITMENT, "no_commitment", "No explicit commitment"), 0)]


def _readiness_reasons(candidate: Candidate) -> list[tuple[RankReason, int]]:
    """Score whether the record can move now: unblocked and owned."""
    if not candidate.blocked and not candidate.waiting and candidate.owner_ids:
        return [(_reason(RankFactor.READINESS, "ready", "Ready"), READY_DELTA)]
    return [(_reason(RankFactor.READINESS, "not_ready", "Not ready"), NOT_READY_DELTA)]


def _recent_change_reasons(candidate: Candidate, today: date) -> list[tuple[RankReason, int]]:
    """Score whether the record changed recently."""
    changed_on = parse_iso_date(candidate.changed_on)
    if changed_on is not None and today - changed_on.date() <= RECENT_CHANGE_WINDOW:
        return [
            (
                _reason(RankFactor.RECENT_CHANGE, "recent_change", f"Changed {candidate.changed_on}"),
                RECENT_CHANGE_DELTA,
            )
        ]
    return [(_reason(RankFactor.RECENT_CHANGE, "unchanged", "Unchanged"), 0)]


def _reason(factor: RankFactor, code: str, detail: str) -> RankReason:
    return RankReason(factor=factor.value, code=code, detail=detail)


def _due_date(candidate: Candidate) -> date | None:
    """Return the parsed due date, or ``None`` when unset or unparseable."""
    due = parse_iso_date(candidate.due)
    return None if due is None else due.date()
