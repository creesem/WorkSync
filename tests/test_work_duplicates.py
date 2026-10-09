"""Spec 7 ticket 02: detect and review duplicate action pairs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from worksync.work.duplicates import DUPLICATE_THRESHOLD, dismiss, pair_evidence, scan
from worksync.work.models import Action
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 6)
ACTIVE = "7. Task Notes/Active"


def _action(
    write_note: Callable[..., Path],
    vault: Path,
    name: str,
    title: str,
    *,
    status: str = "open",
    project: str | None = None,
    owners: tuple[str, ...] = (),
    body: str = "",
) -> Path:
    lines = ["---", "type: action", f"status: {status}"]
    if project:
        lines.append(f'project: "[[{project}]]"')
    if owners:
        lines.append("owners:")
        lines.extend(f'  - "[[{owner}]]"' for owner in owners)
    lines.append("---")
    text = "\n".join(lines) + f"\n# {title}\n\n{body}\n"
    return write_note(vault, f"{ACTIVE}/{name}.md", text)


def test_scan_detects_a_known_duplicate_pair(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about the invoice")

    manifest = scan(vault, tmp_path / "var", today=TODAY)

    assert len(manifest.proposals) == 1
    proposal = manifest.proposals[0]
    assert proposal.action == "merge"
    assert {proposal.source_path, proposal.target_path} == {f"{ACTIVE}/A.md", f"{ACTIVE}/B.md"}
    assert proposal.confidence >= DUPLICATE_THRESHOLD
    assert proposal.basis_sha256
    assert proposal.provenance
    assert proposal.status == "pending"


def test_scan_ignores_unrelated_actions(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _action(write_note, vault, "A", "Update the dashboard layout")
    _action(write_note, vault, "B", "Fix the login timeout bug")

    manifest = scan(vault, tmp_path / "var", today=TODAY)

    assert manifest.proposals == ()


def test_scan_excludes_completed_actions(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about the invoice", status="done")

    manifest = scan(vault, tmp_path / "var", today=TODAY)

    assert manifest.proposals == ()


def test_pair_evidence_bonuses_shared_project_and_owner() -> None:
    left = Action(path=f"{ACTIVE}/A.md", title="Call vendor invoice", status="open")
    plain = Action(path=f"{ACTIVE}/B.md", title="Vendor invoice followup", status="open")
    project = Action(
        path=f"{ACTIVE}/C.md",
        title="Call vendor invoice",
        status="open",
        project="[[Project - Alpha]]",
        owners=("[[Myles]]",),
    )
    both = Action(
        path=f"{ACTIVE}/D.md",
        title="Vendor invoice followup",
        status="open",
        project="[[Project - Alpha]]",
        owners=("[[Myles]]",),
    )

    weak = pair_evidence(left, plain)
    strong = pair_evidence(project, both)

    assert strong.score > weak.score
    assert strong.shared_project and strong.shared_owner
    assert not weak.shared_project and not weak.shared_owner
    assert strong.shared_terms


def test_scan_is_deterministic(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about the invoice")

    first = scan(vault, tmp_path / "var", today=TODAY)
    second = scan(vault, tmp_path / "var", today=TODAY)

    assert [p.id for p in first.proposals] == [p.id for p in second.proposals]


def test_dismissed_pair_is_retained_until_basis_changes(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    first = _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about the invoice")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id

    dismissed = dismiss(runtime, proposal_id, reviewer="Myles", reason="keep both")
    assert dismissed.proposals[0].status == "dismissed"
    assert dismissed.proposals[0].decided_at

    retained = scan(vault, runtime, today=TODAY)
    assert retained.proposals[0].status == "dismissed"

    first.write_text(first.read_text(encoding="utf-8") + "\nMore context.\n", encoding="utf-8")
    voided = scan(vault, runtime, today=TODAY)

    assert voided.proposals[0].status == "pending"
    assert voided.proposals[0].decision_history[-1].outcome == "dismissed"


def test_rescan_retires_an_undiscovered_pair(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    first = _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about the invoice")
    runtime = tmp_path / "var"
    scan(vault, runtime, today=TODAY)

    first.unlink()
    rescanned = scan(vault, runtime, today=TODAY)

    statuses = {proposal.status for proposal in rescanned.proposals}
    assert "obsolete" in statuses
    assert "pending" not in statuses


def test_discover_duplicates_sees_the_active_set(vault: Path, write_note: Callable[..., Path]) -> None:
    from worksync.work.duplicates import discover_duplicates

    _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about the invoice")
    _action(write_note, vault, "C", "Call vendor about the invoice", status="done")

    index = WorkIndex.from_vault(vault)
    proposals = discover_duplicates(vault, index)

    assert len(proposals) == 1
