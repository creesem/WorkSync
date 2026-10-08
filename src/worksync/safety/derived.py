"""Narrow seam for non-canonical derived writes (runtime JSON, generated artifacts).

Derived writers still enforce containment and create/overwrite policy but skip the
canonical backup/reviewer gate. This keeps the atomic file primitives internal to
``safety``: no other layer calls ``atomic_write_*`` directly.

The artifacts written here are runtime state singletons that the application owns and
regenerates (the workday plan, the remembered reviewer). Their normal operation is an
idempotent overwrite of the current value, so this seam overwrites by default rather
than requiring ``expected_absent`` or an explicit ``force``; the canonical
create-only/backup rules apply to the ``trusted`` vault, not to runtime state. Callers
must pass a root that contains the target; an escape fails closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from worksync.core.paths import ensure_under
from worksync.safety.files import atomic_write_text


def _contained(root: str | Path, target: str | Path) -> Path:
    root_path = Path(root).expanduser().resolve()
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    return ensure_under(root_path, candidate)


def write_text(
    root: str | Path,
    target: str | Path,
    content: str,
    *,
    expected: str | None = None,
    expected_absent: bool = False,
) -> Path:
    """Atomically write derived text under *root*, refusing a containment escape.

    ``expected`` and ``expected_absent`` add a stale-state precondition so a concurrent
    writer (for example another app tab) cannot clobber this one; a mismatch fails closed.
    """
    resolved = _contained(root, target)
    atomic_write_text(resolved, content, expected_sha256=expected, expected_absent=expected_absent)
    return resolved


def write_json(
    root: str | Path,
    target: str | Path,
    payload: Any,
    *,
    expected: str | None = None,
    expected_absent: bool = False,
) -> Path:
    """Atomically write derived JSON under *root*, refusing a containment escape."""
    return write_text(
        root,
        target,
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        expected=expected,
        expected_absent=expected_absent,
    )
