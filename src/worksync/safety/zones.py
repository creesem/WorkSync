"""Shared write-zone mapping for canonical and derived writes.

A write zone pairs a named root with its policy (see ``safety.models``): ``trusted``
is the vault, ``runtime`` is the runtime root, and the derived zones live under the
runtime root. Building zones in one place keeps every writer's containment and write
class consistent.
"""

from __future__ import annotations

from pathlib import Path

from worksync.core.paths import GENERATED_INTERFACE_REL


def write_zones(vault_root: str | Path, runtime_root: str | Path) -> dict[str, Path]:
    """Return the standard writable roots for a vault and runtime root."""
    vault = Path(vault_root).expanduser().resolve()
    runtime = Path(runtime_root).expanduser().resolve()
    return {
        "trusted": vault,
        "staging": runtime / "staging",
        "ingest": runtime / "ingest",
        "views": runtime / "views",
        "generated": vault / GENERATED_INTERFACE_REL,
        "runtime": runtime,
    }
