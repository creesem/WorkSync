"""The pure lifecycle-registry data model and path helpers (no IO, no safety).

Split from :mod:`worksync.work.lifecycle.registry` so read-only consumers (the loader
and the control center) can join records to the registry without reaching any write
helper. The stale-safe store lives in ``registry``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.work.lifecycle.records import RegistryError

REGISTRY_VERSION = 1
REGISTRY_FILENAME = "lifecycle.json"
RUNTIME_PROJECT_DIR = "project"


def _safe_project_id(project_id: object) -> str:
    value = str(project_id or "").strip()
    if not value or value in {".", ".."} or Path(value).name != value:
        raise RegistryError("invalid_project_id", f"Unsafe project id for a registry path: {project_id!r}")
    return value


def project_registry_dir(runtime_root: str | Path, project_id: str) -> Path:
    """Return the derived registry directory for one project."""
    runtime = Path(runtime_root).expanduser().resolve()
    safe = _safe_project_id(project_id)
    target = (runtime / RUNTIME_PROJECT_DIR / safe).resolve()
    try:
        return ensure_under(runtime, target)
    except PathSafetyError as exc:
        raise RegistryError("invalid_project_id", str(exc), affected=(str(project_id),)) from exc


def registry_path(runtime_root: str | Path, project_id: str) -> Path:
    """Return the derived registry file path for one project."""
    return project_registry_dir(runtime_root, project_id) / REGISTRY_FILENAME


def now() -> str:
    """Return the current UTC timestamp recorded on a registry write."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Transition:
    """One recorded lifecycle transition: who changed what, why, and from/to where."""

    at: str
    actor: str
    reason: str
    from_state: str
    to_state: str
    evidence: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "at": self.at,
            "actor": self.actor,
            "reason": self.reason,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transition:
        return cls(
            at=str(data.get("at") or ""),
            actor=str(data.get("actor") or ""),
            reason=str(data.get("reason") or ""),
            from_state=str(data.get("from_state") or ""),
            to_state=str(data.get("to_state") or ""),
            evidence=str(data.get("evidence") or ""),
        )


@dataclass(frozen=True)
class LifecycleEntry:
    """One tracked canonical record: its current state and transition history."""

    record_id: str
    record_kind: str
    lifecycle_state: str
    provenance: tuple[str, ...] = ()
    transitions: tuple[Transition, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_kind": self.record_kind,
            "lifecycle_state": self.lifecycle_state,
            "provenance": list(self.provenance),
            "transitions": [transition.to_dict() for transition in self.transitions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifecycleEntry:
        provenance = data.get("provenance")
        transitions = data.get("transitions")
        return cls(
            record_id=str(data.get("record_id") or ""),
            record_kind=str(data.get("record_kind") or ""),
            lifecycle_state=str(data.get("lifecycle_state") or ""),
            provenance=tuple(str(item) for item in provenance) if isinstance(provenance, list) else (),
            transitions=tuple(Transition.from_dict(item) for item in transitions if isinstance(item, dict))
            if isinstance(transitions, list)
            else (),
        )


@dataclass(frozen=True)
class LifecycleRegistry:
    """The derived registry for one project, keyed by canonical record path."""

    project_id: str
    records: tuple[LifecycleEntry, ...] = ()
    version: int = REGISTRY_VERSION
    updated_at: str = ""

    def entry(self, record_id: str) -> LifecycleEntry | None:
        """Return the entry for one record id, or ``None`` when it is not tracked."""
        return next((entry for entry in self.records if entry.record_id == record_id), None)

    def with_records(self, records: tuple[LifecycleEntry, ...]) -> LifecycleRegistry:
        """Return a new registry carrying *records* and a fresh timestamp."""
        return replace(self, records=tuple(records), updated_at=now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project_id": self.project_id,
            "updated_at": self.updated_at,
            "records": [entry.to_dict() for entry in self.records],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifecycleRegistry:
        records = data.get("records")
        return cls(
            project_id=str(data.get("project_id") or ""),
            records=tuple(LifecycleEntry.from_dict(item) for item in records if isinstance(item, dict))
            if isinstance(records, list)
            else (),
            version=int(data.get("version") or REGISTRY_VERSION),
            updated_at=str(data.get("updated_at") or ""),
        )


def render_registry(registry: LifecycleRegistry) -> str:
    """Return the exact registry bytes as text, shared by save and the gateway op."""
    return json.dumps(registry.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n"


def read_registry(runtime_root: str | Path, project_id: str) -> LifecycleRegistry | None:
    """Read the registry without any write helper; ``None`` when absent or unreadable."""
    path = registry_path(runtime_root, project_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return LifecycleRegistry.from_dict(data)
