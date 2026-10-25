"""The work-generation write path: snapshot legacy work into ``user_state``.

No vault content is modified. The record is written through the safety gateway with a named
reviewer, a human-readable reason, a SHA precondition on updates, and the standard backup and
rollback. A reset writes generation 1 with an empty set; nothing is deleted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.generation import (
    CUTOVER_GENERATION,
    FIRST_GENERATION,
    GENERATION_FILENAME,
    WorkGeneration,
    generation_path,
    read_generation,
)
from worksync.work.models import EntityType, entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.since_last_check import USER_STATE_ZONE

CUTOVER_VERB = "cut_over_work"
RESET_VERB = "reset_work_generation"


class GenerationError(ValueError):
    """Raised when a generation cutover cannot be recorded."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def cut_over(
    vault: str | Path,
    runtime: str | Path,
    *,
    reviewer: str,
    reason: str,
    now: str | None = None,
) -> CommitResult:
    """Freeze every existing action and ticket as legacy reference, once.

    The snapshot covers all statuses, so reopening an old note cannot make it live again.
    A second cutover is refused: reset the generation first if a new boundary is intended.
    """
    _require(reviewer, reason)
    existing = read_generation(runtime)
    if existing.cut_over:
        raise GenerationError(
            "already_cut_over",
            "A work generation cutover is already recorded; reset the generation first.",
        )
    index = WorkIndex.from_vault(vault)
    actions = sorted((entity for entity in index.entities if entity.entity_type is EntityType.ACTION), key=entity_id_of)
    tickets = sorted((entity for entity in index.entities if entity.entity_type is EntityType.TICKET), key=entity_id_of)
    when = _resolve_now(now)
    generation = WorkGeneration(
        generation=CUTOVER_GENERATION,
        legacy_action_ids=tuple(entity_id_of(entity) for entity in actions),
        legacy_action_paths=tuple(entity.path for entity in actions),
        legacy_ticket_ids=tuple(entity_id_of(entity) for entity in tickets),
        legacy_ticket_paths=tuple(entity.path for entity in tickets),
        cutover_at=when.isoformat(),
        reviewer=str(reviewer).strip(),
        reason=str(reason).strip(),
    )
    return _write(vault, runtime, generation, verb=CUTOVER_VERB, when=when)


def reset_generation(
    vault: str | Path,
    runtime: str | Path,
    *,
    reviewer: str,
    reason: str,
    now: str | None = None,
) -> CommitResult:
    """Restore legacy work to the live set by writing generation 1."""
    _require(reviewer, reason)
    when = _resolve_now(now)
    generation = WorkGeneration(
        generation=FIRST_GENERATION,
        cutover_at=when.isoformat(),
        reviewer=str(reviewer).strip(),
        reason=str(reason).strip(),
    )
    return _write(vault, runtime, generation, verb=RESET_VERB, when=when)


def _require(reviewer: str, reason: str) -> None:
    if not str(reviewer).strip():
        raise GenerationError("missing_reviewer", "A generation change requires a named reviewer.")
    if not str(reason).strip():
        raise GenerationError("missing_reason", "A generation change requires a human-readable reason.")


def _resolve_now(now: str | None) -> datetime:
    return datetime.fromisoformat(now) if now is not None else datetime.now(UTC)


def _write(
    vault: str | Path,
    runtime: str | Path,
    generation: WorkGeneration,
    *,
    verb: str,
    when: datetime,
) -> CommitResult:
    target = generation_path(runtime)
    content = json.dumps(generation.to_dict(), sort_keys=True, ensure_ascii=False)
    if target.is_file():
        op = FileOp(
            "update",
            Path(GENERATION_FILENAME),
            USER_STATE_ZONE,
            content=content,
            expected=sha256_file(target),
        )
    else:
        op = FileOp("create", Path(GENERATION_FILENAME), USER_STATE_ZONE, content=content)
    changeset = ChangeSet(verb=verb, ops=(op,), reviewer=generation.reviewer, reason=generation.reason)
    return commit(changeset, write_zones(vault, runtime), confirmed=True, now=when)
