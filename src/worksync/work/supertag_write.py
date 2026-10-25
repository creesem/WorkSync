"""Apply or remove a supertag as one atomic, hash-checked canonical write.

Adding a tag never changes the canonical entity type. Applying writes only missing field
defaults; removing deletes only the ``supertags`` entry and keeps every field value. The
safety gateway supplies the SHA precondition, backup, journal, and rollback.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import scan_vault, set_frontmatter_values
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp, MutationError
from worksync.safety.zones import write_zones
from worksync.work.generation import read_generation
from worksync.work.models import EntityBase, entity_id_of
from worksync.work.supertags import BASE_ENTITY_TYPES, Supertag, SupertagView, build_view

APPLY_VERB = "apply_supertag"
REMOVE_VERB = "remove_supertag"
_ENTITY_BASE: dict[str, str] = {value: key for key, value in BASE_ENTITY_TYPES.items()}


class SupertagWriteError(ValueError):
    """A user-facing apply/remove failure; nothing partial survives."""

    def __init__(self, code: str, message: str, status: int = 422, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.affected = tuple(affected)


@dataclass(frozen=True)
class SupertagWriteResult:
    """The visible outcome of one apply/remove transaction."""

    path: str
    committed: bool
    sha: str | None
    journal: Path | None
    changes: tuple[dict, ...]
    tags: tuple[str, ...]
    defaults_written: tuple[str, ...] = ()


def apply_supertag(
    vault: str | Path,
    runtime: str | Path,
    entity_id: str,
    supertag_id: str,
    *,
    reviewer: str,
    reason: str,
    expected: str | None = None,
    confirmed: bool = False,
) -> SupertagWriteResult:
    """Add one custom supertag plus its missing defaults, atomically."""
    entity_id = str(entity_id or "").strip()
    supertag_id = str(supertag_id or "").strip()
    reason = str(reason or "").strip()
    reviewer = str(reviewer or "").strip()
    if not entity_id:
        raise SupertagWriteError("invalid_target", "An entity id is required.", 400)
    if not supertag_id:
        raise SupertagWriteError("invalid_supertag", "A supertag id is required.", 400)
    if not reason:
        raise SupertagWriteError("missing_reason", "A reason is required.", 400)
    if not reviewer:
        raise SupertagWriteError("missing_reviewer", "A reviewer is required.", 400)

    vault_root = Path(vault).expanduser().resolve()
    view = _view(vault_root, runtime)
    entity = _entity(view, entity_id)
    current = _current_tags(entity)
    if supertag_id in current:
        return _noop(entity, current)
    _validate_existing(view, entity, current)
    tag = _target_tag(view, entity, supertag_id)
    defaults = _defaults(tag, entity)
    new_tags = [*current, tag.id]
    note_content, current_sha = _read_note(vault_root, entity.path, expected)
    new_content = _frontmatter_content(note_content, {"supertags": new_tags, **defaults}, entity.path)
    committed = _commit(
        vault_root,
        runtime,
        verb=APPLY_VERB,
        relative=entity.path,
        content=new_content,
        expected=current_sha,
        reviewer=reviewer,
        reason=reason,
        confirmed=confirmed,
    )
    return SupertagWriteResult(
        path=entity.path,
        committed=committed.committed,
        sha=hashlib.sha256(new_content.encode("utf-8")).hexdigest(),
        journal=committed.journal,
        changes=committed.changes,
        tags=_custom_tags(entity, new_tags),
        defaults_written=tuple(defaults),
    )


def remove_supertag(
    vault: str | Path,
    runtime: str | Path,
    entity_id: str,
    supertag_id: str,
    *,
    reviewer: str,
    reason: str,
    expected: str | None = None,
    confirmed: bool = False,
) -> SupertagWriteResult:
    """Remove one custom supertag entry; every field value remains in the note."""
    entity_id = str(entity_id or "").strip()
    supertag_id = str(supertag_id or "").strip()
    reason = str(reason or "").strip()
    reviewer = str(reviewer or "").strip()
    if not entity_id:
        raise SupertagWriteError("invalid_target", "An entity id is required.", 400)
    if not supertag_id:
        raise SupertagWriteError("invalid_supertag", "A supertag id is required.", 400)
    if not reason:
        raise SupertagWriteError("missing_reason", "A reason is required.", 400)
    if not reviewer:
        raise SupertagWriteError("missing_reviewer", "A reviewer is required.", 400)

    vault_root = Path(vault).expanduser().resolve()
    view = _view(vault_root, runtime)
    entity = _entity(view, entity_id)
    current = _current_tags(entity)
    _target_tag_for_removal(view, supertag_id)
    if supertag_id not in current:
        return _noop(entity, current)
    new_tags = [tag_id for tag_id in current if tag_id != supertag_id]
    note_content, current_sha = _read_note(vault_root, entity.path, expected)
    new_content = _frontmatter_content(note_content, {"supertags": new_tags or None}, entity.path)
    committed = _commit(
        vault_root,
        runtime,
        verb=REMOVE_VERB,
        relative=entity.path,
        content=new_content,
        expected=current_sha,
        reviewer=reviewer,
        reason=reason,
        confirmed=confirmed,
    )
    return SupertagWriteResult(
        path=entity.path,
        committed=committed.committed,
        sha=hashlib.sha256(new_content.encode("utf-8")).hexdigest(),
        journal=committed.journal,
        changes=committed.changes,
        tags=_custom_tags(entity, new_tags),
    )


def _frontmatter_content(content: str, values: dict[str, object], relative: str) -> str:
    try:
        return set_frontmatter_values(content, values)
    except ValueError as exc:
        raise SupertagWriteError(
            "invalid_frontmatter",
            f"Cannot edit the note's frontmatter: {exc}",
            422,
            affected=(relative,),
        ) from exc


def _view(vault_root: Path, runtime: str | Path) -> SupertagView:
    try:
        generation = read_generation(runtime)
    except ValueError as exc:
        raise SupertagWriteError(
            "invalid_generation",
            "The work generation record is invalid; refusing to write.",
            500,
        ) from exc
    return build_view(scan_vault(vault_root), vault_root, generation)


def _entity(view: SupertagView, entity_id: str) -> EntityBase:
    entity = next((candidate for candidate in view.live.entities if entity_id_of(candidate) == entity_id), None)
    if entity is None:
        raise SupertagWriteError("unknown_entity", f"No live entity with id: {entity_id}", 404, affected=(entity_id,))
    return entity


def _current_tags(entity: EntityBase) -> list[str]:
    raw = entity.raw.get("supertags")
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return list(dict.fromkeys(item.strip() for item in raw if item.strip()))
    raise SupertagWriteError(
        "invalid_supertag",
        "The note's supertags field must be a list of ids.",
        422,
        affected=(entity.path,),
    )


def _validate_existing(view: SupertagView, entity: EntityBase, current: list[str]) -> None:
    base_id = _ENTITY_BASE.get(entity.entity_type.value)
    for tag_id in current:
        if tag_id == base_id:
            continue
        tag = view.registry.get(tag_id)
        if tag is None:
            raise SupertagWriteError(
                "unknown_supertag",
                f"The note has an unknown supertag: {tag_id}",
                422,
                affected=(tag_id,),
            )
        if tag.errors:
            raise SupertagWriteError(
                "invalid_supertag",
                f"The note has an invalid supertag: {tag_id}",
                422,
                affected=(tag_id,),
            )
        if tag.entity_type != entity.entity_type.value:
            raise SupertagWriteError(
                "base_mismatch",
                f"The note has a supertag for the wrong base: {tag_id}",
                422,
                affected=(tag_id,),
            )


def _target_tag(view: SupertagView, entity: EntityBase, supertag_id: str) -> Supertag:
    tag = view.registry.get(supertag_id)
    if tag is None:
        raise SupertagWriteError(
            "unknown_supertag", f"No supertag with id: {supertag_id}", 404, affected=(supertag_id,)
        )
    if tag.builtin:
        raise SupertagWriteError(
            "base_tag", "The base tag is implicit and cannot be applied.", 400, affected=(supertag_id,)
        )
    if tag.errors:
        code = (
            "field_conflict" if any(error.startswith("field_conflict:") for error in tag.errors) else "invalid_supertag"
        )
        raise SupertagWriteError(
            code,
            f"#{supertag_id} is invalid: {'; '.join(tag.errors)}",
            422,
            affected=(supertag_id,),
        )
    if tag.entity_type != entity.entity_type.value:
        raise SupertagWriteError(
            "base_mismatch",
            f"#{supertag_id} is for {tag.base}, not {entity.entity_type.value}.",
            422,
            affected=(supertag_id,),
        )
    return tag


def _target_tag_for_removal(view: SupertagView, supertag_id: str) -> Supertag:
    tag = view.registry.get(supertag_id)
    if tag is None:
        raise SupertagWriteError(
            "unknown_supertag", f"No supertag with id: {supertag_id}", 404, affected=(supertag_id,)
        )
    if tag.builtin:
        raise SupertagWriteError(
            "base_tag", "The base tag is implicit and cannot be removed.", 400, affected=(supertag_id,)
        )
    return tag


def _defaults(tag: Supertag, entity: EntityBase) -> dict[str, object]:
    return {
        field.key: field.default for field in tag.fields if field.default is not None and field.key not in entity.raw
    }


def _read_note(vault_root: Path, relative: str, expected: str | None) -> tuple[str, str]:
    try:
        target = ensure_under(vault_root, vault_root / relative)
    except PathSafetyError as exc:
        raise SupertagWriteError("invalid_target", str(exc), 422, affected=(relative,)) from exc
    if not target.is_file():
        raise SupertagWriteError("missing_target", f"Note not found: {relative}", 404, affected=(relative,))
    current_sha = sha256_file(target)
    expected = str(expected or "").strip() or None
    if expected is not None and expected != current_sha:
        raise SupertagWriteError("stale_hash", f"Note changed since it was read: {relative}", 409, affected=(relative,))
    return target.read_bytes().decode("utf-8-sig"), current_sha


def _commit(
    vault_root: Path,
    runtime: str | Path,
    *,
    verb: str,
    relative: str,
    content: str,
    expected: str,
    reviewer: str,
    reason: str,
    confirmed: bool,
) -> CommitResult:
    if not confirmed:
        raise SupertagWriteError(
            "needs_confirmation",
            f"'{verb}' requires explicit confirmation.",
            409,
            affected=(relative,),
        )
    changeset = ChangeSet(
        verb,
        (FileOp("update", Path(relative), "trusted", content=content, expected=expected),),
        reviewer=reviewer,
        reason=reason,
    )
    try:
        return commit(changeset, write_zones(vault_root, runtime), confirmed=True)
    except MutationError as exc:
        status = 409 if exc.code in {"stale_hash", "stale_source"} else 500
        raise SupertagWriteError(exc.code, str(exc), status, affected=exc.affected) from exc


def _custom_tags(entity: EntityBase, tags: list[str]) -> tuple[str, ...]:
    base_id = _ENTITY_BASE.get(entity.entity_type.value)
    return tuple(tag_id for tag_id in tags if tag_id != base_id)


def _noop(entity: EntityBase, current: list[str]) -> SupertagWriteResult:
    return SupertagWriteResult(
        path=entity.path,
        committed=False,
        sha=None,
        journal=None,
        changes=(),
        tags=_custom_tags(entity, current),
    )
