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

An override the user made is decided before those floors: pin, focus-today, and
always-prioritize lift a record above them, defer sinks it below them, and
not-relevant drops the row. A lowering override aimed at a record carrying
material urgent evidence is refused and reported as a conflict instead, so the
evidence a human already flagged stays in view.

An override kind the ranker does not know is a bad record that is skipped, not a
reason to abort the whole ranking, exactly as an override whose target matches no
candidate is skipped: one unpersistable record must not fail a read. CC-04
validates the kinds it persists before they ever reach this module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum

from worksync.work.config import DEFAULT_CONFIG, WorkConfig
from worksync.work.dates import parse_iso_date
from worksync.work.models import EntityBase, EntityType, entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.review import (
    MANAGER_ATTENTION_REASON,
    AttentionKind,
    attention_by_path,
    is_open_status,
)
from worksync.work.schema import link_target, priority_rank

CANDIDATE_TYPES: tuple[EntityType, ...] = (EntityType.ACTION, EntityType.TICKET)
CHANGED_ON_FIELDS: tuple[str, ...] = ("last_checked", "updated", "created", "source_date")
UNKNOWN_PRIORITY_RANK = 99
LATE_DUE_SENTINEL = "9999-99-99"


class ExclusionReason(StrEnum):
    """The single reason a note is not a rankable candidate.

    The membership is the exclusion's dimensions, one reason each: the note's
    shape (type), its permissions, its lifecycle (status), its ownership, and its
    evidence. ``UNAUTHORIZED`` is the permissions dimension: the validator
    flagged the note, so it is absent from ``view_entities`` and is not
    authorized for ranking, whatever the flag was.
    """

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
    waiting_on: str | None = None
    dependency_id: str | None = None


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

    ``today`` and ``config`` are forwarded to the review module's attention pass,
    which is the single owner of the blocker signal this module records.
    """
    attention = _attention_kinds_by_path(index, today, config)
    visible_paths = {
        entity.path for entity_type in CANDIDATE_TYPES for entity in index.view_entities(entity_type.value)
    }
    candidates: list[Candidate] = []
    exclusions: list[Exclusion] = []
    for entity in index.entities:
        reason = _exclusion_reason(index, entity, visible_paths)
        if reason is None:
            candidates.append(_candidate(index, entity, attention))
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
    if not is_open_status(entity):
        return ExclusionReason.CLOSED_STATUS
    if not entity.owners:
        return ExclusionReason.UNOWNED
    if not _has_evidence(entity, _project_id(index, entity)):
        return ExclusionReason.NO_EVIDENCE
    return None


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


def _attention_kinds_by_path(index: WorkIndex, today: date, config: WorkConfig) -> dict[str, frozenset[str]]:
    """Reshape the review module's attention pass into a per-note kind lookup.

    The blocker signal has one owner. Deriving it a second time from raw status
    strings here is exactly the drift the global reuse constraint forbids, so
    this pass only groups the kinds ``attention_by_path`` already decided, keyed
    by the note path the candidate carries.
    """
    kinds_by_path: dict[str, frozenset[str]] = {}
    for path, items in attention_by_path(index, today, config).items():
        kinds_by_path[path] = frozenset(item.kind for item in items)
    return kinds_by_path


def _candidate(index: WorkIndex, entity: EntityBase, attention: dict[str, frozenset[str]]) -> Candidate:
    """Project one eligible entity onto the fields ranking reads."""
    kinds = attention.get(entity.path, frozenset())
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
        blocked=AttentionKind.BLOCKED.value in kinds,
        waiting=AttentionKind.WAITING.value in kinds,
        waiting_on=getattr(entity, "waiting_on", None) if entity.entity_type is EntityType.ACTION else None,
        manager_attention=AttentionKind.MANAGER_ATTENTION.value in kinds,
        changed_on=_changed_on(entity),
        dependency_id=_dependency_id(index, entity),
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


def _dependency_id(index: WorkIndex, entity: EntityBase) -> str | None:
    """Return the canonical id of the record this one waits on, or ``None``.

    The dependency is the ``related_ticket`` link, so an unresolved link stays
    ``None`` rather than guessing at a target that is not in the index.
    """
    dependency = index.resolve(getattr(entity, "related_ticket", None) or "")
    if dependency is None or dependency.entity_type not in CANDIDATE_TYPES:
        return None
    return entity_id_of(dependency)


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


class OverrideKind(StrEnum):
    """What the user did to one record; the ranker honours it before the floors."""

    PIN = "pin"
    FOCUS_TODAY = "focus_today"
    DEFER = "defer"
    NOT_RELEVANT = "not_relevant"
    ALWAYS_PRIORITIZE = "always_prioritize"


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
ELEVATED_BAND: int = -1
DEFERRED_BAND: int = 3
LOWERING_KINDS: frozenset[OverrideKind] = frozenset({OverrideKind.DEFER, OverrideKind.NOT_RELEVANT})

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
class Override:
    """One user decision about one record; the reason is carried for provenance."""

    override_id: str
    target_id: str
    kind: str
    reason: str = ""


@dataclass(frozen=True)
class OverrideConflict:
    """One override that cannot be honoured, with the evidence that stops it."""

    override_id: str
    entity_id: str
    kind: str
    evidence: str
    detail: str


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
    conflicts: tuple[OverrideConflict, ...] = ()


def rank(
    candidates: Iterable[Candidate],
    *,
    today: date,
    overrides: Iterable[Override] = (),
) -> Ranking:
    """Return the ranking with the overrides decided before the safety floors.

    An override replaces the floor band of the record it names, or drops that row
    entirely; a lowering override aimed at a record holding material urgent
    evidence is refused and reported as an ``OverrideConflict`` instead, leaving
    the record at its safety band. With no overrides the result is the baseline
    ranking and ``conflicts`` is empty. ``today`` is injected; nothing here reads
    a clock, and the weights and the safety floors are fixed constants rather
    than configuration.
    """
    resolved = _resolve_overrides(overrides)
    items: list[RankedItem] = []
    conflicts: list[OverrideConflict] = []
    for candidate in candidates:
        item = _ranked_item(candidate, today)
        override = resolved.get(item.candidate.entity_id)
        if override is None:
            items.append(item)
            continue
        kind = _override_kind(override)
        if kind in LOWERING_KINDS and item.policies:
            conflicts.append(_conflict(override, kind, item))
            items.append(item)
            continue
        band = _override_band(kind)
        if band is None:
            continue
        items.append(replace(item, band=band))
    items.sort(key=_sort_key)
    conflicts.sort(key=lambda conflict: (conflict.entity_id, conflict.kind, conflict.override_id))
    return Ranking(items=tuple(items), conflicts=tuple(conflicts))


def _resolve_overrides(overrides: Iterable[Override]) -> dict[str, Override]:
    """Index the overrides by the record they target, the last one for a target winning."""
    resolved: dict[str, Override] = {}
    for override in overrides:
        # A kind the ranker does not know is a bad record, skipped like one that
        # names no candidate: one unpersistable override must not abort a read.
        try:
            _override_kind(override)
        except ValueError:
            continue
        resolved[override.target_id] = override
    return resolved


def _override_kind(override: Override) -> OverrideKind:
    """Return the override's kind, failing closed on one the ranker does not know."""
    try:
        return OverrideKind(str(override.kind).strip())
    except ValueError as error:
        raise ValueError(f"Unknown override kind {override.kind!r} for target {override.target_id}") from error


def _override_band(kind: OverrideKind) -> int | None:
    """Return the band the override forces, or ``None`` when it drops the row."""
    if kind is OverrideKind.DEFER:
        return DEFERRED_BAND
    if kind is OverrideKind.NOT_RELEVANT:
        return None
    return ELEVATED_BAND


def _conflict(override: Override, kind: OverrideKind, item: RankedItem) -> OverrideConflict:
    """Report the lowering override that was refused, and the evidence that refused it."""
    evidence = item.policies[0]
    return OverrideConflict(
        override_id=override.override_id,
        entity_id=item.candidate.entity_id,
        kind=kind.value,
        evidence=evidence,
        detail=f"Cannot {kind.value} {item.candidate.entity_id}: {evidence}",
    )


def _sort_key(item: RankedItem) -> tuple[int, int, int, str, str, str]:
    """Return the documented order: band, then score, then the tie-breakers."""
    return (
        item.band,
        -item.score,
        priority_rank(item.candidate.priority) or UNKNOWN_PRIORITY_RANK,
        item.candidate.due or LATE_DUE_SENTINEL,
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
    """Score how pressing the deadline is, or its absence.

    An unset due and a due that is set but unreadable both score the same, because
    neither can prove urgency; only the unreadable one is named, so a caller can
    see that a date was written and lost rather than never set.
    """
    if not _is_set(candidate.due):
        return [(_reason(RankFactor.URGENCY, "no_due_date", "No due date"), NO_DUE_DATE_DELTA)]
    due = _due_date(candidate)
    if due is None:
        return [
            (
                _reason(RankFactor.URGENCY, "due_unparseable", f"Due date not understood: {candidate.due}"),
                NO_DUE_DATE_DELTA,
            )
        ]
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
            (_reason(RankFactor.IMPACT, "manager_attention", MANAGER_ATTENTION_REASON), MANAGER_ATTENTION_DELTA)
        )
    return reasons


def _dependency_reasons(candidate: Candidate) -> list[tuple[RankReason, int]]:
    """Score whether the record depends on something else moving first."""
    if candidate.blocked:
        return [(_reason(RankFactor.DEPENDENCY, "blocked", "Blocked"), BLOCKED_DELTA)]
    if candidate.waiting:
        detail = f"Waiting on {candidate.waiting_on}" if _is_set(candidate.waiting_on) else "Waiting"
        return [(_reason(RankFactor.DEPENDENCY, "waiting", detail), WAITING_DELTA)]
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
    """Score whether the record changed in the window ending today.

    The window is bounded on both ends: a change dated in the future has not
    happened yet as far as this ranking is concerned, so it earns nothing.
    """
    changed_on = parse_iso_date(candidate.changed_on)
    if changed_on is not None and 0 <= (today - changed_on.date()).days <= RECENT_CHANGE_WINDOW.days:
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
