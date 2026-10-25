"""The single read-only retrieval seam.

CLI, GUI, and MCP map one-to-one onto these functions and recompute nothing. Every
function resolves the vault through the shared work index and opens the index read-only;
no write helper is reachable from here.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable
from datetime import UTC, date, datetime
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
from worksync.inventory.parse import iter_markdown, scan_vault
from worksync.work.command_center import entity_contract_dict as _entity_contract_dict
from worksync.work.command_center import my_priorities as _my_priorities
from worksync.work.command_center import needs_attention as _needs_attention
from worksync.work.command_center import section_result_to_dict as _section_result_to_dict
from worksync.work.control_center import build_control_center
from worksync.work.layout_profile import apply_profile, default_profile, read_profile
from worksync.work.lifecycle.loader import load_project_records
from worksync.work.lifecycle.registry_model import LifecycleRegistry, read_registry
from worksync.work.models import entity_id_of
from worksync.work.override import read_overrides as _read_overrides
from worksync.work.prioritization import Override
from worksync.work.processing import processing_status as _processing_status
from worksync.work.relationships import related_to
from worksync.work.render import (
    attention_to_dict,
    project_review_to_dict,
    relationships_to_dict,
    workload_to_dict,
)
from worksync.work.repository import WorkIndex, entity_to_dict
from worksync.work.review import (
    attention_by_path as _attention_by_path,
)
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
from worksync.work.since_last_check import read_checkpoint as _read_checkpoint
from worksync.work.since_last_check import since_last_check_from_records as _since_last_check_from_records
from worksync.work.since_last_check import since_last_check_to_dict as _since_last_check_to_dict

ENTITY_TYPES = ("project", "person", "ticket", "meeting", "action")


def default_paths() -> tuple[Path, Path]:
    """Resolve the configured vault root and derived index path, or fail closed."""
    try:
        config = load_config()
    except ConfigError as exc:
        raise ServiceError(str(exc)) from exc
    return config.vault_path, index_path(config.runtime_root)


_scan_lock = threading.RLock()
_scan_cache: dict[str, tuple[str, tuple]] = {}


def _vault_signature(vault: Path) -> str:
    """A cheap, content-and-name-sensitive signature of the vault's markdown set.

    Hashes each note's relative path, mtime (ns), and size in deterministic order, so an
    edit, add, remove, or rename all change the signature. This is the invalidation key for
    the scan cache; it uses the same ``iter_markdown``/``EXCLUDED_DIRS`` walk as ``scan_vault``.
    """
    digest = hashlib.sha256()
    for path in iter_markdown(vault):
        stat = path.stat()
        relative = path.relative_to(vault).as_posix()
        digest.update(f"{relative}:{stat.st_mtime_ns}:{stat.st_size}\0".encode())
    return digest.hexdigest()


def _cached_scan(vault: str | Path) -> tuple:
    """Return the vault's scan, reused across requests until the vault changes.

    The GUI is long-running, but every read was re-scanning the whole vault per request.
    This caches the scan per resolved vault and re-scanning only on a signature change.
    """
    root = Path(vault).expanduser().resolve()
    with _scan_lock:
        signature = _vault_signature(root)
        cached = _scan_cache.get(str(root))
        if cached is not None and cached[0] == signature:
            return cached[1]
        records = tuple(scan_vault(root))
        _scan_cache[str(root)] = (signature, records)
        return records


def _index(vault: str | Path) -> WorkIndex:
    return WorkIndex.from_records(_cached_scan(vault), Path(vault).expanduser().resolve())


def _project_entity(index: WorkIndex, name: str):
    resolved = _resolve_project(index, {"name": name})
    if resolved.get("status") != "resolved":
        return None
    project_id = resolved["project_id"]
    return next((entity for entity in index.list_type("project") if entity.project_id == project_id), None)


def _overrides_payload(index: WorkIndex, overrides: Iterable[Override]) -> list[dict]:
    """Resolve every active override to the label and path its target carries.

    An override outlives its section row: a ``not_relevant`` target is dropped from My
    Priorities, so the view cannot rely on a section item to name and clear it. The index
    supplies the label and path; a target that is no longer in the vault falls back to its
    id with an empty path, so it stays visible and reversible.
    """
    entities_by_id = {entity_id_of(entity): entity for entity in index.entities}
    rows = []
    for override in overrides:
        entity = entities_by_id.get(override.target_id)
        rows.append(
            {
                "target_id": override.target_id,
                "kind": override.kind,
                "reason": override.reason,
                "label": (entity.title if entity is not None else "") or override.target_id,
                "path": entity.path if entity is not None else "",
            }
        )
    return rows


def command_center(
    vault: str | Path,
    runtime_root: str | Path,
    today: date,
    *,
    owner_id: str | None = None,
    generated_at: str | None = None,
) -> dict:
    """Assemble the Command Center's three sections from one index build, read-only.

    ``generated_at`` is injectable so a fixed vault and checkpoint yield a deterministic
    payload. The layout profile supplies the section order, per-section visibility, and the
    "Me" owner; an explicit ``owner_id`` overrides the profile's for programmatic callers.
    Without an owner My Priorities reports unavailable. ``overrides`` lists every active
    override with its target resolved to a label and path, so an override whose row left
    every section (``not_relevant``) can still be seen and cleared.
    """
    root = Path(vault).expanduser().resolve()
    records = _cached_scan(vault)
    index = WorkIndex.from_records(records, root)
    when = generated_at or datetime.now(UTC).isoformat()
    try:
        checkpoint = _read_checkpoint(runtime_root)
    except ValueError:
        # A present-but-malformed checkpoint must not brick the default screen: degrade the
        # Since Last Check section to "unavailable" / "no_checkpoint" and keep the other two
        # sections rendering. The next acknowledge repairs the corrupt file (ruling R4).
        checkpoint = None
    try:
        profile = read_profile(runtime_root)
    except ValueError:
        # Mirror the checkpoint wrap (ruling R3): a corrupt profile falls back to the
        # defaults instead of failing the read; the save path repairs the file.
        profile = default_profile()
    try:
        overrides = _read_overrides(runtime_root)
    except ValueError:
        # Overrides fail closed on read (ruling R2), but that must not brick the default
        # screen (ruling R6): a malformed file degrades My Priorities to the baseline
        # ranking, and the next save repairs the record.
        overrides = ()
    owner = owner_id if owner_id is not None else profile.owner_id
    sections = [
        _section_result_to_dict(_needs_attention(index, today, generated_at=when)),
        _section_result_to_dict(_my_priorities(index, owner, today, generated_at=when, overrides=overrides)),
        _since_last_check_to_dict(_since_last_check_from_records(records, checkpoint, generated_at=when)),
    ]
    profile_payload = profile.to_dict()
    # Contract boundary: the stored record keeps its R1 shape (``updated_at: ""``), while the
    # read contract reports an absent timestamp as ``null``, never an empty string.
    profile_payload["updated_at"] = profile_payload.get("updated_at") or None
    return {
        "generated_at": when,
        "profile": profile_payload,
        "sections": apply_profile(sections, profile),
        "overrides": _overrides_payload(index, overrides),
    }


def entity_contract(vault: str | Path, entity_id: str, today: date) -> dict | None:
    """Return the contract's intrinsic detail object for one entity id, or ``None``.

    Resolution is by stable id through the shared index — never by filesystem path — and the
    object carries only the declared contract fields.
    """
    index = _index(vault)
    entity = next((candidate for candidate in index.entities if entity_id_of(candidate) == entity_id), None)
    if entity is None:
        return None
    kinds = tuple(item.kind for item in _attention_by_path(index, today).get(entity.path, ()))
    return _entity_contract_dict(entity, index=index, attention_kinds=kinds)


def resolve_project(vault: str | Path, hint: dict | None) -> dict:
    return _resolve_project(_index(vault), hint)


def list_projects(vault: str | Path, db_path: str | Path | None = None) -> list[dict]:
    return _list_projects(_index(vault), db_path=db_path)


def health(vault: str | Path) -> dict:
    """Return the vault-wide health report: counts and validation issues."""
    return _index(vault).health()


def processing(runtime_root: str | Path) -> dict:
    """Read-only operational status: review queues, Krisp sync, and recent activity."""
    return _processing_status(runtime_root)


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
