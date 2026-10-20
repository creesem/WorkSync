"""Ticket 12: typed text becomes a pending capture proposal in the review queue."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.safety.files import sha256_bytes
from worksync.work.capture import CAPTURE_REL, capture_text
from worksync.work.queue import Manifest, QueueStore

TEXT = "Follow up with Dana about the Alpha handoff."
NOW = "2026-02-01T09:00:00+00:00"


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_capture_text_creates_one_deterministic_pending_proposal(tmp_path: Path) -> None:
    manifest = capture_text(tmp_path / "var", TEXT, now=NOW)

    assert isinstance(manifest, Manifest)
    assert manifest.updated_at == NOW
    assert len(manifest.proposals) == 1
    proposal = manifest.proposals[0]
    digest = sha256_bytes(TEXT.encode("utf-8"))
    assert proposal.id == digest[:12]
    assert proposal.action == "capture"
    assert proposal.source_path == ""
    assert proposal.source_sha256 == digest
    assert proposal.fields == {"text": TEXT}
    assert proposal.provenance == ("capture",)
    assert proposal.status == "pending"


def test_repeating_the_same_capture_does_not_duplicate_the_proposal(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    first = capture_text(runtime, TEXT, now=NOW)
    second = capture_text(runtime, TEXT, now="2026-02-01T10:00:00+00:00")

    assert len(second.proposals) == 1
    assert second.proposals[0].id == first.proposals[0].id
    assert second.updated_at == "2026-02-01T10:00:00+00:00"
    assert QueueStore(runtime, CAPTURE_REL).load() == second


def test_a_second_distinct_capture_keeps_the_first_pending(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    first = capture_text(runtime, TEXT, now=NOW)
    second_text = "Book the Alpha retro room."
    second = capture_text(runtime, second_text, now="2026-02-01T10:00:00+00:00")

    assert len(second.proposals) == 2
    statuses = {proposal.source_sha256: proposal.status for proposal in second.proposals}
    assert statuses[sha256_bytes(TEXT.encode("utf-8"))] == "pending"
    assert statuses[sha256_bytes(second_text.encode("utf-8"))] == "pending"
    assert first.proposals[0].id in {proposal.id for proposal in QueueStore(runtime, CAPTURE_REL).load().proposals}


def test_capture_manifest_lives_under_the_staging_zone(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    capture_text(runtime, TEXT, now=NOW)

    assert Path("capture") / "manifest.json" == CAPTURE_REL
    assert (runtime.resolve() / "staging" / "capture" / "manifest.json").is_file()


def test_capture_never_writes_to_the_vault(tmp_path: Path, vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "Actions/A1.md", "---\ntype: action\nstatus: open\n---\n# Action One\n")
    before = _snapshot(vault)

    capture_text(tmp_path / "var", TEXT, now=NOW)

    assert _snapshot(vault) == before


def test_recapturing_the_same_text_keeps_a_retained_decision(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    manifest = capture_text(runtime, TEXT, now=NOW)
    proposal_id = manifest.proposals[0].id
    QueueStore(runtime, CAPTURE_REL).dismiss(proposal_id, reviewer="Myles", reason="already handled")

    again = capture_text(runtime, TEXT, now="2026-02-01T11:00:00+00:00")

    assert len(again.proposals) == 1
    assert again.proposals[0].status == "dismissed"
    assert again.proposals[0].reviewer == "Myles"
    assert again.proposals[0].reason == "already handled"
