"""Plan and apply a person merge as one gated transaction.

A merge combines a canonical person note with a duplicate: nonconflicting fields are
combined automatically, every conflicting field requires an explicit reviewer decision, the
duplicate becomes an in-place redirect tombstone, every confidently parsed wiki link to the
duplicate is rewritten to the canonical title, and a durable old-id redirect is registered.
The whole thing is one :func:`worksync.safety.gateway.commit` transaction — the merge, the
reference rewrites, the redirect registry, and the queue manifest update commit or roll back
together. A changed source or identity basis fails closed. Ordinary prose is never rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from worksync.core.paths import PathSafetyError, ensure_under
from worksync.inventory.parse import WIKILINK_RE, edit_frontmatter_fields, parse_note, scan_vault
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, FileOp
from worksync.safety.zones import write_zones
from worksync.work.consolidate import append_update_entry, merged_content, redirect_content
from worksync.work.identity import MANIFEST_REL, IdentityError, person_basis
from worksync.work.models import EntityBase, EntityType
from worksync.work.queue import ApplyResult, QueueStore, now, op_dict
from worksync.work.redirects import (
    REDIRECTS_REL,
    load_redirects,
    redirect_registry_path,
    render_redirects,
    resolve_person,
)
from worksync.work.schema import entity_from_record, normalize_target

MERGE_FIELDS = ("role", "team", "manager", "email", "status")
DECISIONS = ("left", "right")


@dataclass(frozen=True)
class FieldPlan:
    """One mergeable field's two sides and whether they conflict."""

    field: str
    left: str | None
    right: str | None
    conflict: bool


@dataclass(frozen=True)
class ReferencePlan:
    """One note that references the duplicate and will be rewritten."""

    path: str
    target: str


@dataclass(frozen=True)
class MergePlan:
    """The read-only plan for merging a duplicate into a canonical person."""

    canonical_path: str
    duplicate_path: str
    canonical_title: str
    duplicate_title: str
    fields: tuple[FieldPlan, ...]
    references: tuple[ReferencePlan, ...]
    basis_sha256: str

    @property
    def conflicts(self) -> tuple[FieldPlan, ...]:
        """Return the fields that require an explicit reviewer decision."""
        return tuple(field for field in self.fields if field.conflict)


def plan_merge(vault: str | Path, canonical: EntityBase, duplicate: EntityBase) -> MergePlan:
    """Return the field, reference, and basis plan for one person pair; writes nothing."""
    vault_root = Path(vault).expanduser().resolve()
    fields = []
    for name in MERGE_FIELDS:
        left, right = _value(canonical, name), _value(duplicate, name)
        conflict = bool(left) and bool(right) and left != right
        fields.append(FieldPlan(name, left, right, conflict))
    references = _find_references(vault_root, duplicate, {canonical.path, duplicate.path})
    return MergePlan(
        canonical_path=canonical.path,
        duplicate_path=duplicate.path,
        canonical_title=canonical.title,
        duplicate_title=duplicate.title,
        fields=tuple(fields),
        references=references,
        basis_sha256=person_basis(canonical, duplicate),
    )


def apply_merge(
    vault: str | Path,
    runtime: str | Path,
    *,
    proposal_id: str,
    reviewer: str,
    reason: str,
    field_decisions: dict[str, str] | None = None,
    confirmed: bool = False,
    dry_run: bool = False,
) -> ApplyResult:
    """Apply one reviewed person merge as a single transaction, or restore the prior state."""
    if not str(reviewer).strip():
        raise IdentityError("missing_reviewer", "A merge requires a named reviewer.")
    if not str(reason).strip():
        raise IdentityError("missing_reason", "A merge requires a human-readable reason.")
    vault_root = Path(vault).expanduser().resolve()
    store = QueueStore(runtime, MANIFEST_REL)
    loaded = store.load_with_hash()
    if loaded is None:
        raise IdentityError("no_manifest", "No identity manifest; run 'worksync identity scan' first.")
    manifest, manifest_hash = loaded
    proposal = next((item for item in manifest.proposals if item.id == proposal_id), None)
    if proposal is None:
        raise IdentityError("unknown_proposal", f"No proposal with id: {proposal_id}", affected=(proposal_id,))
    if proposal.status != "pending":
        raise IdentityError("not_pending", f"Proposal is not pending: {proposal_id}", affected=(proposal_id,))
    if not proposal.target_path or not proposal.source_path:
        raise IdentityError("invalid_proposal", "Merge proposal is missing a side.", affected=(proposal_id,))

    canonical_record, canonical = _load_person(vault_root, proposal.target_path, proposal.target_sha256, proposal_id)
    duplicate_record, duplicate = _load_person(vault_root, proposal.source_path, proposal.source_sha256, proposal_id)

    plan = plan_merge(vault_root, canonical, duplicate)
    if plan.basis_sha256 != proposal.basis_sha256:
        raise IdentityError(
            "stale_basis", f"The identity basis changed since review: {proposal_id}", affected=(proposal_id,)
        )

    decisions = {str(key): str(value).strip().casefold() for key, value in (field_decisions or {}).items()}
    unresolved = [field.field for field in plan.conflicts if decisions.get(field.field) not in DECISIONS]
    if unresolved:
        raise IdentityError(
            "unresolved_conflict",
            "Every conflicting field needs a decision: " + ", ".join(unresolved),
            affected=tuple(unresolved),
        )

    when = date.today().isoformat()
    ops: list[FileOp] = [
        FileOp(
            "update",
            Path(canonical_record.path),
            "trusted",
            content=_merged_canonical(
                plan, canonical_record, duplicate_record, decisions, when=when, reviewer=reviewer, reason=reason
            ),
            expected=canonical_record.content_hash,
        ),
        FileOp(
            "update",
            Path(duplicate_record.path),
            "trusted",
            content=redirect_content(
                duplicate_record.content,
                duplicate_record.frontmatter,
                canonical.title,
                when=when,
                reviewer=reviewer,
                reason=reason,
            ),
            expected=duplicate_record.content_hash,
        ),
    ]
    ops.extend(_reference_ops(vault_root, plan, canonical.title, duplicate))
    registry_op = _redirect_op(runtime, canonical, duplicate)
    if registry_op is not None:
        ops.append(registry_op)

    updated = tuple(
        replace(item, status="applied", reviewer=reviewer, reason=reason, decided_at=now())
        if item.id == proposal_id
        else item
        for item in manifest.proposals
    )
    ops.append(store.manifest_op(manifest.with_proposals(updated), expected=manifest_hash))

    if dry_run:
        return ApplyResult(
            committed=False, journal=Path(), changes=tuple(op_dict(op) for op in ops), applied=(proposal_id,)
        )

    changeset = ChangeSet("merge", tuple(ops), reviewer=str(reviewer).strip(), reason=str(reason).strip())
    result = commit(changeset, write_zones(vault_root, runtime), confirmed=confirmed)
    return ApplyResult(
        committed=result.committed, journal=result.journal, changes=result.changes, applied=(proposal_id,)
    )


def _value(entity: EntityBase, field: str) -> str | None:
    value = getattr(entity, field, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _find_references(vault_root: Path, duplicate: EntityBase, exclude: set[str]) -> tuple[ReferencePlan, ...]:
    keys = _duplicate_keys(duplicate)
    references: list[ReferencePlan] = []
    for record in scan_vault(vault_root):
        if record.path in exclude:
            continue
        for target, _alias in record.links:
            if normalize_target(target) in keys:
                references.append(ReferencePlan(record.path, target))
                break
    return tuple(sorted(references, key=lambda reference: reference.path))


def _duplicate_keys(entity: EntityBase) -> set[str]:
    keys = {normalize_target(Path(entity.path).stem), normalize_target(entity.title)}
    keys |= {normalize_target(alias) for alias in entity.aliases}
    return {key for key in keys if key}


def _merged_canonical(
    plan: MergePlan,
    canonical_record,
    duplicate_record,
    decisions: dict[str, str],
    *,
    when: str,
    reviewer: str,
    reason: str,
) -> str:
    set_fields: dict[str, str] = {}
    for field in plan.fields:
        if field.conflict:
            value = field.left if decisions[field.field] == "left" else field.right
        else:
            value = field.left or field.right
        if value is not None:
            set_fields[field.field] = value
    content = edit_frontmatter_fields(canonical_record.content, set_fields=set_fields)
    content = merged_content(content, duplicate_record.content)
    return append_update_entry(content, when=when, reviewer=reviewer, reason=reason)


def _reference_ops(vault_root: Path, plan: MergePlan, canonical_title: str, duplicate: EntityBase) -> list[FileOp]:
    keys = _duplicate_keys(duplicate)
    ops: list[FileOp] = []
    for reference in plan.references:
        record = parse_note(vault_root / reference.path, vault_root)
        rewritten = _rewrite_links(record.content, keys, canonical_title)
        if rewritten != record.content:
            ops.append(
                FileOp(
                    "update",
                    Path(reference.path),
                    "trusted",
                    content=rewritten,
                    expected=record.content_hash,
                )
            )
    return ops


def _rewrite_links(content: str, keys: set[str], canonical_title: str) -> str:
    def replace_link(match) -> str:
        raw = match.group(1)
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if normalize_target(target) in keys:
            suffix = raw[len(target) :] if raw.startswith(target) else ""
            return f"[[{canonical_title}{suffix}]]"
        return match.group(0)

    return WIKILINK_RE.sub(replace_link, content)


def _redirect_op(runtime: str | Path, canonical: EntityBase, duplicate: EntityBase) -> FileOp | None:
    retired_id = getattr(duplicate, "person_id", None)
    canonical_id = getattr(canonical, "person_id", None)
    if not retired_id or not canonical_id:
        return None
    redirects = load_redirects(runtime)
    redirects[retired_id] = resolve_person(canonical_id, redirects)
    content = render_redirects(redirects)
    path = redirect_registry_path(runtime)
    if path.is_file():
        return FileOp("update", REDIRECTS_REL, "runtime", content=content, expected=sha256_file(path))
    return FileOp("create", REDIRECTS_REL, "runtime", content=content)


def _load_person(vault_root: Path, relative: str, expected: str | None, proposal_id: str):
    if not relative:
        raise IdentityError("missing_target", f"Proposal is missing a path: {proposal_id}", affected=(proposal_id,))
    try:
        target = ensure_under(vault_root, vault_root / relative)
    except PathSafetyError as exc:
        raise IdentityError("invalid_source", str(exc), affected=(relative,)) from exc
    if not target.is_file():
        raise IdentityError("missing_source", f"Note not found: {relative}", affected=(relative,))
    current = sha256_file(target)
    if expected and current != expected:
        raise IdentityError("stale_source", f"Note changed since the scan: {relative}", affected=(relative,))
    record = parse_note(target, vault_root)
    entity = entity_from_record(record)
    if entity is None or entity.entity_type is not EntityType.PERSON:
        raise IdentityError("not_person", f"Not a person note: {relative}", affected=(relative,))
    return record, entity
