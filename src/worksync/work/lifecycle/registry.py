"""The derived lifecycle registry, stored only under the runtime project zone.

The registry holds each record's current lifecycle state and its transition history
under ``var/project/<project_id>/lifecycle.json``. It is derived, regenerable state:
never a vault sidecar (the legacy ``9. Project/<project>/`` location is retired), and
never a source of truth. Persistence is stale-safe so concurrent tabs cannot clobber
one another, and the registry update travels in the same ``ChangeSet`` as the
canonical write it records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.safety import derived
from worksync.safety.files import sha256_file
from worksync.safety.models import FileOp
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


@dataclass(frozen=True)
class LifecycleStore:
    """Guarded, stale-safe persistence for one project's derived registry."""

    runtime_root: str | Path
    project_id: str

    def path(self) -> Path:
        """Return the registry path under the runtime project zone."""
        return registry_path(self.runtime_root, self.project_id)

    def rel(self) -> Path:
        """Return the registry path relative to the runtime root, for the gateway."""
        return Path(RUNTIME_PROJECT_DIR) / _safe_project_id(self.project_id) / REGISTRY_FILENAME

    def sha256(self) -> str | None:
        """Return the registry's current content hash, or ``None`` when absent."""
        path = self.path()
        return sha256_file(path) if path.is_file() else None

    def load_with_hash(self) -> tuple[LifecycleRegistry, str] | None:
        """Load the registry and the hash of the exact bytes read."""
        path = self.path()
        if not path.is_file():
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        digest = hashlib.sha256(raw).hexdigest()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return LifecycleRegistry.from_dict(data), digest

    def load(self) -> LifecycleRegistry | None:
        """Load the registry, or ``None`` when it is absent or unreadable."""
        loaded = self.load_with_hash()
        return loaded[0] if loaded is not None else None

    def save(
        self,
        registry: LifecycleRegistry,
        *,
        expected: str | None = None,
        expected_absent: bool = False,
    ) -> Path:
        """Write the registry with a stale-state precondition; a mismatch fails closed."""
        return derived.write_text(
            project_registry_dir(self.runtime_root, self.project_id),
            REGISTRY_FILENAME,
            render_registry(registry),
            expected=expected,
            expected_absent=expected_absent,
        )

    def registry_op(self, registry: LifecycleRegistry, *, expected: str | None) -> FileOp:
        """Return the registry ``FileOp`` for a transition's ``ChangeSet`` (runtime zone)."""
        kind = "update" if expected is not None else "create"
        return FileOp(kind, self.rel(), "runtime", content=render_registry(registry), expected=expected)
