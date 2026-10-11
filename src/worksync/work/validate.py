"""Deterministic validation for work entities, with error and warning tiers.

Errors: missing required field, enum violation, conditional-rule violation, and a
review date out of order. Warnings: unresolved wikilink, ``source_system`` without
``sync_mode``, and malformed frontmatter. A note with errors is excluded from views
but still listed in the health report; validation never raises on a bad note.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from worksync.work.dates import parse_iso_date
from worksync.work.models import (
    ENUM_FIELDS,
    LINK_FIELDS_BY_TYPE,
    STATUS_ENUM_BY_TYPE,
    EntityBase,
    EntityType,
)
from worksync.work.schema import DATE_STATUS_UNDATED, is_valid_person_id, link_targets

REQUIRED_BY_TYPE: dict[str, tuple[str, ...]] = {
    EntityType.PROJECT.value: ("owners",),
    EntityType.MEETING.value: ("date",),
}
EXTERNAL_SYNC_MODES = {"reference", "snapshot"}
REQUIRED_FIELD_LABELS = {"owners": "at least one owner", "date": "date"}


@dataclass(frozen=True)
class ValidationIssue:
    """One validation finding for a work note."""

    path: str
    message: str
    severity: str = "error"
    rule: str = ""


def validate_entity(entity: EntityBase) -> list[ValidationIssue]:
    """Validate one entity's fields, returning error- and warning-tier issues."""
    issues: list[ValidationIssue] = []
    entity_type = entity.entity_type.value

    if not entity.status:
        issues.append(_issue(entity, "Missing required field: status", rule="required"))
    elif entity.status not in {member.value for member in STATUS_ENUM_BY_TYPE[entity_type]}:
        issues.append(_issue(entity, f"Invalid status '{entity.status}' for {entity_type}", rule="enum"))

    for field_name, enum in ENUM_FIELDS.items():
        value = _field_value(entity, field_name)
        if value is None:
            continue
        if str(value) not in {member.value for member in enum}:
            issues.append(_issue(entity, f"Invalid {field_name} '{value}'", rule="enum"))

    issues.extend(_validate_required(entity))
    issues.extend(_validate_conditionals(entity))
    issues.extend(_validate_date_order(entity))
    if entity_type == EntityType.PERSON.value:
        issues.extend(_validate_person_id(entity))
    return issues


def validate_relationships(entity: EntityBase, known_targets: set[str]) -> list[ValidationIssue]:
    """Warn about wikilink targets that do not resolve to a known entity."""
    issues: list[ValidationIssue] = []
    entity_type = entity.entity_type.value
    for field_name in LINK_FIELDS_BY_TYPE.get(entity_type, ()):
        value = getattr(entity, field_name, None)
        if field_name == "related_ticket" and isinstance(value, str) and "[[" not in value:
            # related_ticket may legitimately be a bare external id, not a wikilink.
            continue
        for target in link_targets(entity, field_name):
            if target and target not in known_targets:
                issues.append(
                    _issue(
                        entity,
                        f"Unresolved link in {field_name}: {target}",
                        severity="warning",
                        rule="unresolved_link",
                    )
                )
    return issues


def validate_all(entities: Iterable[EntityBase], known_targets: set[str]) -> list[ValidationIssue]:
    """Validate every entity and return issues in stable order."""
    ordered = list(entities)
    issues: list[ValidationIssue] = []
    for entity in ordered:
        issues.extend(validate_entity(entity))
        issues.extend(validate_relationships(entity, known_targets))
    issues.extend(_duplicate_person_id_issues(ordered))
    issues.sort(key=_issue_sort)
    return issues


def has_errors(issues: Iterable[ValidationIssue]) -> bool:
    """Return True when any issue has error severity."""
    return any(issue.severity == "error" for issue in issues)


def _issue_sort(issue: ValidationIssue) -> tuple[str, str, str]:
    return (issue.path, issue.severity, issue.message)


def _validate_required(entity: EntityBase) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field_name in REQUIRED_BY_TYPE.get(entity.entity_type.value, ()):
        if not getattr(entity, field_name, None):
            label = REQUIRED_FIELD_LABELS.get(field_name, field_name)
            issues.append(_issue(entity, f"Missing required field: {label}", rule="required"))
    return issues


def _validate_conditionals(entity: EntityBase) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    entity_type = entity.entity_type.value

    if entity_type == EntityType.TICKET.value:
        sync_mode = getattr(entity, "sync_mode", None)
        if sync_mode in EXTERNAL_SYNC_MODES:
            for field_name in ("source_system", "external_id"):
                if not getattr(entity, field_name, None):
                    issues.append(
                        _issue(
                            entity,
                            f"sync_mode '{sync_mode}' requires field: {field_name}",
                            rule="conditional",
                        )
                    )

    if entity_type == EntityType.ACTION.value:
        if entity.status == "waiting" and not getattr(entity, "waiting_on", None):
            issues.append(_issue(entity, "status 'waiting' requires field: waiting_on", rule="conditional"))
        if entity.status == "done" and not getattr(entity, "completed", None):
            issues.append(_issue(entity, "status 'done' requires field: completed", rule="conditional"))

    if entity_type == EntityType.MEETING.value:
        date_status = str(entity.raw.get("date_status") or "").strip().casefold()
        if date_status == DATE_STATUS_UNDATED:
            issues.append(
                _issue(entity, "date is a placeholder (undated); set a real date", severity="warning", rule="undated")
            )

    source_system = getattr(entity, "source_system", None)
    if source_system and not getattr(entity, "sync_mode", None):
        issues.append(_issue(entity, "source_system present without sync_mode", severity="warning", rule="conditional"))

    return issues


def _validate_date_order(entity: EntityBase) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if entity.entity_type is not EntityType.PROJECT:
        return issues

    last_reviewed = getattr(entity, "last_reviewed", None)
    next_review = getattr(entity, "next_review", None)
    if not last_reviewed or not next_review:
        return issues

    parsed_last = parse_iso_date(last_reviewed)
    parsed_next = parse_iso_date(next_review)
    if parsed_last is None or parsed_next is None:
        issues.append(_issue(entity, "Unparseable review date", severity="warning", rule="date_order"))
        return issues
    if parsed_next < parsed_last:
        issues.append(_issue(entity, "next_review is before last_reviewed", rule="date_order"))
    return issues


def _field_value(entity: EntityBase, field_name: str) -> object | None:
    """Return a modeled attribute when present, else fall back to raw frontmatter."""
    value = getattr(entity, field_name, None)
    if value is not None:
        return value
    return entity.raw.get(field_name)


def _validate_person_id(entity: EntityBase) -> list[ValidationIssue]:
    person_id = getattr(entity, "person_id", None)
    if person_id and not is_valid_person_id(person_id):
        return [_issue(entity, f"Invalid person_id '{person_id}'", rule="person_id")]
    return []


def _duplicate_person_id_issues(entities: Iterable[EntityBase]) -> list[ValidationIssue]:
    """Flag every active person that shares a person_id, so none is trusted (fail closed)."""
    by_id: dict[str, list[EntityBase]] = {}
    for entity in entities:
        if entity.entity_type is not EntityType.PERSON:
            continue
        person_id = getattr(entity, "person_id", None)
        if person_id:
            by_id.setdefault(person_id, []).append(entity)
    issues: list[ValidationIssue] = []
    for person_id, group in by_id.items():
        if len(group) > 1:
            issues.extend(_issue(entity, f"Duplicate person_id: {person_id}", rule="person_id") for entity in group)
    return issues


def _issue(entity: EntityBase, message: str, severity: str = "error", rule: str = "") -> ValidationIssue:
    return ValidationIssue(path=entity.path, message=message, severity=severity, rule=rule)
