"""Read-only supertag registry: definitions, inheritance, validation, and counts.

A supertag is a vault note with ``type: supertag``. The five built-in base tags mirror the work
entity types; custom tags add typed fields and may extend one parent. Supertags enrich an
entity without changing its canonical type. This module reads definitions and counts live
instances; it writes nothing.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from worksync.inventory.parse import IndexRecord, scan_vault
from worksync.work.generation import WorkGeneration, live_index_from, read_generation
from worksync.work.models import EntityBase
from worksync.work.repository import WorkIndex

BASE_ENTITY_TYPES: dict[str, str] = {
    "task": "action",
    "ticket": "ticket",
    "project": "project",
    "meeting": "meeting",
    "person": "person",
}
BUILTIN_IDS: tuple[str, ...] = tuple(BASE_ENTITY_TYPES)
COLORS: tuple[str, ...] = (
    "gray",
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "purple",
    "pink",
    "brown",
    "cyan",
    "teal",
    "indigo",
)
FIELD_TYPES: tuple[str, ...] = (
    "text",
    "number",
    "date",
    "select",
    "checkbox",
    "reference",
    "multi_reference",
    "multi_text",
)
REFERENCE_TARGETS: tuple[str, ...] = ("person", "project", "meeting", "task", "ticket")
RESERVED_KEYS = frozenset({"type", "supertags", "tags"})

_ACTION_STATUSES = ("open", "in_progress", "waiting", "watch", "parked", "done", "cancelled")
_TICKET_STATUSES = ("open", "in_progress", "waiting", "blocked", "escalated", "resolved", "closed")
_PROJECT_STATUSES = ("active", "paused", "blocked", "done", "archived")
_MEETING_STATUSES = ("scheduled", "held", "cancelled")
_PERSON_STATUSES = ("active", "inactive")
_PRIORITIES = ("P1", "P2", "P3", "P4")
_HEALTH = ("green", "yellow", "red")

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class SupertagField:
    """One typed field in a supertag definition."""

    name: str
    key: str
    type: str
    default: Any = None
    required: bool = False
    optional: bool = False
    options: tuple[str, ...] = ()
    target: str | None = None
    inherited: bool = False
    source: str = ""


@dataclass(frozen=True)
class Supertag:
    """One resolved supertag definition plus its live/legacy counts."""

    id: str
    name: str
    base: str
    entity_type: str
    color: str
    builtin: bool
    extends: str | None
    fields: tuple[SupertagField, ...]
    errors: tuple[str, ...] = ()
    instance_count: int = 0
    legacy_count: int = 0

    def field(self, key: str) -> SupertagField | None:
        """Return the field with *key*, or ``None``."""
        return next((field for field in self.fields if field.key == key), None)


@dataclass(frozen=True)
class SupertagRegistry:
    """All definitions, built-ins first, with counts and errors."""

    supertags: tuple[Supertag, ...]

    def get(self, supertag_id: str) -> Supertag | None:
        """Return one definition by id, or ``None``."""
        return next((tag for tag in self.supertags if tag.id == supertag_id), None)

    def selectable(self, entity_type: str) -> tuple[Supertag, ...]:
        """Return custom tags that can be applied to *entity_type*."""
        return tuple(
            tag for tag in self.supertags if not tag.builtin and not tag.errors and tag.entity_type == entity_type
        )


@dataclass(frozen=True)
class _RawField:
    field: SupertagField
    default_set: bool = False
    required_set: bool = False
    optional_set: bool = False


@dataclass(frozen=True)
class _RawDefinition:
    path: str
    id: str
    name: str
    base: str
    entity_type: str
    color: str
    extends: str | None
    fields: tuple[_RawField, ...]
    errors: tuple[str, ...] = ()


def _builtin_field(
    name: str,
    key: str,
    type_: str,
    *,
    required: bool = False,
    options: tuple[str, ...] = (),
    target: str | None = None,
) -> SupertagField:
    return SupertagField(name=name, key=key, type=type_, required=required, options=options, target=target)


def builtin_supertags() -> tuple[Supertag, ...]:
    """Return the five built-in base tags, synthesized from the work schema."""
    tags = (
        Supertag(
            id="task",
            name="Task",
            base="task",
            entity_type="action",
            color="blue",
            builtin=True,
            extends=None,
            fields=(
                _builtin_field("Status", "status", "select", required=True, options=_ACTION_STATUSES),
                _builtin_field("Priority", "priority", "select", options=_PRIORITIES),
                _builtin_field("Due", "due", "date"),
                _builtin_field("Project", "project", "reference", target="project"),
                _builtin_field("Owners", "owners", "multi_reference", target="person"),
            ),
        ),
        Supertag(
            id="ticket",
            name="Ticket",
            base="ticket",
            entity_type="ticket",
            color="purple",
            builtin=True,
            extends=None,
            fields=(
                _builtin_field("Status", "status", "select", required=True, options=_TICKET_STATUSES),
                _builtin_field("Priority", "priority", "select", options=_PRIORITIES),
                _builtin_field("Assignee", "assignee", "reference", target="person"),
                _builtin_field("Project", "project", "reference", target="project"),
                _builtin_field("Next action", "next_action", "text"),
                _builtin_field("Manager attention", "manager_attention", "checkbox"),
                _builtin_field("Last checked", "last_checked", "date"),
            ),
        ),
        Supertag(
            id="project",
            name="Project",
            base="project",
            entity_type="project",
            color="green",
            builtin=True,
            extends=None,
            fields=(
                _builtin_field("Status", "status", "select", required=True, options=_PROJECT_STATUSES),
                _builtin_field("Owners", "owners", "multi_reference", required=True, target="person"),
                _builtin_field("Priority", "priority", "select", options=_PRIORITIES),
                _builtin_field("Health", "health", "select", options=_HEALTH),
                _builtin_field("Next action", "next_action", "text"),
                _builtin_field("Last reviewed", "last_reviewed", "date"),
                _builtin_field("Next review", "next_review", "date"),
            ),
        ),
        Supertag(
            id="meeting",
            name="Meeting",
            base="meeting",
            entity_type="meeting",
            color="orange",
            builtin=True,
            extends=None,
            fields=(
                _builtin_field("Status", "status", "select", required=True, options=_MEETING_STATUSES),
                _builtin_field("Date", "date", "date", required=True),
                _builtin_field("Attendees", "attendees", "multi_reference", target="person"),
                _builtin_field("Projects", "projects", "multi_reference", target="project"),
                _builtin_field("Meeting type", "meeting_type", "text"),
            ),
        ),
        Supertag(
            id="person",
            name="Person",
            base="person",
            entity_type="person",
            color="teal",
            builtin=True,
            extends=None,
            fields=(
                _builtin_field("Status", "status", "select", required=True, options=_PERSON_STATUSES),
                _builtin_field("Role", "role", "text"),
                _builtin_field("Team", "team", "text"),
                _builtin_field("Manager", "manager", "reference", target="person"),
                _builtin_field("Email", "email", "text"),
                _builtin_field("Aliases", "aliases", "multi_text"),
            ),
        ),
    )
    return tuple(
        replace(
            tag,
            fields=tuple(replace(field, source=tag.id, inherited=False) for field in tag.fields),
        )
        for tag in tags
    )


def build_registry(
    records: Iterable[IndexRecord],
    root: str | Path,
    generation: WorkGeneration,
) -> SupertagRegistry:
    """Build the registry from an inventory scan, live-view counts, and generation state."""
    ordered = tuple(records)
    full = WorkIndex.from_records(ordered, root=root)
    live = live_index_from(full, generation, root)
    builtins = builtin_supertags()
    raws = _parse_definitions(ordered)
    tags = _resolve_definitions(builtins, raws)
    tags = _apply_field_conflicts(tags)
    tags = _with_counts(tags, full, live)
    return SupertagRegistry(tuple(tags))


def supertag_registry(vault: str | Path, runtime: str | Path) -> SupertagRegistry:
    """Scan *vault* and build the registry for the current generation."""
    root = Path(vault).expanduser().resolve()
    return build_registry(scan_vault(root), root, read_generation(runtime))


def _path_hash(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]


def _declared_type(record: IndexRecord) -> str:
    return str(record.frontmatter.get("type") or "").strip().strip("\"'").casefold()


def _parse_definitions(records: Iterable[IndexRecord]) -> tuple[_RawDefinition, ...]:
    definitions = sorted((record for record in records if _declared_type(record) == "supertag"), key=lambda r: r.path)
    return tuple(_parse_definition(record) for record in definitions)


def _parse_definition(record: IndexRecord) -> _RawDefinition:
    frontmatter = record.frontmatter
    errors: list[str] = []
    declared_id = str(frontmatter.get("supertag_id") or "").strip()
    if not declared_id:
        errors.append("missing supertag_id")
        tag_id = f"invalid-{_path_hash(record.path)}"
    elif not _ID_RE.fullmatch(declared_id):
        errors.append(f"invalid supertag_id: {declared_id!r}")
        tag_id = f"invalid-{_path_hash(record.path)}"
    else:
        tag_id = declared_id

    name = str(frontmatter.get("name") or record.title or Path(record.path).stem).strip()
    base = str(frontmatter.get("base") or "").strip().casefold()
    if base in BASE_ENTITY_TYPES:
        entity_type = BASE_ENTITY_TYPES[base]
    else:
        errors.append(f"invalid base: {base or '(missing)'}")
        entity_type = ""

    extends_value = frontmatter.get("extends")
    if extends_value is None or extends_value == "":
        extends = None
    elif isinstance(extends_value, str):
        extends = extends_value.strip() or None
    else:
        errors.append("extends must be a supertag id")
        extends = None

    color = str(frontmatter.get("color") or "gray").strip().casefold()
    if color not in COLORS:
        errors.append(f"invalid color: {color!r}")
        color = "gray"

    raw_fields = frontmatter.get("fields")
    if raw_fields is None:
        raw_fields = []
    if not isinstance(raw_fields, list):
        errors.append("fields must be a list")
        raw_fields = []
    fields: list[_RawField] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_fields):
        parsed = _parse_field(item, index, tag_id, errors)
        if parsed is None:
            continue
        if parsed.field.key in seen:
            errors.append(f"duplicate field key: {parsed.field.key}")
            continue
        seen.add(parsed.field.key)
        fields.append(parsed)

    return _RawDefinition(
        path=record.path,
        id=tag_id,
        name=name,
        base=base,
        entity_type=entity_type,
        color=color,
        extends=extends,
        fields=tuple(fields),
        errors=tuple(errors),
    )


def _parse_field(
    item: object,
    index: int,
    def_id: str,
    errors: list[str],
) -> _RawField | None:
    label = f"field {index + 1}"
    if not isinstance(item, dict):
        errors.append(f"{label}: must be a mapping")
        return None
    name = str(item.get("name") or "").strip()
    if not name:
        errors.append(f"{label}: missing name")
        return None
    key = str(item.get("key") or _slug(name)).strip()
    if not _KEY_RE.fullmatch(key):
        errors.append(f"{label} ({name}): invalid key {key!r}")
        return None
    if key in RESERVED_KEYS:
        errors.append(f"{label} ({name}): reserved key {key!r}")
        return None
    type_ = str(item.get("type") or "").strip().casefold()
    if type_ not in FIELD_TYPES:
        errors.append(f"{label} ({name}): invalid type {type_ or '(missing)'}")
        return None

    required = item.get("required", False)
    optional = item.get("optional", False)
    if not isinstance(required, bool) or not isinstance(optional, bool):
        errors.append(f"{label} ({name}): required/optional must be booleans")
        return None
    if required and optional:
        errors.append(f"{label} ({name}): required and optional cannot both be true")
        return None

    options_raw = item.get("options")
    options: tuple[str, ...] = ()
    if type_ == "select":
        if (
            not isinstance(options_raw, list)
            or not options_raw
            or not all(isinstance(option, str) and option for option in options_raw)
        ):
            errors.append(f"{label} ({name}): select needs non-empty string options")
            return None
        if len(set(options_raw)) != len(options_raw):
            errors.append(f"{label} ({name}): duplicate options")
            return None
        options = tuple(options_raw)
    elif options_raw not in (None, []):
        errors.append(f"{label} ({name}): options only apply to select")
        return None

    target_raw = item.get("target")
    target = str(target_raw).strip() if isinstance(target_raw, str) and target_raw.strip() else None
    if type_ in ("reference", "multi_reference"):
        if target not in REFERENCE_TARGETS:
            errors.append(f"{label} ({name}): invalid reference target {target!r}")
            return None
    elif target is not None:
        errors.append(f"{label} ({name}): target only applies to references")
        return None

    default_set = "default" in item
    default = item.get("default")
    if default_set:
        problem = _default_problem(default, type_, options)
        if problem is not None:
            errors.append(f"{label} ({name}): {problem}")
            default = None

    field = SupertagField(
        name=name,
        key=key,
        type=type_,
        default=default if default_set else None,
        required=required,
        optional=optional,
        options=options,
        target=target,
        inherited=False,
        source=def_id,
    )
    return _RawField(
        field=field,
        default_set=default_set,
        required_set="required" in item,
        optional_set="optional" in item,
    )


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.casefold())
    return re.sub(r"_+", "_", cleaned).strip("_")


def _default_problem(value: object, type_: str, options: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    if type_ == "text":
        return None if isinstance(value, str) else "default must be text"
    if type_ == "number":
        return None if isinstance(value, (int, float)) and not isinstance(value, bool) else "default must be a number"
    if type_ == "checkbox":
        return None if isinstance(value, bool) else "default must be a boolean"
    if type_ == "select":
        return None if isinstance(value, str) and value in options else "default must be one of the options"
    if type_ == "date":
        if not isinstance(value, str):
            return "default must be a date"
        try:
            date.fromisoformat(value)
        except ValueError:
            return "default must be an ISO date"
        return None
    if type_ == "reference":
        return None if isinstance(value, str) and value.strip() else "default must be a reference string"
    if type_ in ("multi_reference", "multi_text"):
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            return "default must be a non-empty list of strings"
        return None
    return None


def _resolve_definitions(
    builtins: tuple[Supertag, ...],
    raws: tuple[_RawDefinition, ...],
) -> tuple[Supertag, ...]:
    builtin_by_id = {tag.id: tag for tag in builtins}
    raw_by_id: dict[str, _RawDefinition] = {}
    for raw in raws:
        if raw.id in builtin_by_id or raw.id in raw_by_id:
            original = builtin_by_id.get(raw.id) or raw_by_id.get(raw.id)
            source = "the built-in tag" if isinstance(original, Supertag) else original.path
            synthetic = f"{raw.id}-dup-{_path_hash(raw.path)}"
            raw = replace(
                raw,
                id=synthetic,
                errors=(*raw.errors, f"duplicate supertag_id: {raw.id} (also {source})"),
            )
            raw_by_id[synthetic] = raw
        else:
            raw_by_id[raw.id] = raw

    cycle_ids, cycle_errors = _find_cycles(raw_by_id, builtin_by_id)

    def parent_id(raw: _RawDefinition) -> str | None:
        if raw.id in cycle_ids:
            return None
        if raw.extends:
            return raw.extends
        return raw.base if raw.base in BASE_ENTITY_TYPES else None

    resolved: dict[str, Supertag] = dict(builtin_by_id)

    def resolve(raw_id: str) -> Supertag | None:
        if raw_id in resolved:
            return resolved[raw_id]
        raw = raw_by_id.get(raw_id)
        if raw is None:
            return None
        parent_ref = parent_id(raw)
        errors = list(raw.errors) + list(cycle_errors.get(raw.id, ()))
        parent: Supertag | None = None
        if parent_ref is not None:
            parent = resolve(parent_ref)
            if parent is None:
                errors.append(f"unknown extends: {parent_ref}")
            elif parent.entity_type and raw.entity_type and parent.entity_type != raw.entity_type:
                errors.append(f"extends base mismatch: {parent_ref} is {parent.base}, this tag is {raw.base}")
                parent = None
            elif parent.errors:
                errors.append(f"parent supertag is invalid: {parent_ref}")
        fields = _merge_fields(parent.fields if parent is not None else (), raw.fields, raw.id, errors)
        tag = Supertag(
            id=raw.id,
            name=raw.name,
            base=raw.base,
            entity_type=raw.entity_type,
            color=raw.color,
            builtin=False,
            extends=raw.extends,
            fields=fields,
            errors=tuple(errors),
        )
        resolved[raw.id] = tag
        return tag

    for raw in raw_by_id.values():
        resolve(raw.id)

    ordered = [builtin_by_id[tag_id] for tag_id in BUILTIN_IDS]
    custom = sorted(
        (tag for tag_id, tag in resolved.items() if tag_id not in builtin_by_id),
        key=lambda tag: (tag.name.casefold(), tag.id),
    )
    return tuple([*ordered, *custom])


def _find_cycles(
    raw_by_id: dict[str, _RawDefinition],
    builtin_by_id: dict[str, Supertag],
) -> tuple[set[str], dict[str, tuple[str, ...]]]:
    cycle_ids: set[str] = set()
    cycle_errors: dict[str, list[str]] = {}
    for raw in raw_by_id.values():
        path: list[str] = []
        seen: dict[str, int] = {}
        current: str | None = raw.id
        while current is not None:
            if current in seen:
                cycle = [*path[seen[current] :], current]
                message = "cycle: " + " -> ".join(cycle)
                for tag_id in set(cycle):
                    cycle_ids.add(tag_id)
                    cycle_errors.setdefault(tag_id, []).append(message)
                break
            seen[current] = len(path)
            path.append(current)
            node = raw_by_id.get(current)
            if node is None:
                break
            if current in cycle_ids:
                break
            if node.extends:
                current = node.extends
            elif node.base in builtin_by_id:
                current = node.base
            else:
                current = None
    return cycle_ids, {tag_id: tuple(messages) for tag_id, messages in cycle_errors.items()}


def _merge_fields(
    parent_fields: tuple[SupertagField, ...],
    raw_fields: tuple[_RawField, ...],
    child_id: str,
    errors: list[str],
) -> tuple[SupertagField, ...]:
    order: list[str] = [field.key for field in parent_fields]
    merged: dict[str, SupertagField] = {field.key: replace(field, inherited=True) for field in parent_fields}
    for raw_field in raw_fields:
        field = raw_field.field
        parent = merged.get(field.key)
        if parent is None:
            merged[field.key] = field
            order.append(field.key)
            continue
        if (field.name, field.type, field.options) != (parent.name, parent.type, parent.options):
            errors.append(f"field {field.key}: a child cannot change name/type/options")
            continue
        updated = replace(
            parent,
            default=field.default if raw_field.default_set else parent.default,
            required=field.required if raw_field.required_set else parent.required,
            optional=field.optional if raw_field.optional_set else parent.optional,
        )
        if updated.required and updated.optional:
            errors.append(f"field {field.key}: required and optional cannot both be true")
            continue
        merged[field.key] = updated
    return tuple(merged[key] for key in order)


def _apply_field_conflicts(tags: tuple[Supertag, ...]) -> tuple[Supertag, ...]:
    by_base: dict[str, list[Supertag]] = {}
    for tag in tags:
        if not tag.builtin and tag.entity_type:
            by_base.setdefault(tag.entity_type, []).append(tag)
    extra: dict[str, list[str]] = {}
    for group in by_base.values():
        owners: dict[str, tuple[SupertagField, Supertag]] = {}
        for tag in group:
            for field in tag.fields:
                if field.inherited:
                    continue
                existing = owners.get(field.key)
                if existing is None:
                    owners[field.key] = (field, tag)
                    continue
                other_field, other_tag = existing
                if (field.name, field.type, field.options) != (
                    other_field.name,
                    other_field.type,
                    other_field.options,
                ):
                    extra.setdefault(tag.id, []).append(f"field_conflict: {field.key} with #{other_tag.id}")
                    extra.setdefault(other_tag.id, []).append(f"field_conflict: {field.key} with #{tag.id}")
    return tuple(replace(tag, errors=(*tag.errors, *extra.get(tag.id, ()))) if tag.id in extra else tag for tag in tags)


def _with_counts(
    tags: tuple[Supertag, ...],
    full: WorkIndex,
    live: WorkIndex,
) -> tuple[Supertag, ...]:
    counted: list[Supertag] = []
    for tag in tags:
        if tag.errors or not tag.entity_type:
            counted.append(replace(tag, instance_count=0, legacy_count=0))
            continue
        if tag.builtin:
            live_count = len(live.list_type(tag.entity_type))
            full_count = len(full.list_type(tag.entity_type))
        else:
            live_count = sum(1 for entity in live.list_type(tag.entity_type) if _has_tag(entity, tag.id))
            full_count = sum(1 for entity in full.list_type(tag.entity_type) if _has_tag(entity, tag.id))
        counted.append(replace(tag, instance_count=live_count, legacy_count=max(0, full_count - live_count)))
    return tuple(counted)


def _has_tag(entity: EntityBase, tag_id: str) -> bool:
    values = entity.raw.get("supertags")
    if isinstance(values, str):
        return values.strip() == tag_id
    if isinstance(values, list):
        return tag_id in [str(value) for value in values]
    return False
