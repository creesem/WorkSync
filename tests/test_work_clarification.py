"""Spec 7 ticket 04: the clarification queue and its resolutions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.clarification import ClarificationError, apply, dismiss, load_manifest, scan

TODAY = date(2026, 10, 6)
ACTIVE = "7. Task Notes/Active"


def _note(write_note: Callable[..., Path], vault: Path, relative: str, text: str) -> Path:
    return write_note(vault, relative, text)


def _action(write_note: Callable[..., Path], vault: Path, name: str, title: str, frontmatter: str = "") -> Path:
    text = f"---\ntype: action\nstatus: open\n{frontmatter}---\n# {title}\n\nBody.\n"
    return write_note(vault, f"{ACTIVE}/{name}.md", text)


def _seed_entities(write_note: Callable[..., Path], vault: Path) -> None:
    _note(
        write_note,
        vault,
        "9. Project/Project - Alpha.md",
        "---\ntype: project\nstatus: active\n---\n# Project - Alpha\n",
    )
    _note(write_note, vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def _vault_state(vault: Path) -> dict[str, bytes]:
    return {path.as_posix(): path.read_bytes() for path in vault.rglob("*.md")}


def test_scan_reports_each_failing_predicate(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_entities(write_note, vault)
    _action(write_note, vault, "NoOwner", "Call the vendor")
    _action(write_note, vault, "BadPriority", "Ship the release", 'owners:\n  - "[[Myles]]"\npriority: high\n')
    _action(
        write_note, vault, "PastDue", "Send the report", 'owners:\n  - "[[Myles]]"\npriority: P2\ndue: 2026-10-01\n'
    )

    manifest = scan(vault, tmp_path / "var", today=TODAY)
    reasons = {Path(proposal.source_path).stem: proposal.provenance for proposal in manifest.proposals}

    assert any("missing project" in reason for reason in reasons["NoOwner"])
    assert any("missing owner" in reason for reason in reasons["NoOwner"])
    assert any("invalid priority" in reason for reason in reasons["BadPriority"])
    assert any("past due" in reason for reason in reasons["PastDue"])


def test_scan_excludes_a_complete_action(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_entities(write_note, vault)
    _action(
        write_note,
        vault,
        "Healthy",
        "Call the vendor",
        'owners:\n  - "[[Myles]]"\npriority: P2\nproject: "[[Project - Alpha]]"\n',
    )

    manifest = scan(vault, tmp_path / "var", today=TODAY)

    assert manifest.proposals == ()


def test_scan_includes_top_matches_for_context(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_entities(write_note, vault)
    _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about invoice")

    manifest = scan(vault, tmp_path / "var", today=TODAY)
    item = next(p for p in manifest.proposals if Path(p.source_path).stem == "A")

    assert item.fields["matches"]


def test_apply_keep_records_the_review(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_entities(write_note, vault)
    note = _action(write_note, vault, "NoOwner", "Call the vendor", "revision: 1\n")
    runtime = tmp_path / "var"
    scan(vault, runtime, today=TODAY)

    apply(vault, runtime, reviewer="Myles", reason="Reviewed", today=TODAY)

    text = note.read_text(encoding="utf-8")
    assert "revision: 2" in text
    assert "updated_by: Myles" in text
    assert "last_action: Reviewed" in text
    loaded = load_manifest(runtime)
    assert loaded is not None and loaded.proposals[0].status == "applied"


def test_apply_archive_retires_the_item(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_entities(write_note, vault)
    note = _action(write_note, vault, "NoOwner", "Call the vendor")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id

    apply(
        vault,
        runtime,
        reviewer="Myles",
        reason="No longer work",
        confirmed=True,
        today=TODAY,
        overrides={proposal_id: {"resolution": "archive"}},
    )

    assert "type: redirect" in note.read_text(encoding="utf-8")


def test_apply_reclassify_waiting_on(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_entities(write_note, vault)
    note = _action(write_note, vault, "NoOwner", "Call the vendor")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id

    apply(
        vault,
        runtime,
        reviewer="Myles",
        reason="Waiting on vendor",
        today=TODAY,
        overrides={
            proposal_id: {
                "resolution": "reclassify",
                "project": "Project - Alpha",
                "owner": "Myles",
                "dependency": "Vendor response",
                "next_review": "2026-11-01",
            }
        },
    )

    text = note.read_text(encoding="utf-8")
    assert "status: waiting" in text
    assert "waiting_on: Vendor response" in text
    assert "due: 2026-11-01" in text
    assert "[[Myles]]" in text


def test_apply_reclassify_fails_closed_without_required_fields(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed_entities(write_note, vault)
    _action(write_note, vault, "NoOwner", "Call the vendor")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id

    with pytest.raises(ClarificationError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="Myles",
            reason="Waiting",
            today=TODAY,
            overrides={proposal_id: {"resolution": "reclassify"}},
        )
    assert excinfo.value.code == "missing_reclassify_fields"


def test_apply_merge_consolidates_into_the_target(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed_entities(write_note, vault)
    item = _action(write_note, vault, "NoOwner", "Call the vendor")
    target = _action(write_note, vault, "Target", "Call the vendor invoice")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id
    target_relative = target.relative_to(vault).as_posix()

    apply(
        vault,
        runtime,
        reviewer="Myles",
        reason="Duplicate",
        confirmed=True,
        today=TODAY,
        ids=(proposal_id,),
        overrides={proposal_id: {"resolution": "merge", "canonical": target_relative}},
    )

    assert "## Merged context" in target.read_text(encoding="utf-8")
    assert "type: redirect" in item.read_text(encoding="utf-8")


def test_body_only_edit_keeps_a_decision_but_material_change_voids_it(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed_entities(write_note, vault)
    note = _action(write_note, vault, "NoOwner", "Call the vendor")
    runtime = tmp_path / "var"
    proposal_id = scan(vault, runtime, today=TODAY).proposals[0].id
    dismiss(runtime, proposal_id, reviewer="Myles", reason="looks fine")

    note.write_text(note.read_text(encoding="utf-8") + "\nmore body only\n", encoding="utf-8")
    assert scan(vault, runtime, today=TODAY).proposals[0].status == "dismissed"

    note.write_text(
        note.read_text(encoding="utf-8").replace("status: open", "status: open\npriority: P1"), encoding="utf-8"
    )
    voided = scan(vault, runtime, today=TODAY)
    assert voided.proposals[0].status == "pending"
    assert voided.proposals[0].decision_history[-1].outcome == "dismissed"


def test_apply_mid_batch_failure_rolls_back(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed_entities(write_note, vault)
    _action(write_note, vault, "A", "Call the vendor")
    _action(write_note, vault, "B", "Email the vendor")
    runtime = tmp_path / "var"
    scan(vault, runtime, today=TODAY)
    before = _vault_state(vault)
    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if path.name == "B.md":
            raise OSError("disk full")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Review", today=TODAY)

    assert excinfo.value.code == "rolled_back"
    assert _vault_state(vault) == before
    loaded = load_manifest(runtime)
    assert loaded is not None and all(proposal.status == "pending" for proposal in loaded.proposals)
