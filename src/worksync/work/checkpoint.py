"""The "Since Last Check" checkpoint write path.

The read model over the checkpoint lives in ``worksync.work.since_last_check``. The write
lives here, in its own module, so the GUI's read seam can import the read model without
dragging the safety layer into its import closure (see
``test_gui_read_seam_import_closure_reaches_no_write_helper``).

A checkpoint is the acknowledged baseline for "Since Last Check": the content hash of every
vault note at the moment the user acknowledged. It lives in the ``user_state`` zone
(``runtime/user_state/checkpoint.json``), so this one write is journaled and backed up but
never touches a note — acknowledging can never complete an action. The stored shape is ruling
R2: ``{"version": 1, "acknowledged_at": "<iso>", "notes": {path: sha256}}``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp
from worksync.safety.zones import write_zones
from worksync.work.since_last_check import CHECKPOINT_FILENAME, USER_STATE_ZONE, checkpoint_path


def acknowledge_checkpoint(
    vault_root: str | Path,
    runtime_root: str | Path,
    snapshot: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> CommitResult:
    """Write *snapshot* (path -> sha256) as the acknowledged checkpoint, atomically.

    Creates the file on first acknowledge and sha-preconditioned-updates it thereafter. Writes
    only ``checkpoint.json`` in the ``user_state`` zone — never a note — so acknowledging can
    never complete an action.
    """
    when = now or datetime.now(UTC)
    target = checkpoint_path(runtime_root)
    content = json.dumps(
        {
            "version": 1,
            "acknowledged_at": when.isoformat(),
            "notes": dict(sorted(snapshot.items())),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    if target.is_file():
        op = FileOp(
            "update",
            Path(CHECKPOINT_FILENAME),
            USER_STATE_ZONE,
            content=content,
            expected=sha256_file(target),
        )
    else:
        op = FileOp("create", Path(CHECKPOINT_FILENAME), USER_STATE_ZONE, content=content)
    changeset = ChangeSet(
        verb="acknowledge",
        ops=(op,),
        reason="Acknowledge the current vault as the since-last-check checkpoint",
    )
    return commit(changeset, write_zones(vault_root, runtime_root), now=when)
