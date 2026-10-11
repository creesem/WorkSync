"""Spec 9 ticket 07: the project update-review lane on the shared review queue."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.lifecycle.update_review import (
    UpdateReviewError,
    apply,
    discover_updates,
    dismiss,
    load_manifest,
    scan,
)
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 10)
PROJECT = "9. Project/Project - Eleos.md"
MEETING = "10. Meetings/2026-10-02 Weekly.md"
QUIET = "10. Meetings/2026-10-03 Quiet.md"


def _seed(write_note: Callable[..., Path], vault: Path) -> None:
    write_note(
        vault,
        PROJECT,
        '---\ntype: project\nstatus: active\nproject_id: eleos\nowners:\n  - "[[Myles]]"\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        MEETING,
        '---\ntype: meeting\nstatus: held\ndate: 2026-10-02\nproject: "[[Project - Eleos]]"\n---\n'
        "# Weekly\n\n- Waiting on the vendor for the quote.\n- Waiting on QA to test the new build.\n",
    )
    write_note(
        vault,
        QUIET,
        '---\ntype: meeting\nstatus: held\ndate: 2026-10-03\nwaiting_on: vendor\nproject: "[[Project - Eleos]]"\n---\n'
        "# Quiet\n\nNo blockers today.\n",
    )


def _vault_state(vault: Path) -> dict[str, bytes]:
    return {path.as_posix(): path.read_bytes() for path in vault.rglob("*.md")}


def test_discovery_uses_content_only_and_picks_one_best_fit_lane(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(write_note, vault)
    index = WorkIndex.from_vault(vault)

    proposals = discover_updates(vault, index, today=TODAY)

    lanes = [proposal.fields["lane"] for proposal in proposals]
    assert lanes.count("waiting") == 2
    # The QA statement mentions testing but waiting language wins the best fit.
    assert all(proposal.source_path != QUIET for proposal in proposals)
    assert all(proposal.target_path is None for proposal in proposals)


def test_scan_persists_a_stale_safe_manifest(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    manifest = scan(vault, runtime, today=TODAY)
    assert len(manifest.proposals) == 2
    assert load_manifest(runtime) == manifest


def test_apply_maps_evidence_to_an_exact_canonical_edit(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id

    result = apply(
        vault,
        runtime,
        reviewer="Myles",
        reason="Route the update",
        today=TODAY,
        ids=(proposal_id,),
        overrides={
            proposal_id: {
                "target": PROJECT,
                "field": "next_action",
                "value": "Follow up with the vendor",
                "rationale": "Weekly update names the vendor dependency",
            }
        },
    )

    assert result.committed is True
    assert "next_action: Follow up with the vendor" in (vault / PROJECT).read_text(encoding="utf-8")


def test_apply_uses_the_reviewer_edited_value(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id

    apply(
        vault,
        runtime,
        reviewer="Myles",
        reason="Route",
        today=TODAY,
        ids=(proposal_id,),
        overrides={
            proposal_id: {
                "target": PROJECT,
                "field": "next_action",
                "value": "Escalate to the account manager",
                "rationale": "Edited value",
            }
        },
    )

    text = (vault / PROJECT).read_text(encoding="utf-8")
    assert "next_action: Escalate to the account manager" in text
    assert "next_action: Follow up with the vendor" not in text


def test_invented_target_fails_closed_without_writing(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id
    before = _vault_state(vault)

    with pytest.raises(UpdateReviewError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="Myles",
            reason="Route",
            today=TODAY,
            ids=(proposal_id,),
            overrides={
                proposal_id: {"target": "9. Project/Ghost.md", "field": "next_action", "value": "x", "rationale": "r"}
            },
        )
    assert excinfo.value.code == "invalid_target"
    assert _vault_state(vault) == before


def test_stale_target_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id

    with pytest.raises(UpdateReviewError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="Myles",
            reason="Route",
            today=TODAY,
            ids=(proposal_id,),
            overrides={
                proposal_id: {
                    "target": PROJECT,
                    "field": "next_action",
                    "value": "x",
                    "rationale": "r",
                    "target_sha": "deadbeef",
                }
            },
        )
    assert excinfo.value.code == "stale_target"


def test_basis_change_voids_a_dismissed_decision(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id
    dismiss(runtime, proposal_id, reviewer="Myles", reason="Not actionable yet")

    # A body-only edit that keeps the statement changes nothing; a statement change voids it.
    assert scan(vault, runtime, today=TODAY).proposals[0].status == "dismissed"

    note = vault / MEETING
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "Waiting on the vendor for the quote.", "Waiting on finance for approval."
        ),
        encoding="utf-8",
    )
    voided = scan(vault, runtime, today=TODAY)
    target = next(proposal for proposal in voided.proposals if proposal.id == proposal_id)
    assert target.status == "pending"
    assert target.decision_history[-1].outcome == "dismissed"


def test_dismiss_requires_reviewer_and_reason(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id

    with pytest.raises(UpdateReviewError) as excinfo:
        dismiss(runtime, proposal_id, reviewer="", reason="x")
    assert excinfo.value.code == "missing_reviewer"


def test_apply_mid_batch_failure_rolls_back(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(write_note, vault)
    runtime = tmp_path / "var"
    manifest = scan(vault, runtime, today=TODAY)
    ids = tuple(proposal.id for proposal in manifest.proposals)
    overrides = {
        proposal_id: {"target": PROJECT, "field": "next_action", "value": "x", "rationale": "r"} for proposal_id in ids
    }
    before = _vault_state(vault)
    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if path.name == "Project - Eleos.md" and "next_action: x" in text:
            raise OSError("disk full")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Route", today=TODAY, ids=ids, overrides=overrides)

    assert excinfo.value.code == "rolled_back"
    assert _vault_state(vault) == before
    loaded = load_manifest(runtime)
    assert loaded is not None and all(proposal.status == "pending" for proposal in loaded.proposals)
