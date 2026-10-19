"""Shared write-zone mapping for canonical, derived, and user-state writes.

A write zone pairs a named root with its write class (see ``safety.models``):
``trusted`` is the vault, ``runtime`` is the runtime root, the derived zones live
under the runtime root, and ``user_state`` is the user-owned state root, also under
the runtime root. Building zones in one place keeps every writer's containment and
write class consistent.
"""

from __future__ import annotations

from pathlib import Path

from worksync.core.paths import GENERATED_INTERFACE_REL

STAGING_DIRNAME = "staging"


def staging_root(runtime_root: str | Path) -> Path:
    """Return the derived staging root under the runtime root."""
    return Path(runtime_root).expanduser().resolve() / STAGING_DIRNAME


def write_zones(vault_root: str | Path, runtime_root: str | Path) -> dict[str, Path]:
    """Return the standard writable roots for a vault and runtime root."""
    vault = Path(vault_root).expanduser().resolve()
    runtime = Path(runtime_root).expanduser().resolve()
    return {
        "trusted": vault,
        "staging": staging_root(runtime),
        "ingest": runtime / "ingest",
        "views": runtime / "views",
        "generated": vault / GENERATED_INTERFACE_REL,
        "runtime": runtime,
        "user_state": runtime / "user_state",
    }
