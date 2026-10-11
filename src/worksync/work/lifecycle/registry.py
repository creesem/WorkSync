"""The stale-safe store for the derived lifecycle registry.

The pure registry model and path helpers live in
:mod:`worksync.work.lifecycle.registry_model`; this module adds only the guarded,
stale-safe persistence and the gateway ``FileOp``. The registry update travels in the
same ``ChangeSet`` as the canonical write it records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from worksync.safety import derived
from worksync.safety.files import sha256_file
from worksync.safety.models import FileOp
from worksync.work.lifecycle.records import RegistryError
from worksync.work.lifecycle.registry_model import (
    REGISTRY_FILENAME,
    REGISTRY_VERSION,
    RUNTIME_PROJECT_DIR,
    LifecycleEntry,
    LifecycleRegistry,
    Transition,
    _safe_project_id,
    now,
    project_registry_dir,
    registry_path,
    render_registry,
)

__all__ = [
    "REGISTRY_FILENAME",
    "REGISTRY_VERSION",
    "RUNTIME_PROJECT_DIR",
    "LifecycleEntry",
    "LifecycleRegistry",
    "LifecycleStore",
    "RegistryError",
    "Transition",
    "now",
    "project_registry_dir",
    "registry_path",
    "render_registry",
]


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
