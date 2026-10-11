"""WP-02: detect and review duplicate person pairs on the shared work queue."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.work.identity import (
    DUPLICATE_THRESHOLD,
    dismiss,
    person_pair_evidence,
    scan,
)
from worksync.work.models import Person
from worksync.work.repository import WorkIndex

PEOPLE = "People"


def _person(
    write_note: Callable[..., Path],
    vault: Path,
    name: str,
    title: str,
    *,
    person_id: str | None = None,
    team: str | None = None,
    status: str = "active",
    body: str = "",
) -> Path:
    lines = ["---", "type: person", f"status: {status}"]
    if person_id:
        lines.append(f"person_id: {person_id}")
    if team:
        lines.append(f"team: {team}")
    lines.append("---")
    text = "\n".join(lines) + f"\n# {title}\n\n{body}\n"
    return write_note(vault, f"{PEOPLE}/{name}.md", text)


def test_scan_detects_a_duplicate_person_pair(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b")

    manifest = scan(vault, tmp_path / "var")

    assert len(manifest.proposals) == 1
    proposal = manifest.proposals[0]
    assert proposal.action == "merge"
    assert {proposal.source_path, proposal.target_path} == {f"{PEOPLE}/Carlos Barnes.md", f"{PEOPLE}/Carlos B.md"}
    assert proposal.id.startswith("person-dup:")
    assert proposal.basis_sha256
    assert proposal.provenance
    assert proposal.status == "pending"
    assert proposal.confidence >= DUPLICATE_THRESHOLD


def test_scan_ignores_distinct_persons(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes")
    _person(write_note, vault, "Tracy Waite", "Tracy Waite", person_id="tracy-waite")

    assert scan(vault, tmp_path / "var").proposals == ()


def test_scan_excludes_inactive_persons(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b", status="inactive")

    assert scan(vault, tmp_path / "var").proposals == ()


def test_proposal_id_is_stable_across_rescans(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b")

    first = scan(vault, tmp_path / "var").proposals[0].id
    second = scan(vault, tmp_path / "var").proposals[0].id

    assert first == second


def test_person_pair_evidence_explains_signals() -> None:
    left = Person(path=f"{PEOPLE}/A.md", title="Carlos Barnes", status="active", team="Information Technology")
    exact = Person(path=f"{PEOPLE}/B.md", title="Carlos Barnes", status="active", team="Information Technology")
    other = Person(path=f"{PEOPLE}/C.md", title="Tracy Waite", status="active")

    strong = person_pair_evidence(left, exact)
    weak = person_pair_evidence(left, other)

    assert strong.score > weak.score
    assert strong.exact_name and strong.shared_team
    assert "exact name match" in strong.reasons
    assert not weak.exact_name


def test_body_edit_does_not_void_a_dismissal(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    first = _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime).proposals[0].id

    dismissed = dismiss(runtime, proposal_id, reviewer="Myles", reason="same person; merge later")
    assert dismissed.proposals[0].status == "dismissed"
    assert dismissed.proposals[0].decided_at

    first.write_text(first.read_text(encoding="utf-8") + "\nSome unrelated body note.\n", encoding="utf-8")
    retained = scan(vault, runtime)

    assert retained.proposals[0].status == "dismissed"


def test_material_identity_change_reopens_a_dismissal(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _person(
        write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", team="Information Technology"
    )
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime).proposals[0].id
    dismiss(runtime, proposal_id, reviewer="Myles", reason="same person")

    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", team="Finance")
    reopened = scan(vault, runtime)

    assert reopened.proposals[0].status == "pending"
    assert reopened.proposals[0].decision_history[-1].outcome == "dismissed"


def test_rescan_retires_an_undiscovered_pair(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    first = _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b")
    runtime = tmp_path / "var"
    scan(vault, runtime)

    first.unlink()
    rescanned = scan(vault, runtime)

    statuses = {proposal.status for proposal in rescanned.proposals}
    assert "obsolete" in statuses
    assert "pending" not in statuses


def test_discover_sees_only_the_active_person_set(vault: Path, write_note: Callable[..., Path]) -> None:
    from worksync.work.identity import discover_duplicates

    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b")
    _person(write_note, vault, "Carlos C", "Carlos Barnes", person_id="carlos-c", status="inactive")

    proposals = discover_duplicates(vault, WorkIndex.from_vault(vault))

    assert len(proposals) == 1
