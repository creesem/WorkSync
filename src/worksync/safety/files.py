"""Atomic file primitives and sync-conflict/provisional-file detection.

Ported from the previous application's ``mutation_safety`` so the gateway writes
through one atomic path and fails closed on OneDrive conflict or provisional files.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

CONFLICT_COPY = re.compile(r"\s*\((?:[^()]+'s\s+)?conflicted copy(?:\s+[^()]*)?\)$", re.IGNORECASE)
PROVISIONAL_NAMES = (
    re.compile(r"^~\$", re.IGNORECASE),
    re.compile(r"\.(?:tmp|temp|partial|part|crdownload)$", re.IGNORECASE),
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def is_conflict_copy(path: str | Path) -> bool:
    return bool(CONFLICT_COPY.search(Path(path).stem))


def is_provisional_file(path: str | Path) -> bool:
    name = Path(path).name
    return any(pattern.search(name) for pattern in PROVISIONAL_NAMES)


def conflict_key(path: str | Path) -> str:
    path = Path(path)
    return f"{CONFLICT_COPY.sub('', path.stem).casefold()}{path.suffix.casefold()}"


def conflicts_for(path: str | Path) -> list[Path]:
    """Return conflict-copy siblings of *path*, if any."""
    path = Path(path)
    if not path.parent.is_dir():
        return []
    key = conflict_key(path)
    return sorted(
        (
            candidate
            for candidate in path.parent.iterdir()
            if candidate.is_file()
            and conflict_key(candidate) == key
            and (is_conflict_copy(candidate) or is_conflict_copy(path))
        ),
        key=lambda candidate: candidate.name.casefold(),
    )


def atomic_write_bytes(
    path: str | Path,
    content: bytes,
    *,
    expected_sha256: str | None = None,
    expected_absent: bool = False,
) -> None:
    """Write *content* atomically, refusing on a changed or appeared target."""
    path = Path(path)
    if expected_sha256 is not None and expected_absent:
        raise ValueError("Expected hash and expected absence are mutually exclusive")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".worksync-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_absent and path.exists():
            raise RuntimeError(f"Target appeared during processing: {path}")
        if expected_sha256 is not None and (not path.is_file() or sha256_file(path) != expected_sha256):
            raise RuntimeError(f"File changed during processing: {path}")
        if path.exists():
            shutil.copystat(path, temp_name)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_text(
    path: str | Path,
    content: str,
    *,
    expected_sha256: str | None = None,
    expected_absent: bool = False,
) -> None:
    atomic_write_bytes(
        path,
        content.encode("utf-8"),
        expected_sha256=expected_sha256,
        expected_absent=expected_absent,
    )
