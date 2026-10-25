"""Read-only supertag instances: applied tags, field values, defaults, and references.

Validation is additive: a bad tag or field never breaks the work index or the Command Center.
The registry supplies definitions; the live/full index supplies references. Nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from worksync.work.models import EntityBase, entity_id_of
from worksync.work.repository import WorkIndex
from worksync.work.supertags import BASE_ENTITY_TYPES, Supertag, SupertagField, SupertagRegistry

ENTITY_BASE: dict[str, str] = {value: key for key, value in BASE_ENTITY_TYPES.items()}
_ENTITY_TYPES = tuple(BASE_ENTITY_TYPES.values())


@dataclass(frozen=True)
class FieldValue:
    """One field's stored and effective values with errors/warnings."""

    field: SupertagField
    value: Any
    effective: Any
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagInstance:
    """One tag applied to one entity, with its field values."""

    tag: Supertag
    fields: tuple[FieldValue, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def field(self, key: str) -> FieldValue | None:
        """Return the field value for *key*, or ``None``."""
        return next((field for field in self.fields if field.field.key == key), None)

    @property
    def all_errors(self) -> tuple[str, ...]:
        """Return tag-level plus field-level errors."""
        return (
            *self.errors,
            *(f"{self.tag.id}: {error}" for field in self.fields for error in field.errors),
        )

    @property
    def all_warnings(self) -> tuple[str, ...]:
        """Return tag-level plus field-level warnings."""
        return (
            *self.warnings,
            *(f"{self.tag.id}: {warning}" for field in self.fields for warning in field.warnings),
        )


@dataclass(frozen=True)
class InstanceValidation:
    """The validated supertags and fields for one entity."""

    entity_id: str
    path: str
    title: str
    base: Supertag | None
    tag_ids: tuple[str, ...]
    tags: tuple[Supertag, ...]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    instances: tuple[TagInstance, ...] = ()

    def tag_instance(self, tag_id: str) -> TagInstance | None:
        """Return the instance for *tag_id*, or ``None``."""
        return next((instance for instance in self.instances if instance.tag.id == tag_id), None)

    @property
    def all_errors(self) -> tuple[str, ...]:
        """Return instance-level plus every tag/field error."""
        return (*self.errors, *(error for instance in self.instances for error in instance.all_errors))

    @property
    def all_warnings(self) -> tuple[str, ...]:
        """Return instance-level plus every tag/field warning."""
        return (*self.warnings, *(warning for instance in self.instances for warning in instance.all_warnings))


def validate_instance(registry: SupertagRegistry, entity: EntityBase, index: WorkIndex) -> InstanceValidation:
    """Validate one entity's applied tags, fields, defaults, and references."""
    base_id = ENTITY_BASE.get(entity.entity_type.value)
    base = registry.get(base_id) if base_id is not None else None
    errors: list[str] = []
    warnings: list[str] = []

    raw = entity.raw.get("supertags")
    if raw is not None and not isinstance(raw, (str, list, tuple)):
        errors.append("supertags must be a list of ids")
    elif isinstance(raw, (list, tuple)) and any(not isinstance(item, str) for item in raw):
        errors.append("supertags must contain only ids")

    applied: list[str] = []
    for tag_id in entity.supertags:
        if tag_id == base_id or tag_id in applied:
            continue
        applied.append(tag_id)

    tags: list[Supertag] = []
    for tag_id in applied:
        tag = registry.get(tag_id)
        if tag is None:
            errors.append(f"unknown supertag: {tag_id}")
            continue
        if tag.errors:
            errors.append(f"definition #{tag_id} is invalid")
            continue
        if tag.entity_type != entity.entity_type.value:
            errors.append(f"#{tag_id} has base {tag.base}, not {entity.entity_type.value}")
            continue
        tags.append(tag)

    instances: list[TagInstance] = []
    if base is not None:
        instances.append(tag_instance(base, entity, index))
    for tag in tags:
        instances.append(tag_instance(tag, entity, index))

    return InstanceValidation(
        entity_id=entity_id_of(entity),
        path=entity.path,
        title=entity.title,
        base=base,
        tag_ids=tuple(applied),
        tags=tuple(tags),
        errors=tuple(errors),
        warnings=tuple(warnings),
        instances=tuple(instances),
    )


def tag_instance(tag: Supertag, entity: EntityBase, index: WorkIndex) -> TagInstance:
    """Validate *tag*'s fields against *entity*, returning stored/effective values."""
    if tag.errors:
        return TagInstance(tag=tag, errors=tag.errors)
    if tag.entity_type != entity.entity_type.value:
        return TagInstance(tag=tag, errors=(f"#{tag.id} has base {tag.base}, not {entity.entity_type.value}",))
    fields = tuple(_field_value(field, entity, index) for field in tag.fields)
    return TagInstance(tag=tag, fields=fields)


def _field_value(field: SupertagField, entity: EntityBase, index: WorkIndex) -> FieldValue:
    value = entity.raw.get(field.key)
    if field.type == "date" and isinstance(value, date):
        value = value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    present = value is not None
    effective = value if present else field.default
    errors: list[str] = []
    warnings: list[str] = []
    if not present and effective is None and field.required:
        errors.append(f"missing required field: {field.key}")
    elif present:
        errors, warnings = _validate_value(field, value, index)
    return FieldValue(
        field=field,
        value=value,
        effective=effective,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _validate_value(field: SupertagField, value: Any, index: WorkIndex) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    type_ = field.type
    if type_ == "text":
        if not isinstance(value, str):
            errors.append(f"{field.key} must be text")
    elif type_ == "number":
        if not _is_number(value):
            errors.append(f"{field.key} must be a number")
    elif type_ == "date":
        if not isinstance(value, str):
            errors.append(f"{field.key} must be an ISO date")
        else:
            try:
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"{field.key} must be an ISO date")
    elif type_ == "select":
        if not isinstance(value, str) or value not in field.options:
            errors.append(f"{field.key} must be one of {', '.join(field.options)}")
    elif type_ == "checkbox":
        if not isinstance(value, bool):
            errors.append(f"{field.key} must be a boolean")
    elif type_ == "reference":
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field.key} must be a reference")
        else:
            ref_errors, ref_warnings = _reference(field, value, index)
            errors.extend(ref_errors)
            warnings.extend(ref_warnings)
    elif type_ == "multi_reference":
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"{field.key} must be a list of references")
        else:
            for item in value:
                ref_errors, ref_warnings = _reference(field, item, index)
                errors.extend(ref_errors)
                warnings.extend(ref_warnings)
    elif type_ == "multi_text" and (not isinstance(value, list) or not all(isinstance(item, str) for item in value)):
        errors.append(f"{field.key} must be a list of text values")
    return errors, warnings


def _reference(field: SupertagField, value: str, index: WorkIndex) -> tuple[list[str], list[str]]:
    target = BASE_ENTITY_TYPES.get(field.target or "")
    if target is None:
        return [f"{field.key}: definition has no valid reference target"], []
    if index.get(target, value) is not None:
        return [], []
    other = next(
        (entity for entity_type in _ENTITY_TYPES if (entity := index.get(entity_type, value)) is not None),
        None,
    )
    if other is None:
        return [], [f"{field.key}: unresolved reference {value!r}"]
    return [f"{field.key}: expected {field.target}, found {other.entity_type.value}"], []


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
