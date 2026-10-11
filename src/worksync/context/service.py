"""The single read-only retrieval seam.

CLI, GUI, and MCP map one-to-one onto these functions and recompute nothing. Every
function resolves the vault through the shared work index and opens the index read-only;
no write helper is reachable from here.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from worksync.context.projection import get_staleness as _get_staleness
from worksync.context.projection import read_context as _read_context
from worksync.context.registry import list_projects as _list_projects
from worksync.context.registry import resolve_project as _resolve_project
from worksync.context.retrieval import ServiceError
from worksync.context.retrieval import read_evidence as _read_evidence
from worksync.context.retrieval import search_evidence as _search_evidence
from worksync.core.config import ConfigError, load_config
from worksync.inventory.index import index_path
from worksync.work.control_center import build_control_center
from worksync.work.lifecycle.loader import load_project_records
from worksync.work.lifecycle.registry_model import LifecycleRegistry, read_registry
from worksync.work.relationships import related_to
from worksync.work.render import (
    attention_to_dict,
    project_review_to_dict,
    relationships_to_dict,
    workload_to_dict,
)
from worksync.work.repository import WorkIndex, entity_to_dict
from worksync.work.review import (
    attention_items as _attention_items,
)
from worksync.work.review import (
    build_person_workload,
    build_project_review,
)
from worksync.work.review import (
    person_workloads as _person_workloads,
)
from worksync.work.review import (
    project_reviews as _project_reviews,
)

ENTITY_TYPES = ("project", "person", "ticket", "meeting", "action")


def default_paths() -> tuple[Path, Path]:
    """Resolve the configured vault root and derived index path, or fail closed."""
    try:
        config = load_config()
    except ConfigError as exc:
        raise ServiceError(str(exc)) from exc
    return config.vault_path, index_path(config.runtime_root)


def _index(vault: str | Path) -> WorkIndex:
    return WorkIndex.from_vault(vault)


def _project_entity(index: WorkIndex, name: str):
    resolved = _resolve_project(index, {"name": name})
    if resolved.get("status") != "resolved":
        return None
    project_id = resolved["project_id"]
    return next((entity for entity in index.list_type("project") if entity.project_id == project_id), None)


def resolve_project(vault: str | Path, hint: dict | None) -> dict:
    return _resolve_project(_index(vault), hint)


def list_projects(vault: str | Path, db_path: str | Path | None = None) -> list[dict]:
    return _list_projects(_index(vault), db_path=db_path)


def health(vault: str | Path) -> dict:
    """Return the vault-wide health report: counts and validation issues."""
    return _index(vault).health()


def get_entity(vault: str | Path, entity_type: str, name: str) -> dict | None:
    index = _index(vault)
    entity = _project_entity(index, name) if entity_type == "project" else index.get(entity_type, name)
    return entity_to_dict(entity) if entity is not None else None


def list_entities(vault: str | Path, entity_type: str) -> list[dict]:
    return [entity_to_dict(entity) for entity in _index(vault).view_entities(entity_type)]


def relationships(vault: str | Path, entity_type: str, name: str) -> dict | None:
    index = _index(vault)
    entity = _project_entity(index, name) if entity_type == "project" else index.get(entity_type, name)
    if entity is None:
        return None
    return relationships_to_dict(related_to(index, entity))


def attention(vault: str | Path, today: date) -> list[dict]:
    return [attention_to_dict(item) for item in _attention_items(_index(vault), today)]


def project_review(vault: str | Path, name: str, today: date) -> dict | None:
    index = _index(vault)
    project = _project_entity(index, name)
    if project is None:
        return None
    return project_review_to_dict(build_project_review(index, project, today))


def project_reviews(vault: str | Path, today: date) -> list[dict]:
    return [project_review_to_dict(review) for review in _project_reviews(_index(vault), today)]


def person_workload(vault: str | Path, name: str, today: date) -> dict | None:
    index = _index(vault)
    person = index.get("person", name)
    if person is None:
        return None
    return workload_to_dict(build_person_workload(index, person, today))


def person_workloads(vault: str | Path, today: date) -> list[dict]:
    return [workload_to_dict(workload) for workload in _person_workloads(_index(vault), today)]


def search_evidence(
    vault: str | Path,
    db_path: str | Path,
    query: str,
    *,
    project_id: str | None = None,
    limit: int = 10,
    filters: dict | None = None,
) -> dict:
    return _search_evidence(
        db_path,
        query,
        project_id=project_id,
        limit=limit,
        filters=filters,
        vault=vault,
    )


def read_evidence(vault: str | Path, db_path: str | Path, project_id: str, source_id: str) -> dict:
    return _read_evidence(db_path, project_id, source_id, vault=vault)


def read_context(vault: str | Path, db_path: str | Path, project_id: str, repo: str | None = None) -> dict:
    return _read_context(_index(vault), db_path, project_id, repo=repo)


def get_staleness(vault: str | Path, db_path: str | Path, project_id: str, repo: str | None = None) -> dict:
    return _get_staleness(_index(vault), db_path, project_id, repo=repo)


def control_center(vault: str | Path, runtime: str | Path, project_id: str, today: date) -> dict | None:
    """The read-only lifecycle control center for one project, or ``None`` when unknown."""
    index = _index(vault)
    project = next(
        (entity for entity in index.list_type("project") if getattr(entity, "project_id", None) == project_id), None
    )
    if project is None:
        return None
    registry = read_registry(runtime, project_id) or LifecycleRegistry(project_id=project_id)
    records = load_project_records(index, registry)
    return build_control_center(index, project, records, today=today)
