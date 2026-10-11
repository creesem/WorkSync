"""The controlled project update-review lane on the shared review queue.

Classified meeting evidence (testing, waiting, communication) becomes a reviewable
proposal; a reviewer maps it to an exact canonical record, field, and proposed value
with a rationale before acceptance. Routing evidence is extracted from note **content
only** — never frontmatter — and a statement matching several lanes picks one best-fit
lane with waiting/communication language ahead of incidental testing terms. An invented
or stale target id is rejected before any write; the queue owns the stale-safe manifest,
merge-on-rescan, dismissal, and the single batch commit.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import edit_frontmatter_fields, parse_note
from worksync.safety.files import sha256_file
from worksync.safety.models import FileOp
from worksync.work.queue import (
    ApplyResult,
    Manifest,
    Proposal,
    QueueError,
    QueueStore,
    apply_proposals,
    content_scan_token,
    scan_manifest,
)
from worksync.work.repository import WorkIndex
from worksync.work.schema import detect_type

MANIFEST_REL = Path("project-update") / "manifest.json"
ROUTABLE_FIELDS = frozenset(
    {
        "status",
        "waiting_on",
        "next_action",
        "last_checked",
        "manager_attention",
        "completed",
        "due",
        "project",
        "priority",
    }
)
WAITING_PATTERNS = ("waiting on", "waiting for", "blocked by", "awaiting", "dependent on")
COMMUNICATION_PATTERNS = ("need to tell", "communicate", "email ", "send ", "inform ")
TESTING_PATTERNS = ("ready for testing", "for testing", "retest", "test the", "qa ")


class UpdateReviewError(QueueError):
    """Raised when a project update-review action cannot be applied."""


def discover_updates(vault: str | Path, index: WorkIndex, *, today: date) -> tuple[Proposal, ...]:
    """Return one proposal per content-only routing statement in a meeting note."""
    vault_root = Path(vault).expanduser().resolve()
    proposals: list[Proposal] = []
    for meeting in index.list_type("meeting"):
        target = vault_root / meeting.path
        if not target.is_file():
            continue
        record = parse_note(target, vault_root)
        source_sha = sha256_file(target)
        for lineno, raw in enumerate(_body_lines(record.content), start=1):
            statement = _statement(raw)
            lane = _classify(statement)
            if lane is None:
                continue
            proposals.append(
                Proposal(
                    id=f"{meeting.path}#{lineno}",
                    action="route",
                    source_path=meeting.path,
                    source_sha256=source_sha,
                    basis_sha256=_basis(statement),
                    fields={"lane": lane, "statement": statement},
                    confidence=0.5,
                    provenance=(f"{meeting.path}:{lineno}",),
                )
            )
    return tuple(sorted(proposals, key=lambda proposal: (proposal.source_path, _line_number(proposal.id))))


def scan(vault: str | Path, runtime: str | Path, *, today: date | None = None, dry_run: bool = False) -> Manifest:
    """Queue update-routing proposals and persist the merged manifest with a precondition."""
    when = today or date.today()
    index = WorkIndex.from_vault(vault)
    fresh = discover_updates(vault, index, today=when)
    return scan_manifest(QueueStore(runtime, MANIFEST_REL), fresh, token=_scan_token(vault, index), dry_run=dry_run)


def dismiss(runtime: str | Path, proposal_id: str, *, reviewer: str, reason: str, dry_run: bool = False) -> Manifest:
    """Mark one update proposal dismissed with a named reviewer and reason."""
    return QueueStore(runtime, MANIFEST_REL).dismiss(
        proposal_id,
        reviewer=reviewer,
        reason=reason,
        error=UpdateReviewError,
        no_manifest="No project-update manifest; run 'worksync project update scan' first.",
        dry_run=dry_run,
    )


def load_manifest(runtime: str | Path) -> Manifest | None:
    """Load the project-update manifest, or ``None`` when absent."""
    return QueueStore(runtime, MANIFEST_REL).load()


def manifest_path(runtime: str | Path) -> Path:
    """Return the project-update manifest path under the staging zone."""
    return QueueStore(runtime, MANIFEST_REL).path()


def apply(
    vault: str | Path,
    runtime: str | Path,
    *,
    reviewer: str,
    reason: str,
    ids: tuple[str, ...] | None = None,
    overrides: dict[str, dict] | None = None,
    confirmed: bool = False,
    today: date | None = None,
    dry_run: bool = False,
) -> ApplyResult:
    """Apply the selected pending updates as one transaction through the gateway."""
    vault_root = Path(vault).expanduser().resolve()

    def build_ops(proposal: Proposal, override: dict) -> tuple[list[FileOp], str]:
        return _build_ops(vault_root, proposal, override)

    return apply_proposals(
        QueueStore(runtime, MANIFEST_REL),
        vault_root=vault_root,
        reviewer=reviewer,
        reason=reason,
        ids=ids,
        overrides=overrides,
        confirmed=confirmed,
        dry_run=dry_run,
        error=UpdateReviewError,
        no_manifest="No project-update manifest; run 'worksync project update scan' first.",
        empty_selection="No pending updates were selected.",
        build_ops=build_ops,
        verb=lambda _resolutions: "route_update",
    )


def _build_ops(vault_root: Path, proposal: Proposal, override: dict) -> tuple[list[FileOp], str]:
    target = str(override.get("target") or "").strip()
    field = str(override.get("field") or "").strip()
    value = str(override.get("value") or "").strip()
    rationale = str(override.get("rationale") or "").strip()
    if not (target and field and value and rationale):
        raise UpdateReviewError(
            "missing_mapping",
            "A routing requires a target record, field, proposed value, and rationale.",
            affected=(proposal.id,),
        )
    if field not in ROUTABLE_FIELDS:
        raise UpdateReviewError("unknown_field", f"Field is not routable: {field}", affected=(field,))

    try:
        resolved = ensure_under(vault_root, vault_root / target)
    except PathSafetyError as exc:
        raise UpdateReviewError("invalid_target", str(exc), affected=(target,)) from exc
    if not resolved.is_file():
        raise UpdateReviewError("invalid_target", f"Target record not found: {target}", affected=(target,))

    relative = resolved.resolve().relative_to(vault_root).as_posix()
    record = parse_note(resolved, vault_root)
    if detect_type(record.frontmatter.get("type")) is None:
        raise UpdateReviewError("invalid_target", f"Target is not a work record: {target}", affected=(target,))
    target_sha = str(override.get("target_sha") or "").strip()
    if target_sha and target_sha != record.content_hash:
        raise UpdateReviewError("stale_target", f"Target changed since it was read: {relative}", affected=(relative,))

    content = edit_frontmatter_fields(record.content, set_fields={field: value})
    return [FileOp("update", Path(relative), "trusted", content=content, expected=record.content_hash)], "route"


def _body_lines(content: str) -> list[str]:
    """Return the note body lines after any closed frontmatter block (CRLF-tolerant)."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return lines
    close = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if close is None:
        return lines
    return lines[close + 1 :]


def _line_number(proposal_id: str) -> int:
    _, _, suffix = proposal_id.rpartition("#")
    return int(suffix) if suffix.isdigit() else 0


def _statement(raw: str) -> str:
    text = raw.strip()
    while text[:1] in {"-", "*", "#"}:
        text = text[1:].strip()
    return text


def _classify(statement: str) -> str | None:
    text = statement.casefold()
    if not text:
        return None
    if any(pattern in text for pattern in WAITING_PATTERNS):
        return "waiting"
    if any(pattern in text for pattern in COMMUNICATION_PATTERNS):
        return "communication"
    if any(pattern in text for pattern in TESTING_PATTERNS):
        return "testing"
    return None


def _basis(statement: str) -> str:
    return hashlib.sha256(" ".join(statement.split()).casefold().encode("utf-8")).hexdigest()


def _scan_token(vault: str | Path, index: WorkIndex) -> str:
    return content_scan_token(vault, index.list_type("meeting"))
