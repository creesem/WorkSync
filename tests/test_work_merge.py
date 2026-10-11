"""WP-04: plan and apply a person merge as one transaction."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from worksync.inventory.parse import parse_note
from worksync.safety.models import MutationError
from worksync.work.identity import IdentityError, load_manifest, scan
from worksync.work.merge import apply_merge, plan_merge
from worksync.work.redirects import load_redirects
from worksync.work.repository import WorkIndex
from worksync.work.schema import entity_from_record

PEOPLE = "People"


def _person(
    write_note: Callable[..., Path],
    vault: Path,
    name: str,
    title: str,
    *,
    person_id: str,
    role: str | None = None,
    team: str | None = None,
    email: str | None = None,
    status: str = "active",
) -> Path:
    lines = ["---", "type: person", f"status: {status}", f"person_id: {person_id}"]
    if role:
        lines.append(f"role: {role}")
    if team:
        lines.append(f"team: {team}")
    if email:
        lines.append(f"email: {email}")
    lines.append("---")
    return write_note(vault, f"{PEOPLE}/{name}.md", "\n".join(lines) + f"\n# {title}\n")


def _entity(vault: Path, relative: str):
    return entity_from_record(parse_note(vault / relative, vault))


def _seed_pair(write_note: Callable[..., Path], vault: Path) -> None:
    # The canonical note carries strictly more metadata, so the established-record heuristic
    # (more metadata wins) makes it the survivor deterministically.
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", role="PM", team="IT")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b", email="carlos@example.com")


def test_plan_merge_combines_nonconflicting_fields(vault: Path, write_note: Callable[..., Path]) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", role="PM")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b", team="IT")
    canonical = _entity(vault, f"{PEOPLE}/Carlos Barnes.md")
    duplicate = _entity(vault, f"{PEOPLE}/Carlos B.md")

    plan = plan_merge(vault, canonical, duplicate)

    assert plan.conflicts == ()
    fields = {field.field: field for field in plan.fields}
    assert fields["role"].left == "PM" and fields["role"].right is None
    assert fields["team"].left is None and fields["team"].right == "IT"


def test_plan_merge_flags_conflicting_fields(vault: Path, write_note: Callable[..., Path]) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", role="PM")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b", role="Engineer")
    canonical = _entity(vault, f"{PEOPLE}/Carlos Barnes.md")
    duplicate = _entity(vault, f"{PEOPLE}/Carlos B.md")

    plan = plan_merge(vault, canonical, duplicate)

    assert [field.field for field in plan.conflicts] == ["role"]


def test_plan_merge_enumerates_references(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed_pair(write_note, vault)
    write_note(
        vault,
        "10. Meetings/M.md",
        '---\ntype: meeting\nstatus: held\ndate: 2026-01-01\nattendees:\n  - "[[Carlos B]]"\n---\n# M\n',
    )
    canonical = _entity(vault, f"{PEOPLE}/Carlos Barnes.md")
    duplicate = _entity(vault, f"{PEOPLE}/Carlos B.md")

    plan = plan_merge(vault, canonical, duplicate)

    assert [reference.path for reference in plan.references] == ["10. Meetings/M.md"]


def test_apply_merge_requires_conflict_decisions(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", role="PM")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b", role="Engineer")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime).proposals[0].id

    with pytest.raises(IdentityError) as excinfo:
        apply_merge(vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="same person", confirmed=True)

    assert excinfo.value.code == "unresolved_conflict"


def test_apply_merge_merges_rewrites_and_registers_redirect(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed_pair(write_note, vault)
    write_note(
        vault,
        "10. Meetings/M.md",
        '---\ntype: meeting\nstatus: held\ndate: 2026-01-01\nattendees:\n  - "[[Carlos B]]"\n---\n# M\n',
    )
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime).proposals[0].id

    result = apply_merge(
        vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="same person", confirmed=True
    )

    assert result.committed is True
    canonical = (vault / f"{PEOPLE}/Carlos Barnes.md").read_text(encoding="utf-8")
    assert "type: redirect" not in canonical
    assert "email: carlos@example.com" in canonical
    duplicate = (vault / f"{PEOPLE}/Carlos B.md").read_text(encoding="utf-8")
    assert "type: redirect" in duplicate
    meeting = (vault / "10. Meetings/M.md").read_text(encoding="utf-8")
    assert "[[Carlos Barnes]]" in meeting and "[[Carlos B]]" not in meeting
    assert load_redirects(runtime) == {"carlos-b": "carlos-barnes"}
    assert load_manifest(runtime).proposals[0].status == "applied"


def test_apply_merge_requires_confirmation(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_pair(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime).proposals[0].id

    with pytest.raises(MutationError) as excinfo:
        apply_merge(vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="same person")

    assert excinfo.value.code == "needs_confirmation"


def test_apply_merge_fails_closed_on_a_stale_source(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed_pair(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime).proposals[0].id
    duplicate = vault / f"{PEOPLE}/Carlos B.md"
    duplicate.write_text(duplicate.read_text(encoding="utf-8") + "\nEdited after scan.\n", encoding="utf-8")

    with pytest.raises(IdentityError) as excinfo:
        apply_merge(vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="same person", confirmed=True)

    assert excinfo.value.code == "stale_source"


def test_apply_merge_dry_run_writes_nothing(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_pair(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime).proposals[0].id
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}

    result = apply_merge(
        vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="same person", confirmed=True, dry_run=True
    )

    assert result.committed is False
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before
    assert load_redirects(runtime) == {}


def test_plan_merge_workindex_parameter_is_unused_but_index_matches(
    vault: Path, write_note: Callable[..., Path]
) -> None:
    _seed_pair(write_note, vault)
    canonical = _entity(vault, f"{PEOPLE}/Carlos Barnes.md")
    duplicate = _entity(vault, f"{PEOPLE}/Carlos B.md")
    assert isinstance(WorkIndex.from_vault(vault), WorkIndex)
    assert plan_merge(vault, canonical, duplicate).basis_sha256
