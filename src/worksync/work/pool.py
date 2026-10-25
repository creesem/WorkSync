"""Runtime potential-task pool: schema, read model, definition presentation, and lifecycle.

The pool is deliberately separate from the vault and live work index. Candidates live in
``runtime/user_state/pool.json`` and are never entities; the ``potential-task`` supertag is
only a presentation/schema extension. This module has no safety-layer import: the read seam
can use it without pulling in the write gateway. Writes live in ``work.pool_store``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from worksync.inventory.parse import scan_vault
from worksync.work.generation import WorkGeneration
from worksync.work.permissions import permission_warnings
from worksync.work.since_last_check import user_state_root
from worksync.work.supertags import Supertag, build_registry

POOL_FILENAME = "pool.json"
POOL_SCHEMA_VERSION = 1
CANDIDATE_SCHEMA_VERSION = 1
SCORING_VERSION = "rubric-v1"
EXTRACTION_VERSION = "extract-v1"
DEFAULT_DEFINITION_VERSION = "default-v1"
DEFAULT_DEFINITION_ID = "potential-task"
POOL_START_VERB = "pool_init"
POOL_WRITE_VERB = "pool_write"
POOL_RESTORE_VERB = "pool_restore"

STATES = ("new", "evaluating", "deferred", "rejected", "duplicate", "obsolete", "promoted")
TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"evaluating", "obsolete"}),
    "evaluating": frozenset({"promoted", "deferred", "rejected", "duplicate", "obsolete"}),
    "deferred": frozenset({"evaluating", "obsolete"}),
    "rejected": frozenset({"evaluating", "obsolete"}),
    "duplicate": frozenset({"evaluating", "obsolete"}),
    "obsolete": frozenset({"evaluating"}),
    "promoted": frozenset(),
}
PARSE_QUALITIES = ("complete", "partial", "minimal")
LINK_STATES = ("linked", "missing", "inconsistent")
SOURCE_KINDS = ("meeting", "manual")
MANUAL_PROVENANCE_CLASSES = ("manual-note", "meeting-followup", "direct-request", "other")
PRIORITIES = ("P1", "P2", "P3", "P4")
TASK_FIELD_KEYS = ("project", "owner", "due", "priority")

_CANDIDATE_ID_RE = re.compile(r"^cand-[0-9a-f]{16}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class PoolError(ValueError):
    """A user-facing pool read/write error with an HTTP status."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


_UTC_ALIASES = frozenset({"utc", "etc/utc", "gmt", "z"})


def pool_zone(name: str) -> tzinfo:
    """Resolve an IANA timezone, with a built-in UTC fallback for Windows without tzdata."""
    text = str(name or "").strip()
    if not text:
        raise PoolError("bad_timezone", "An IANA timezone is required.", 400)
    if text.casefold() in _UTC_ALIASES:
        return UTC
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise PoolError("bad_timezone", f"Unknown timezone: {text}", 400) from exc


def pool_path(runtime_root: str | Path) -> Path:
    """Return the pool record's path in the ``user_state`` zone."""
    return user_state_root(runtime_root) / POOL_FILENAME


@dataclass(frozen=True)
class ScoringModel:
    """One versioned human-rubric scoring model.

    Versions are additive and permanent: a stored score is validated against the
    model named by its own ``scoring_version``, never against the current default.
    That keeps old scores explainable when weights change.
    """

    version: str
    impact_weight: float
    urgency_weight: float
    strategic_fit_weight: float
    effort_weight: float
    formula: str
    effort_inverted: bool = True


RUBRIC_V1_FORMULA = (
    "raw = 0.35*(impact/5) + 0.30*(urgency/5) + 0.25*(strategic_fit/5) + 0.10*((6-effort)/5); score = round(raw*100, 1)"
)
SCORING_MODELS: dict[str, ScoringModel] = {
    SCORING_VERSION: ScoringModel(
        version=SCORING_VERSION,
        impact_weight=0.35,
        urgency_weight=0.30,
        strategic_fit_weight=0.25,
        effort_weight=0.10,
        formula=RUBRIC_V1_FORMULA,
    ),
}


def scoring_model(version: str) -> ScoringModel:
    """Return a registered scoring model, failing closed for an unknown version."""
    model = SCORING_MODELS.get(version)
    if model is None:
        raise PoolError("pool_version", f"Unsupported scoring version: {version}", 409)
    return model


def score_for_ratings(
    impact: int,
    urgency: int,
    effort: int,
    strategic_fit: int,
    *,
    version: str = SCORING_VERSION,
) -> float:
    """Return the advisory score for all four human ratings under one version."""
    model = scoring_model(version)
    effort_value = 6 - effort if model.effort_inverted else effort
    raw = (
        model.impact_weight * (impact / 5)
        + model.urgency_weight * (urgency / 5)
        + model.strategic_fit_weight * (strategic_fit / 5)
        + model.effort_weight * (effort_value / 5)
    )
    return round(raw * 100, 1)


@dataclass(frozen=True)
class TaskFieldValue:
    extracted: str | None = None
    human: str | None = None
    effective: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"extracted": self.extracted, "human": self.human, "effective": self.effective}

    @classmethod
    def from_dict(cls, payload: object, *, key: str) -> TaskFieldValue:
        data = _mapping(payload, f"task_fields.{key}")
        _allow(data, {"extracted", "human", "effective"}, f"task_fields.{key}")
        extracted = _nullable_text(data.get("extracted"), f"task_fields.{key}.extracted")
        human = _nullable_text(data.get("human"), f"task_fields.{key}.human")
        effective = _nullable_text(data.get("effective"), f"task_fields.{key}.effective")
        for value in (extracted, human, effective):
            _validate_task_value(key, value, f"task_fields.{key}")
        expected = human if human is not None else extracted
        if effective != expected:
            raise PoolError(
                "pool_corrupt",
                f"task_fields.{key}.effective must equal human when set, else extracted",
                500,
            )
        return cls(extracted=extracted, human=human, effective=effective)


@dataclass(frozen=True)
class PoolSource:
    kind: str
    meeting_id: str | None = None
    meeting_path: str | None = None
    meeting_date: str | None = None
    content_hash: str | None = None
    line: int | None = None
    occurrence: int | None = None
    quote: str | None = None
    rule_version: str | None = None
    extracted_at: str | None = None
    initiated_by: str | None = None
    provenance_classification: str | None = None
    provenance_note: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "meeting_id": self.meeting_id,
            "meeting_path": self.meeting_path,
            "meeting_date": self.meeting_date,
            "content_hash": self.content_hash,
            "line": self.line,
            "occurrence": self.occurrence,
            "quote": self.quote,
            "rule_version": self.rule_version,
            "extracted_at": self.extracted_at,
            "initiated_by": self.initiated_by,
            "provenance_classification": self.provenance_classification,
            "provenance_note": self.provenance_note,
        }

    @classmethod
    def from_dict(cls, payload: object) -> PoolSource:
        data = _mapping(payload, "source")
        _allow(data, set(PoolSource.__dataclass_fields__), "source")
        kind = _text(data.get("kind"), "source.kind")
        if kind not in SOURCE_KINDS:
            raise PoolError("pool_corrupt", f"source.kind must be one of {SOURCE_KINDS}", 500)
        source = cls(
            kind=kind,
            meeting_id=_nullable_text(data.get("meeting_id"), "source.meeting_id"),
            meeting_path=_nullable_text(data.get("meeting_path"), "source.meeting_path"),
            meeting_date=_nullable_text(data.get("meeting_date"), "source.meeting_date"),
            content_hash=_nullable_text(data.get("content_hash"), "source.content_hash"),
            line=_nullable_int(data.get("line"), "source.line"),
            occurrence=_nullable_int(data.get("occurrence"), "source.occurrence"),
            quote=_nullable_text(data.get("quote"), "source.quote"),
            rule_version=_nullable_text(data.get("rule_version"), "source.rule_version"),
            extracted_at=_nullable_text(data.get("extracted_at"), "source.extracted_at"),
            initiated_by=_nullable_text(data.get("initiated_by"), "source.initiated_by"),
            provenance_classification=_nullable_text(
                data.get("provenance_classification"), "source.provenance_classification"
            ),
            provenance_note=_nullable_text(data.get("provenance_note"), "source.provenance_note"),
        )
        _validate_source(source)
        return source


@dataclass(frozen=True)
class Rubric:
    impact: int | None = None
    urgency: int | None = None
    effort: int | None = None
    strategic_fit: int | None = None
    note: str = ""
    scoring_version: str = SCORING_VERSION
    score: float | None = None
    rated_by: str | None = None
    rated_at: str | None = None

    @property
    def complete(self) -> bool:
        return all(
            value is not None for value in (self.impact, self.urgency, self.effort, self.strategic_fit)
        ) and bool(self.note.strip())

    def to_dict(self) -> dict[str, object]:
        return {
            "impact": self.impact,
            "urgency": self.urgency,
            "effort": self.effort,
            "strategic_fit": self.strategic_fit,
            "note": self.note,
            "scoring_version": self.scoring_version,
            "score": self.score,
            "rated_by": self.rated_by,
            "rated_at": self.rated_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> Rubric:
        data = _mapping(payload, "rubric")
        _allow(data, set(Rubric.__dataclass_fields__), "rubric")
        ratings = []
        for key in ("impact", "urgency", "effort", "strategic_fit"):
            value = data.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5):
                raise PoolError("pool_corrupt", f"rubric.{key} must be 1-5 or null", 500)
            ratings.append(value)
        note = _nullable_text(data.get("note"), "rubric.note") or ""
        scoring_version = _text(data.get("scoring_version"), "rubric.scoring_version")
        scoring_model(scoring_version)
        score = data.get("score")
        if score is not None and (
            not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100
        ):
            raise PoolError("pool_corrupt", "rubric.score must be 0-100 or null", 500)
        rated_by = _nullable_text(data.get("rated_by"), "rubric.rated_by")
        rated_at = _nullable_text(data.get("rated_at"), "rubric.rated_at")
        if any(value is not None for value in ratings):
            if any(value is None for value in ratings):
                raise PoolError("pool_corrupt", "rubric must have all four ratings or none", 500)
            if score is None:
                raise PoolError("pool_corrupt", "rubric with all four ratings requires a score", 500)
            expected = score_for_ratings(*ratings, version=scoring_version)  # type: ignore[arg-type]
            if score != expected:
                raise PoolError(
                    "pool_corrupt",
                    f"rubric.score must equal the {SCORING_VERSION} formula ({expected})",
                    500,
                )
            if not rated_by or not rated_at:
                raise PoolError("pool_corrupt", "rubric requires rated_by and rated_at", 500)
        if score is not None and any(value is None for value in ratings):
            raise PoolError("pool_corrupt", "rubric.score cannot exist without all four ratings", 500)
        if rated_at is not None:
            _validate_timestamp(rated_at, "rubric.rated_at")
        return cls(
            impact=ratings[0],
            urgency=ratings[1],
            effort=ratings[2],
            strategic_fit=ratings[3],
            note=note,
            scoring_version=scoring_version,
            score=score,
            rated_by=rated_by,
            rated_at=rated_at,
        )


@dataclass(frozen=True)
class Promotion:
    promotion_id: str
    action_id: str
    action_path: str
    action_sha: str
    promoted_by: str
    promoted_at: str
    link_state: str = "linked"

    def to_dict(self) -> dict[str, str]:
        return {
            "promotion_id": self.promotion_id,
            "action_id": self.action_id,
            "action_path": self.action_path,
            "action_sha": self.action_sha,
            "promoted_by": self.promoted_by,
            "promoted_at": self.promoted_at,
            "link_state": self.link_state,
        }

    @classmethod
    def from_dict(cls, payload: object) -> Promotion:
        data = _mapping(payload, "promotion")
        _allow(data, set(Promotion.__dataclass_fields__), "promotion")
        promotion = cls(
            promotion_id=_text(data.get("promotion_id"), "promotion.promotion_id"),
            action_id=_text(data.get("action_id"), "promotion.action_id"),
            action_path=_text(data.get("action_path"), "promotion.action_path"),
            action_sha=_text(data.get("action_sha"), "promotion.action_sha"),
            promoted_by=_text(data.get("promoted_by"), "promotion.promoted_by"),
            promoted_at=_text(data.get("promoted_at"), "promotion.promoted_at"),
            link_state=_text(data.get("link_state"), "promotion.link_state"),
        )
        if not _HASH_RE.fullmatch(promotion.action_sha):
            raise PoolError("pool_corrupt", "promotion.action_sha must be a sha256", 500)
        if promotion.link_state not in LINK_STATES:
            raise PoolError("pool_corrupt", f"promotion.link_state must be one of {LINK_STATES}", 500)
        _validate_timestamp(promotion.promoted_at, "promotion.promoted_at")
        return promotion


@dataclass(frozen=True)
class DuplicateRef:
    kind: str
    id: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id}

    @classmethod
    def from_dict(cls, payload: object) -> DuplicateRef:
        data = _mapping(payload, "duplicate_of")
        _allow(data, {"kind", "id"}, "duplicate_of")
        kind = _text(data.get("kind"), "duplicate_of.kind")
        if kind not in ("candidate", "action"):
            raise PoolError("pool_corrupt", "duplicate_of.kind must be candidate or action", 500)
        return cls(kind=kind, id=_text(data.get("id"), "duplicate_of.id"))


@dataclass(frozen=True)
class DefinitionRef:
    id: str
    version: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "version": self.version}

    @classmethod
    def from_dict(cls, payload: object) -> DefinitionRef:
        data = _mapping(payload, "definition")
        _allow(data, {"id", "version"}, "definition")
        return cls(id=_text(data.get("id"), "definition.id"), version=_text(data.get("version"), "definition.version"))


@dataclass(frozen=True)
class HistoryEntry:
    at: str
    by: str
    from_state: str | None
    to_state: str
    reason: str
    op: str
    ratings: dict[str, int] | None = None
    scoring_version: str | None = None
    score: float | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "at": self.at,
            "by": self.by,
            "from": self.from_state,
            "to": self.to_state,
            "reason": self.reason,
            "op": self.op,
        }
        if self.ratings is not None:
            data["ratings"] = dict(self.ratings)
            data["scoring_version"] = self.scoring_version
            data["score"] = self.score
        return data

    @classmethod
    def from_dict(cls, payload: object) -> HistoryEntry:
        data = _mapping(payload, "history[]")
        _allow(
            data,
            {"at", "by", "from", "to", "reason", "op", "ratings", "scoring_version", "score"},
            "history[]",
        )
        at = _text(data.get("at"), "history[].at")
        _validate_timestamp(at, "history[].at")
        from_state = data.get("from")
        if from_state is not None and from_state not in STATES:
            raise PoolError("pool_corrupt", "history[].from is not a state", 500)
        to_state = _text(data.get("to"), "history[].to")
        if to_state not in STATES:
            raise PoolError("pool_corrupt", "history[].to is not a state", 500)
        ratings = _history_ratings(data.get("ratings"))
        scoring_version = _nullable_text(data.get("scoring_version"), "history[].scoring_version")
        score = data.get("score")
        if ratings is None:
            if scoring_version is not None or score is not None:
                raise PoolError("pool_corrupt", "history[] scoring fields require all four ratings", 500)
        else:
            if scoring_version is None or score is None:
                raise PoolError("pool_corrupt", "history[] evaluation requires scoring_version and score", 500)
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
                raise PoolError("pool_corrupt", "history[].score must be 0-100", 500)
            expected = score_for_ratings(
                ratings["impact"],
                ratings["urgency"],
                ratings["effort"],
                ratings["strategic_fit"],
                version=scoring_version,
            )
            if float(score) != expected:
                raise PoolError("pool_corrupt", "history[].score does not match its ratings", 500)
        return cls(
            at=at,
            by=_text(data.get("by"), "history[].by"),
            from_state=from_state,
            to_state=to_state,
            reason=_text(data.get("reason"), "history[].reason"),
            op=_text(data.get("op"), "history[].op"),
            ratings=ratings,
            scoring_version=scoring_version,
            score=float(score) if score is not None else None,
        )


@dataclass(frozen=True)
class PoolCandidate:
    id: str
    title: str
    state: str
    state_reason: str
    source: PoolSource
    task_fields: dict[str, TaskFieldValue]
    history: tuple[HistoryEntry, ...]
    created_at: str
    updated_at: str
    revision: int = 1
    schema_version: int = CANDIDATE_SCHEMA_VERSION
    defer_until: str | None = None
    duplicate_of: DuplicateRef | None = None
    parse_quality: str | None = None
    parse_reasons: tuple[str, ...] = ()
    definition: DefinitionRef | None = None
    rubric: Rubric | None = None
    promotion: Promotion | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "schema_version": self.schema_version,
            "revision": self.revision,
            "title": self.title,
            "state": self.state,
            "state_reason": self.state_reason,
            "defer_until": self.defer_until,
            "duplicate_of": self.duplicate_of.to_dict() if self.duplicate_of else None,
            "source": self.source.to_dict(),
            "task_fields": {key: self.task_fields[key].to_dict() for key in TASK_FIELD_KEYS},
            "parse_quality": self.parse_quality,
            "parse_reasons": list(self.parse_reasons),
            "definition": self.definition.to_dict() if self.definition else None,
            "rubric": self.rubric.to_dict() if self.rubric else None,
            "promotion": self.promotion.to_dict() if self.promotion else None,
            "history": [entry.to_dict() for entry in self.history],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> PoolCandidate:
        data = _mapping(payload, "candidate")
        _allow(data, set(PoolCandidate.__dataclass_fields__), "candidate")
        schema_version = data.get("schema_version")
        if schema_version != CANDIDATE_SCHEMA_VERSION:
            raise PoolError("pool_version", f"Unsupported candidate schema: {schema_version}", 409)
        task_payload = _mapping(data.get("task_fields"), "task_fields")
        _allow(task_payload, set(TASK_FIELD_KEYS), "task_fields")
        if set(task_payload) != set(TASK_FIELD_KEYS):
            raise PoolError("pool_corrupt", f"task_fields must contain exactly {TASK_FIELD_KEYS}", 500)
        task_fields = {key: TaskFieldValue.from_dict(task_payload[key], key=key) for key in TASK_FIELD_KEYS}
        history_payload = data.get("history")
        if not isinstance(history_payload, list):
            raise PoolError("pool_corrupt", "history must be a list", 500)
        history = tuple(HistoryEntry.from_dict(entry) for entry in history_payload)
        candidate = cls(
            id=_text(data.get("id"), "id"),
            schema_version=schema_version,
            revision=_int(data.get("revision"), "revision", minimum=1),
            title=_text(data.get("title"), "title"),
            state=_text(data.get("state"), "state"),
            state_reason=_nullable_text(data.get("state_reason"), "state_reason") or "",
            defer_until=_nullable_text(data.get("defer_until"), "defer_until"),
            duplicate_of=(
                DuplicateRef.from_dict(data["duplicate_of"]) if data.get("duplicate_of") is not None else None
            ),
            source=PoolSource.from_dict(data.get("source")),
            task_fields=task_fields,
            parse_quality=_nullable_text(data.get("parse_quality"), "parse_quality"),
            parse_reasons=_text_list(data.get("parse_reasons"), "parse_reasons"),
            definition=(DefinitionRef.from_dict(data["definition"]) if data.get("definition") is not None else None),
            rubric=Rubric.from_dict(data["rubric"]) if data.get("rubric") is not None else None,
            promotion=(Promotion.from_dict(data["promotion"]) if data.get("promotion") is not None else None),
            history=history,
            created_at=_text(data.get("created_at"), "created_at"),
            updated_at=_text(data.get("updated_at"), "updated_at"),
        )
        _validate_candidate(candidate)
        return candidate


@dataclass(frozen=True)
class MeetingExtraction:
    meeting_id: str
    path: str
    title: str
    date: str | None
    content_hash: str
    eligibility: str
    reason: str
    extraction_version: str
    candidate_ids: tuple[str, ...]
    extracted_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "meeting_id": self.meeting_id,
            "path": self.path,
            "title": self.title,
            "date": self.date,
            "content_hash": self.content_hash,
            "eligibility": self.eligibility,
            "reason": self.reason,
            "extraction_version": self.extraction_version,
            "candidate_ids": list(self.candidate_ids),
            "extracted_at": self.extracted_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> MeetingExtraction:
        data = _mapping(payload, "meetings[]")
        _allow(data, set(MeetingExtraction.__dataclass_fields__), "meetings[]")
        eligibility = _text(data.get("eligibility"), "meetings[].eligibility")
        if eligibility not in ("eligible", "skipped"):
            raise PoolError("pool_corrupt", "meetings[].eligibility must be eligible or skipped", 500)
        content_hash = _text(data.get("content_hash"), "meetings[].content_hash")
        if not _HASH_RE.fullmatch(content_hash):
            raise PoolError("pool_corrupt", "meetings[].content_hash must be a sha256", 500)
        cached = data.get("candidate_ids")
        if not isinstance(cached, list):
            raise PoolError("pool_corrupt", "meetings[].candidate_ids must be a list", 500)
        meeting = cls(
            meeting_id=_text(data.get("meeting_id"), "meetings[].meeting_id"),
            path=_text(data.get("path"), "meetings[].path"),
            title=_text(data.get("title"), "meetings[].title"),
            date=_nullable_text(data.get("date"), "meetings[].date"),
            content_hash=content_hash,
            eligibility=eligibility,
            reason=_text(data.get("reason"), "meetings[].reason"),
            extraction_version=_text(data.get("extraction_version"), "meetings[].extraction_version"),
            candidate_ids=tuple(_text(item, "meetings[].candidate_ids[]") for item in cached),
            extracted_at=_text(data.get("extracted_at"), "meetings[].extracted_at"),
        )
        if meeting.date is not None:
            _validate_date(meeting.date, "meetings[].date")
        _validate_timestamp(meeting.extracted_at, "meetings[].extracted_at")
        return meeting


@dataclass(frozen=True)
class PoolAuditEvent:
    at: str
    by: str
    verb: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"at": self.at, "by": self.by, "verb": self.verb, "reason": self.reason}

    @classmethod
    def from_dict(cls, payload: object) -> PoolAuditEvent:
        data = _mapping(payload, "audit[]")
        _allow(data, {"at", "by", "verb", "reason"}, "audit[]")
        at = _text(data.get("at"), "audit[].at")
        _validate_timestamp(at, "audit[].at")
        return cls(
            at=at,
            by=_text(data.get("by"), "audit[].by"),
            verb=_text(data.get("verb"), "audit[].verb"),
            reason=_text(data.get("reason"), "audit[].reason"),
        )


@dataclass(frozen=True)
class PoolManifest:
    pool_start_at: str
    pool_start_timezone: str
    pool_start_local_date: str
    candidates: tuple[PoolCandidate, ...] = ()
    meetings: tuple[MeetingExtraction, ...] = ()
    audit: tuple[PoolAuditEvent, ...] = ()
    revision: int = 1
    schema_version: int = POOL_SCHEMA_VERSION
    candidate_schema_version: int = CANDIDATE_SCHEMA_VERSION
    scoring_version: str = SCORING_VERSION
    extraction_version: str = EXTRACTION_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_schema_version": self.candidate_schema_version,
            "pool_start_at": self.pool_start_at,
            "pool_start_timezone": self.pool_start_timezone,
            "pool_start_local_date": self.pool_start_local_date,
            "scoring_version": self.scoring_version,
            "extraction_version": self.extraction_version,
            "revision": self.revision,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "meetings": [meeting.to_dict() for meeting in self.meetings],
            "audit": [event.to_dict() for event in self.audit],
        }

    @classmethod
    def from_dict(cls, payload: object) -> PoolManifest:
        data = _mapping(payload, "pool")
        _allow(data, set(PoolManifest.__dataclass_fields__), "pool")
        schema_version = data.get("schema_version")
        if schema_version != POOL_SCHEMA_VERSION:
            raise PoolError("pool_version", f"Unsupported pool schema: {schema_version}", 409)
        candidate_schema_version = data.get("candidate_schema_version")
        if candidate_schema_version != CANDIDATE_SCHEMA_VERSION:
            raise PoolError("pool_version", f"Unsupported candidate schema: {candidate_schema_version}", 409)
        candidate_payload = data.get("candidates")
        if not isinstance(candidate_payload, list):
            raise PoolError("pool_corrupt", "candidates must be a list", 500)
        meeting_payload = data.get("meetings", [])
        if not isinstance(meeting_payload, list):
            raise PoolError("pool_corrupt", "meetings must be a list", 500)
        audit_payload = data.get("audit", [])
        if not isinstance(audit_payload, list):
            raise PoolError("pool_corrupt", "audit must be a list", 500)
        manifest = cls(
            schema_version=schema_version,
            candidate_schema_version=candidate_schema_version,
            pool_start_at=_text(data.get("pool_start_at"), "pool_start_at"),
            pool_start_timezone=_text(data.get("pool_start_timezone"), "pool_start_timezone"),
            pool_start_local_date=_text(data.get("pool_start_local_date"), "pool_start_local_date"),
            scoring_version=_text(data.get("scoring_version"), "scoring_version"),
            extraction_version=_text(data.get("extraction_version"), "extraction_version"),
            revision=_int(data.get("revision"), "revision", minimum=1),
            candidates=tuple(PoolCandidate.from_dict(item) for item in candidate_payload),
            meetings=tuple(MeetingExtraction.from_dict(item) for item in meeting_payload),
            audit=tuple(PoolAuditEvent.from_dict(item) for item in audit_payload),
        )
        validate_manifest(manifest)
        return manifest


@dataclass(frozen=True)
class PoolDefinitionField:
    key: str
    name: str
    type: str
    options: tuple[str, ...] = ()
    target: str | None = None
    inherited: bool = True
    source: str = "task"


@dataclass(frozen=True)
class PoolDefinition:
    id: str
    name: str
    base: str
    entity_type: str
    version: str
    fields: tuple[PoolDefinitionField, ...]
    errors: tuple[str, ...]
    source: str

    def field(self, key: str) -> PoolDefinitionField | None:
        return next((field for field in self.fields if field.key == key), None)


@dataclass(frozen=True)
class PoolDiagnostics:
    """Safe, evidence-free recovery diagnostics for the read model."""

    revision: int
    schema_version: int
    candidate_schema_version: int
    scoring_version: str
    extraction_version: str
    backup_present: bool
    journal_present: bool
    backup_count: int = 0
    journal_count: int = 0


@dataclass(frozen=True)
class PoolView:
    manifest: PoolManifest
    definition: PoolDefinition
    permission_warnings: tuple[str, ...] = ()
    diagnostics: PoolDiagnostics | None = None


def read_pool(vault_root: str | Path, runtime_root: str | Path) -> PoolView:
    """Read and validate the pool, definition presentation, permissions, and diagnostics."""
    assert_recovered(runtime_root)
    manifest = read_manifest(runtime_root)
    definition = read_definition(vault_root)
    return PoolView(
        manifest=manifest,
        definition=definition,
        permission_warnings=permission_warnings(runtime_root),
        diagnostics=_runtime_diagnostics(manifest, runtime_root),
    )


def _runtime_diagnostics(manifest: PoolManifest, runtime_root: str | Path) -> PoolDiagnostics:
    root = Path(runtime_root).expanduser().resolve()
    backups = tuple(path for path in (root / "backups").glob("backup-*/file-*") if path.is_file())
    journals = tuple(path for path in (root / "journal").glob("*.json") if path.is_file())
    return PoolDiagnostics(
        revision=manifest.revision,
        schema_version=manifest.schema_version,
        candidate_schema_version=manifest.candidate_schema_version,
        scoring_version=manifest.scoring_version,
        extraction_version=manifest.extraction_version,
        backup_present=bool(backups),
        journal_present=bool(journals),
        backup_count=len(backups),
        journal_count=len(journals),
    )


def read_manifest(runtime_root: str | Path) -> PoolManifest:
    """Read the runtime manifest; a missing file is not initialized, never auto-created."""
    target = pool_path(runtime_root)
    if not target.exists():
        raise PoolError("pool_not_initialized", "The potential-task pool is not initialized.", 409)
    if not target.is_file():
        raise PoolError("pool_corrupt", "The pool record is not a regular file.", 500)
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise PoolError("pool_corrupt", f"The pool record could not be read: {exc}", 500) from exc
    return PoolManifest.from_dict(payload)


def assert_recovered(runtime_root: str | Path) -> None:
    """Fail closed while any gateway journal is uncommitted or unreadable."""
    journal_dir = Path(runtime_root).expanduser().resolve() / "journal"
    if not journal_dir.is_dir():
        return
    for journal in sorted(journal_dir.glob("*.json")):
        try:
            record = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PoolError(
                "pool_recovery_required",
                f"An incomplete transaction journal could not be read: {journal}",
                409,
            ) from exc
        if not isinstance(record, dict):
            raise PoolError(
                "pool_recovery_required",
                f"An incomplete transaction journal is malformed: {journal}",
                409,
            )
        if not record.get("committed") and not record.get("rolled_back"):
            raise PoolError(
                "pool_recovery_required",
                f"An unresolved transaction journal must be recovered first: {journal}",
                409,
            )


def read_definition(vault_root: str | Path) -> PoolDefinition:
    """Read the optional ``potential-task`` supertag presentation; never fail the pool."""
    root = Path(vault_root).expanduser().resolve()
    registry = build_registry(scan_vault(root), root, WorkGeneration())
    tag = registry.get(DEFAULT_DEFINITION_ID)
    if tag is None:
        return default_definition()
    return _definition_from_tag(tag)


def default_definition() -> PoolDefinition:
    return PoolDefinition(
        id=DEFAULT_DEFINITION_ID,
        name="Potential task",
        base="task",
        entity_type="action",
        version=DEFAULT_DEFINITION_VERSION,
        fields=(
            PoolDefinitionField("project", "Project", "reference", target="project"),
            PoolDefinitionField("owners", "Owners", "multi_reference", target="person"),
            PoolDefinitionField("due", "Due", "date"),
            PoolDefinitionField("priority", "Priority", "select", options=PRIORITIES),
        ),
        errors=(),
        source="default",
    )


def definition_version(tag: Supertag) -> str:
    """Return a deterministic version of the definition's field metadata."""
    fields = [
        {
            "key": field.key,
            "name": field.name,
            "type": field.type,
            "required": field.required,
            "optional": field.optional,
            "default": field.default,
            "options": list(field.options),
            "target": field.target,
            "inherited": field.inherited,
            "source": field.source,
        }
        for field in tag.fields
    ]
    payload = json.dumps(
        {"id": tag.id, "base": tag.base, "extends": tag.extends, "fields": fields},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def candidate_definition_status(candidate: PoolCandidate, definition: PoolDefinition) -> str:
    """Return ``current``, ``changed``, or ``unset`` for presentation warnings."""
    if candidate.definition is None:
        return "unset"
    return "current" if candidate.definition.version == definition.version else "changed"


def transition_candidate(
    candidate: PoolCandidate,
    to_state: str,
    *,
    by: str,
    reason: str,
    at: datetime | None = None,
    defer_until: str | None = None,
    duplicate_of: DuplicateRef | None = None,
    promotion: Promotion | None = None,
    op: str = "transition",
) -> PoolCandidate:
    """Apply one legal lifecycle transition with an audited history entry."""
    by = _text(by, "by")
    reason = _text(reason, "reason")
    when = (at or datetime.now(UTC)).astimezone(UTC).isoformat()
    if to_state not in STATES:
        raise PoolError("invalid_state", f"Unknown state: {to_state}", 422)
    if to_state not in TRANSITIONS[candidate.state]:
        raise PoolError(
            "invalid_state",
            f"Cannot move a candidate from {candidate.state} to {to_state}.",
            422,
        )
    new_defer: str | None = None
    new_duplicate: DuplicateRef | None = None
    new_promotion: Promotion | None = None
    if to_state == "deferred":
        if defer_until is None:
            raise PoolError("invalid_state", "A deferred candidate requires defer_until.", 422)
        _validate_date(defer_until, "defer_until")
        new_defer = defer_until
    elif to_state == "duplicate":
        if duplicate_of is None:
            raise PoolError("invalid_state", "A duplicate candidate requires a survivor.", 422)
        new_duplicate = duplicate_of
    elif to_state == "promoted":
        if promotion is None:
            raise PoolError("invalid_state", "A promoted candidate requires an action link.", 422)
        new_promotion = promotion
    updated = replace(
        candidate,
        state=to_state,
        state_reason=reason,
        defer_until=new_defer,
        duplicate_of=new_duplicate,
        promotion=new_promotion,
        history=(
            *candidate.history,
            HistoryEntry(
                at=when,
                by=by,
                from_state=candidate.state,
                to_state=to_state,
                reason=reason,
                op=op,
            ),
        ),
        revision=candidate.revision + 1,
        updated_at=when,
    )
    _validate_candidate(updated)
    return updated


def validate_manifest(manifest: PoolManifest) -> None:
    """Validate the complete manifest, including duplicate references."""
    if manifest.schema_version != POOL_SCHEMA_VERSION:
        raise PoolError("pool_version", f"Unsupported pool schema: {manifest.schema_version}", 409)
    if manifest.candidate_schema_version != CANDIDATE_SCHEMA_VERSION:
        raise PoolError("pool_version", f"Unsupported candidate schema: {manifest.candidate_schema_version}", 409)
    scoring_model(manifest.scoring_version)
    if manifest.revision < 1:
        raise PoolError("pool_corrupt", "revision must be at least 1", 500)
    _validate_start(manifest.pool_start_at, manifest.pool_start_timezone, manifest.pool_start_local_date)
    ids = [candidate.id for candidate in manifest.candidates]
    if len(ids) != len(set(ids)):
        raise PoolError("pool_corrupt", "Candidate ids must be unique", 500)
    by_id = {candidate.id: candidate for candidate in manifest.candidates}
    for candidate in manifest.candidates:
        _validate_candidate(candidate, by_id=by_id)
    meeting_ids = [meeting.meeting_id for meeting in manifest.meetings]
    if len(meeting_ids) != len(set(meeting_ids)):
        raise PoolError("pool_corrupt", "Meeting ids must be unique", 500)


def _validate_candidate(candidate: PoolCandidate, *, by_id: dict[str, PoolCandidate] | None = None) -> None:
    if not _CANDIDATE_ID_RE.fullmatch(candidate.id):
        raise PoolError("pool_corrupt", f"Invalid candidate id: {candidate.id!r}", 500)
    if candidate.schema_version != CANDIDATE_SCHEMA_VERSION:
        raise PoolError("pool_version", "Unsupported candidate schema", 409)
    if candidate.revision < 1:
        raise PoolError("pool_corrupt", "Candidate revision must be at least 1", 500)
    if not candidate.title.strip():
        raise PoolError("pool_corrupt", "Candidate title must not be empty", 500)
    if candidate.state not in STATES:
        raise PoolError("pool_corrupt", f"Invalid candidate state: {candidate.state}", 500)
    _validate_timestamp(candidate.created_at, "created_at")
    _validate_timestamp(candidate.updated_at, "updated_at")
    _validate_source(candidate.source)
    if set(candidate.task_fields) != set(TASK_FIELD_KEYS):
        raise PoolError("pool_corrupt", f"task_fields must contain exactly {TASK_FIELD_KEYS}", 500)
    for key, value in candidate.task_fields.items():
        for item in (value.extracted, value.human, value.effective):
            _validate_task_value(key, item, f"task_fields.{key}")
        expected = value.human if value.human is not None else value.extracted
        if value.effective != expected:
            raise PoolError("pool_corrupt", f"task_fields.{key}.effective is inconsistent", 500)
    if candidate.parse_quality is not None and candidate.parse_quality not in PARSE_QUALITIES:
        raise PoolError("pool_corrupt", f"Invalid parse_quality: {candidate.parse_quality}", 500)
    if candidate.definition is not None and (not candidate.definition.id or not candidate.definition.version):
        raise PoolError("pool_corrupt", "definition id/version must not be empty", 500)
    if candidate.state == "deferred":
        if candidate.defer_until is None:
            raise PoolError("pool_corrupt", "Deferred candidate lacks defer_until", 500)
        _validate_date(candidate.defer_until, "defer_until")
        if candidate.duplicate_of is not None or candidate.promotion is not None:
            raise PoolError("pool_corrupt", "Deferred candidate has incompatible links", 500)
    elif candidate.defer_until is not None:
        raise PoolError("pool_corrupt", "defer_until is only valid while deferred", 500)
    if candidate.state == "duplicate":
        if candidate.duplicate_of is None:
            raise PoolError("pool_corrupt", "Duplicate candidate lacks duplicate_of", 500)
        if candidate.duplicate_of.id == candidate.id:
            raise PoolError("pool_corrupt", "A candidate cannot duplicate itself", 500)
        if by_id is not None and candidate.duplicate_of.kind == "candidate":
            survivor = by_id.get(candidate.duplicate_of.id)
            if survivor is None:
                raise PoolError("pool_corrupt", "Duplicate target candidate does not exist", 500)
            if survivor.state in ("obsolete", "rejected"):
                raise PoolError("pool_corrupt", "Duplicate target must be a surviving candidate", 500)
        if candidate.promotion is not None:
            raise PoolError("pool_corrupt", "Duplicate candidate has a promotion link", 500)
    elif candidate.duplicate_of is not None:
        raise PoolError("pool_corrupt", "duplicate_of is only valid while duplicate", 500)
    if candidate.state == "promoted":
        if candidate.promotion is None:
            raise PoolError("pool_corrupt", "Promoted candidate lacks a promotion link", 500)
    elif candidate.promotion is not None:
        raise PoolError("pool_corrupt", "Only promoted candidates carry a promotion link", 500)
    if candidate.history:
        last = candidate.history[-1]
        if last.to_state != candidate.state:
            raise PoolError("pool_corrupt", "The last history entry must match the candidate state", 500)


def _validate_source(source: PoolSource) -> None:
    if source.kind == "meeting":
        if not source.meeting_id or not source.meeting_path:
            raise PoolError("pool_corrupt", "Meeting source lacks id/path", 500)
        if not source.content_hash or not _HASH_RE.fullmatch(source.content_hash):
            raise PoolError("pool_corrupt", "Meeting source hash must be a sha256", 500)
        if source.line is None or source.line < 1 or source.occurrence is None or source.occurrence < 0:
            raise PoolError("pool_corrupt", "Meeting source line/occurrence is invalid", 500)
        if not source.quote or not source.rule_version or not source.extracted_at:
            raise PoolError("pool_corrupt", "Meeting source lacks quote/rule/extracted_at", 500)
        _validate_timestamp(source.extracted_at, "source.extracted_at")
        if source.meeting_date is not None:
            _validate_date(source.meeting_date, "source.meeting_date")
        if (
            source.initiated_by is not None
            or source.provenance_classification is not None
            or source.provenance_note is not None
        ):
            raise PoolError("pool_corrupt", "Meeting source cannot carry manual provenance", 500)
    elif source.kind == "manual":
        if not source.initiated_by or not source.provenance_note:
            raise PoolError("pool_corrupt", "Manual source lacks initiator/provenance note", 500)
        if source.provenance_classification not in MANUAL_PROVENANCE_CLASSES:
            raise PoolError("pool_corrupt", "Manual source has an invalid provenance classification", 500)
        if source.content_hash is not None or source.quote is not None or source.line is not None:
            raise PoolError("pool_corrupt", "Manual source must not fabricate hash/quote/line", 500)
        if source.occurrence is not None or source.rule_version is not None or source.extracted_at is not None:
            raise PoolError("pool_corrupt", "Manual source cannot carry extraction metadata", 500)
        if source.meeting_date is not None:
            _validate_date(source.meeting_date, "source.meeting_date")
    else:
        raise PoolError("pool_corrupt", f"Invalid source kind: {source.kind}", 500)


def _validate_start(pool_start_at: str, timezone: str, local_date: str) -> None:
    try:
        start = datetime.fromisoformat(pool_start_at)
    except ValueError as exc:
        raise PoolError("pool_corrupt", "pool_start_at must be an ISO timestamp", 500) from exc
    if start.tzinfo is None or start.utcoffset() != timedelta(0):
        raise PoolError("pool_corrupt", "pool_start_at must be a UTC timestamp", 500)
    try:
        zone = pool_zone(timezone)
    except PoolError as exc:
        raise PoolError("pool_corrupt", f"Unknown pool timezone: {timezone}", 500) from exc
    _validate_date(local_date, "pool_start_local_date")
    expected = start.astimezone(zone).date().isoformat()
    if expected != local_date:
        raise PoolError(
            "pool_corrupt",
            f"pool_start_local_date {local_date} does not match {expected} in {timezone}",
            500,
        )


def _definition_from_tag(tag: Supertag) -> PoolDefinition:
    defaults = {field.key: field for field in default_definition().fields}
    fields: list[PoolDefinitionField] = []
    errors = list(tag.errors)
    for key in ("project", "owners", "due", "priority"):
        definition_field = tag.field(key)
        if definition_field is None:
            fields.append(defaults[key])
            errors.append(f"definition field {key!r} missing; using default presentation")
            continue
        fields.append(
            PoolDefinitionField(
                key=key,
                name=definition_field.name,
                type=definition_field.type,
                options=tuple(definition_field.options),
                target=definition_field.target,
                inherited=definition_field.inherited,
                source=definition_field.source,
            )
        )
    return PoolDefinition(
        id=tag.id,
        name=tag.name,
        base=tag.base,
        entity_type=tag.entity_type,
        version=definition_version(tag),
        fields=tuple(fields),
        errors=tuple(errors),
        source="vault",
    )


def _validate_task_value(key: str, value: str | None, path: str) -> None:
    if value is None:
        return
    if key in ("project", "owner"):
        if not value.strip():
            raise PoolError("pool_corrupt", f"{path} must not be blank", 500)
    elif key == "due":
        _validate_date(value, path)
    elif key == "priority" and value not in PRIORITIES:
        raise PoolError("pool_corrupt", f"{path} must be P1-P4", 500)


def _validate_date(value: str, path: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise PoolError("pool_corrupt", f"{path} must be an ISO date", 500) from exc


def _validate_timestamp(value: str, path: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PoolError("pool_corrupt", f"{path} must be an ISO timestamp", 500) from exc
    if parsed.tzinfo is None:
        raise PoolError("pool_corrupt", f"{path} must include a timezone", 500)


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PoolError("pool_corrupt", f"{path} must be an object", 500)
    return value


def _allow(data: dict[str, Any], allowed: set[str], path: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise PoolError("pool_corrupt", f"{path} has unknown fields: {sorted(extra)}", 500)


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PoolError("pool_corrupt", f"{path} must be a non-empty string", 500)
    return value


def _nullable_text(value: object, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PoolError("pool_corrupt", f"{path} must be a string or null", 500)
    return value


def _int(value: object, path: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PoolError("pool_corrupt", f"{path} must be an integer", 500)
    if minimum is not None and value < minimum:
        raise PoolError("pool_corrupt", f"{path} must be at least {minimum}", 500)
    return value


def _nullable_int(value: object, path: str) -> int | None:
    if value is None:
        return None
    return _int(value, path)


def _text_list(value: object, path: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PoolError("pool_corrupt", f"{path} must be a list", 500)
    return tuple(_text(item, f"{path}[]") for item in value)


def _history_ratings(value: object) -> dict[str, int] | None:
    if value is None:
        return None
    data = _mapping(value, "history[].ratings")
    _allow(data, {"impact", "urgency", "effort", "strategic_fit"}, "history[].ratings")
    ratings: dict[str, int] = {}
    for key in ("impact", "urgency", "effort", "strategic_fit"):
        item = data.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 5:
            raise PoolError("pool_corrupt", f"history[].ratings.{key} must be 1-5", 500)
        ratings[key] = item
    return ratings
