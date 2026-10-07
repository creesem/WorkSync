"""The contained, derived writer for the generated HTML interface.

Pages are written as one ``safety.commit`` transaction into the ``generated`` zone
(``0. System/Interface`` inside the vault). Creating a page is allowed; replacing an
existing page requires explicit confirmation and ``force``. No canonical note is
touched, and a failed transaction leaves no partial page set.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from worksync.html.generator import GeneratedPage
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, CommitResult, FileOp, MutationError
from worksync.safety.zones import write_zones

GENERATED_ZONE = "generated"


def generated_zones(vault_root: str | Path, runtime_root: str | Path) -> dict[str, Path]:
    """Return the writable roots for the generated interface, including the vault zone."""
    vault = Path(vault_root).expanduser().resolve()
    runtime = Path(runtime_root).expanduser().resolve()
    return write_zones(vault, runtime)


def write_pages(
    pages: tuple[GeneratedPage, ...],
    zones: dict[str, Path],
    *,
    confirmed: bool = False,
    force: bool = False,
    now: datetime | None = None,
) -> CommitResult:
    """Write rendered pages as one derived transaction into the generated zone."""
    if not pages:
        raise MutationError("invalid_op", "A generated-interface write requires at least one page.")
    root = Path(zones[GENERATED_ZONE])
    ops: list[FileOp] = []
    for page in pages:
        existing = root / page.filename
        if existing.is_file():
            if not confirmed:
                raise MutationError(
                    "needs_confirmation",
                    f"Overwriting an existing generated page requires confirmation: {page.filename}",
                )
            ops.append(
                FileOp(
                    "update",
                    Path(page.filename),
                    GENERATED_ZONE,
                    content=page.content,
                    expected=sha256_file(existing),
                )
            )
        else:
            ops.append(FileOp("create", Path(page.filename), GENERATED_ZONE, content=page.content))
    return commit(ChangeSet("regen_html", tuple(ops)), zones, force=force, now=now)
