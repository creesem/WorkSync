"""Read-only work index over a vault.

Builds typed entities from the shared inventory scanner, validates them, and
exposes deterministic list/lookup/health views. Never writes to the vault.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from worksync.inventory.parse import scan_vault
from worksync.inventory.validate import structural_issues
from worksync.work.models import EntityBase
from worksync.work.schema import OPERATOR_TYPE_VALUES, entity_from_record, link_target, normalize_target
from worksync.work.validate import ValidationIssue, has_errors, validate_all


@dataclass
class WorkIndex:
    """A read-only view of all work entities in a vault."""

    root: Path
    entities: tuple[EntityBase, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    _by_type: dict[str, tuple[EntityBase, ...]] = field(default_factory=dict)
    _lookup: dict[str, EntityBase] = field(default_factory=dict)
    _duplicate_keys: tuple[str, ...] = ()

    @classmethod
    def from_vault(cls, vault_root: str | Path) -> WorkIndex:
        """Build an index by scanning *vault_root* with the shared inventory scanner."""
        root = Path(vault_root).expanduser().resolve()
        records = scan_vault(root)
        entities = [entity for record in records if (entity := entity_from_record(record)) is not None]
        index = cls.from_entities(entities, root=root)
        structural = [
            ValidationIssue(path=item["path"], message=item["message"], severity=item["severity"], rule=item["code"])
            for item in structural_issues(records)
        ]
        if structural:
            index.issues = tuple(sorted([*index.issues, *structural], key=_issue_sort))
        return index

    @classmethod
    def from_entities(cls, entities: Iterable[EntityBase], *, root: str | Path | None = None) -> WorkIndex:
        """Assemble an index from typed entities (used by tests and callers)."""
        root_path = Path(root) if root is not None else Path(".")
        ordered = sorted(entities, key=lambda entity: (entity.entity_type.value, entity.title.casefold(), entity.path))
        lookup, duplicates = _build_lookup(ordered)
        issues: list[ValidationIssue] = [
            ValidationIssue(path="", message=f"Duplicate entity key: {key}", severity="warning", rule="duplicate")
            for key in duplicates
        ]
        issues.extend(validate_all(ordered, set(lookup)))
        issues.sort(key=_issue_sort)

        by_type: dict[str, list[EntityBase]] = {}
        for entity in ordered:
            by_type.setdefault(entity.entity_type.value, []).append(entity)

        return cls(
            root=root_path,
            entities=tuple(ordered),
            issues=tuple(issues),
            _by_type={key: tuple(value) for key, value in by_type.items()},
            _lookup=lookup,
            _duplicate_keys=duplicates,
        )

    def list_type(self, entity_type: str) -> tuple[EntityBase, ...]:
        """Return all entities of a type, in stable order."""
        return self._by_type.get(entity_type, ())

    def view_entities(self, entity_type: str) -> tuple[EntityBase, ...]:
        """Return entities of a type that have no validation errors."""
        error_paths = {issue.path for issue in self.errors}
        return tuple(entity for entity in self.list_type(entity_type) if entity.path not in error_paths)

    def get(self, entity_type: str, name: str) -> EntityBase | None:
        """Resolve a name to an entity of the requested type, or ``None``."""
        entity = self._lookup.get(link_target(name))
        if entity is not None and entity.entity_type.value == entity_type:
            return entity
        return None

    def resolve(self, target: str) -> EntityBase | None:
        """Resolve any wikilink/name target to an entity, or ``None``."""
        return self._lookup.get(link_target(target))

    def issues_for(self, path: str) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.path == path)

    def has_errors(self, path: str) -> bool:
        return has_errors(self.issues_for(path))

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def duplicate_keys(self) -> tuple[str, ...]:
        return self._duplicate_keys

    def counts(self) -> dict[str, int]:
        """Return entity counts per type, including zero-count types."""
        return {key: len(self._by_type.get(key, ())) for key in OPERATOR_TYPE_VALUES}

    def health(self) -> dict:
        """Return a health report listing every finding, including error notes."""
        return {
            "entities": len(self.entities),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "counts": self.counts(),
            "issues": [issue_to_dict(issue) for issue in self.issues],
        }


def entity_to_dict(entity: EntityBase) -> dict:
    """Serialize an entity for CLI JSON output (excluding the raw frontmatter)."""
    data = {field.name: getattr(entity, field.name) for field in dataclasses.fields(entity)}
    data["type"] = entity.entity_type.value
    data.pop("raw", None)
    return data


def issue_to_dict(issue: ValidationIssue) -> dict:
    return {"path": issue.path, "severity": issue.severity, "rule": issue.rule, "message": issue.message}


def _issue_sort(issue: ValidationIssue) -> tuple[str, str, str]:
    return (issue.path, issue.severity, issue.message)


def _build_lookup(entities: list[EntityBase]) -> tuple[dict[str, EntityBase], tuple[str, ...]]:
    """Build the name lookup with exact-filename-stem precedence over title and alias.

    A key claimed by two entities at the same precedence is ambiguous and resolves
    to nothing, so a link never invents an edge.
    """
    best: dict[str, tuple[int, EntityBase]] = {}
    duplicates: set[str] = set()
    for entity in entities:
        candidates = [(normalize_target(Path(entity.path).stem), 0), (normalize_target(entity.title), 1)]
        candidates.extend((normalize_target(alias), 2) for alias in entity.aliases)
        for key, precedence in candidates:
            if not key or key in duplicates:
                continue
            current = best.get(key)
            if current is None or precedence < current[0]:
                best[key] = (precedence, entity)
            elif precedence == current[0]:
                duplicates.add(key)
                best.pop(key, None)
    lookup = {key: entity for key, (_, entity) in best.items() if key not in duplicates}
    return lookup, tuple(sorted(duplicates))
