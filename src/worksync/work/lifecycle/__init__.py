"""lifecycle — project delivery state machines, control center, and walkthrough.

Depends on ``core``, ``inventory``, ``safety``, and ``work``; imports no ``context``
and no ``html``. Transition history and review ledgers are derived runtime state.
"""

from __future__ import annotations

from worksync.work.lifecycle.loader import LifecycleRecord, load_project_records
from worksync.work.lifecycle.records import (
    DATE_FIELDS,
    ISSUE_FIELDS,
    RECORD_ENTITY_TYPE,
    WAITING_FIELDS,
    RecordKind,
    RegistryError,
    fields_for_kind,
    is_record_kind,
    record_entity_type,
)
from worksync.work.lifecycle.registry import (
    LifecycleEntry,
    LifecycleRegistry,
    LifecycleStore,
    Transition,
    project_registry_dir,
    registry_path,
)

__all__ = [
    "DATE_FIELDS",
    "ISSUE_FIELDS",
    "RECORD_ENTITY_TYPE",
    "WAITING_FIELDS",
    "LifecycleEntry",
    "LifecycleRecord",
    "LifecycleRegistry",
    "LifecycleStore",
    "RecordKind",
    "RegistryError",
    "Transition",
    "fields_for_kind",
    "is_record_kind",
    "load_project_records",
    "project_registry_dir",
    "record_entity_type",
    "registry_path",
]
