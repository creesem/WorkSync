"""Vault containment, legacy-path rebasing, and unique-target helpers.

All paths a caller supplies are resolved before validation; nothing here mutates
a note or assumes a development-machine location.
"""

from __future__ import annotations

from pathlib import Path

from worksync.core.names import safe_name

GENERATED_INTERFACE_REL = Path("0. System") / "Interface"


class PathSafetyError(ValueError):
    """Raised when a path escapes its allowed root."""


def ensure_under(root: str | Path, target: str | Path) -> Path:
    """Resolve ``target`` and refuse it when it escapes ``root``.

    Absolute paths outside the root and paths that traverse out via ``..`` are
    refused after resolution. The resolved path is returned.
    """
    root_resolved = Path(root).expanduser().resolve(strict=False)
    target_resolved = Path(target).expanduser().resolve(strict=False)
    if not target_resolved.is_relative_to(root_resolved):
        raise PathSafetyError(f"Refusing path outside allowed root: {target_resolved}")
    return target_resolved


def _clean(value: object) -> str:
    return str(value or "").strip().strip("\"'`")


def _as_posix(value: object) -> str:
    return str(value).replace("\\", "/").rstrip("/")


def resolve_stored_path(
    vault: str | Path,
    stored: str,
    *,
    legacy_roots: tuple[str, ...] = (),
) -> Path:
    """Return the real file for a stored path, rebasing known legacy roots.

    Stored paths are advisory: OneDrive may have moved the file. The path is
    resolved against the configured vault, legacy roots are rebased at read time,
    and the result must remain inside the vault. Fails closed when the target
    cannot be located; never mutates a note.
    """
    vault_path = Path(vault).expanduser().resolve()
    clean = _clean(stored)
    if not clean:
        raise FileNotFoundError("A stored path is required.")

    candidate = Path(clean)
    if not candidate.is_absolute():
        inside = (vault_path / candidate).resolve()
        if inside.is_file() and inside.is_relative_to(vault_path):
            return inside
    elif candidate.is_file():
        resolved = candidate.resolve()
        if resolved.is_relative_to(vault_path):
            return resolved
        raise FileNotFoundError(f"Stored path is outside the configured vault: {clean}")

    stored_posix = _as_posix(clean)
    for legacy in legacy_roots:
        legacy_posix = _as_posix(legacy)
        stored_posix_cf = stored_posix.casefold()
        legacy_posix_cf = legacy_posix.casefold()
        if stored_posix_cf == legacy_posix_cf or stored_posix_cf.startswith(legacy_posix_cf + "/"):
            remainder = stored_posix[len(legacy_posix) :].lstrip("/")
            rebased = (vault_path / remainder).resolve()
            if rebased.is_file() and rebased.is_relative_to(vault_path):
                return rebased
            raise FileNotFoundError(f"Stored path was not found under the configured vault: {clean}")

    raise FileNotFoundError(f"Stored path could not be resolved: {clean}")


def unique_target(directory: str | Path, name: str) -> Path:
    """Return a collision-free path under *directory* for *name*.

    Never overwrites a same-named file: ``note.md`` becomes ``note 1.md`` and so on.
    """
    directory = Path(directory)
    safe = safe_name(name) or "untitled"
    stem = Path(safe).stem
    suffix = Path(safe).suffix
    candidate = directory / safe
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem} {counter}{suffix}"
        counter += 1
    return candidate
