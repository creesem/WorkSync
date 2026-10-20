"""The Command Center layout profile write path.

The read model lives in ``worksync.work.layout_profile``. The writes live here, in their
own module, so the GUI's read seam can import the read model without dragging the safety
layer into its import closure (mirroring the checkpoint split).

The profile is a ``user_state`` record (``runtime/user_state/layout_profile.json``), so
these writes are journaled and backed up but never touch a note. Ruling R5: ``save_profile``
bumps ``revision``, stamps ``updated_at``, and creates the file on first save or
sha-preconditioned-updates it thereafter. It never parses the existing file — a corrupt
profile is repaired rather than blocking (mirroring the checkpoint's ruling R4).
``reset_profile`` writes the default profile at revision 1.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.layout_profile import PROFILE_FILENAME, LayoutProfile, default_profile, profile_path
from worksync.work.since_last_check import USER_STATE_ZONE

SAVE_VERB = "save_layout"
SAVE_REASON = "Save the Command Center layout profile"
RESET_VERB = "reset_layout"
RESET_REASON = "Reset the Command Center layout profile"


def save_profile(
    vault_root: str | Path,
    runtime_root: str | Path,
    profile: LayoutProfile,
    *,
    now: str | None = None,
) -> CommitResult:
    """Persist *profile*, bumping its revision and stamping ``updated_at``.

    Creates ``layout_profile.json`` on the first save and sha-preconditioned-updates it
    thereafter. Writes only the ``user_state`` record — never a note.
    """
    when = _resolve_now(now)
    saved = replace(profile, revision=profile.revision + 1, updated_at=when.isoformat())
    return _commit_profile(vault_root, runtime_root, saved, verb=SAVE_VERB, reason=SAVE_REASON, when=when)


def reset_profile(
    vault_root: str | Path,
    runtime_root: str | Path,
    *,
    now: str | None = None,
) -> CommitResult:
    """Restore the default profile (revision 1), stamped with ``updated_at``."""
    when = _resolve_now(now)
    saved = replace(default_profile(), updated_at=when.isoformat())
    return _commit_profile(vault_root, runtime_root, saved, verb=RESET_VERB, reason=RESET_REASON, when=when)


def _resolve_now(now: str | None) -> datetime:
    """Return the injected instant (ISO string) or the current UTC time."""
    return datetime.fromisoformat(now) if now is not None else datetime.now(UTC)


def _commit_profile(
    vault_root: str | Path,
    runtime_root: str | Path,
    profile: LayoutProfile,
    *,
    verb: str,
    reason: str,
    when: datetime,
) -> CommitResult:
    target = profile_path(runtime_root)
    content = json.dumps(profile.to_dict(), sort_keys=True, ensure_ascii=False)
    if target.is_file():
        op = FileOp(
            "update",
            Path(PROFILE_FILENAME),
            USER_STATE_ZONE,
            content=content,
            expected=sha256_file(target),
        )
    else:
        op = FileOp("create", Path(PROFILE_FILENAME), USER_STATE_ZONE, content=content)
    changeset = ChangeSet(verb=verb, ops=(op,), reason=reason)
    return commit(changeset, write_zones(vault_root, runtime_root), now=when)
