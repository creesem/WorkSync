"""Ticket 12: typed text becomes a pending capture proposal in the review queue."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import worksync.work.capture as capture_module
from worksync.safety.files import sha256_bytes
from worksync.work.capture import CAPTURE_REL, capture_text
from worksync.work.queue import Manifest, QueueError, QueueStore

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


def test_a_concurrent_manifest_change_fails_closed_as_stale_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "var"
    capture_text(runtime, TEXT, now=NOW)
    manifest_path = runtime.resolve() / "staging" / "capture" / "manifest.json"
    real_merge = capture_module.merge_manifest

    def racing_merge(previous, fresh, *, token):
        manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
        return real_merge(previous, fresh, token=token)

    monkeypatch.setattr(capture_module, "merge_manifest", racing_merge)

    with pytest.raises(QueueError) as excinfo:
        capture_text(runtime, "Second capture while another tab writes.", now=NOW)

    assert excinfo.value.code == "stale_hash"
    assert excinfo.value.affected == (str(manifest_path),)


def test_a_failed_staging_write_surfaces_as_write_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An OSError must not escape as a bare traceback; the transport maps it to a 500."""
    runtime = tmp_path / "var"
    manifest_path = QueueStore(runtime, CAPTURE_REL).path()

    def failing_save(self, manifest, *, expected=None, expected_absent=False):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(capture_module.QueueStore, "save", failing_save)

    with pytest.raises(QueueError) as excinfo:
        capture_text(runtime, TEXT, now=NOW)

    assert excinfo.value.code == "write_failed"
    assert excinfo.value.affected == (str(manifest_path),)
    assert str(excinfo.value)
    assert not manifest_path.exists()


def test_a_corrupt_manifest_fails_closed_without_overwriting_it(tmp_path: Path) -> None:
    """Unreadable state is not "absent": retrying would loop, so it reports its own code."""
    runtime = tmp_path / "var"
    manifest_path = QueueStore(runtime, CAPTURE_REL).path()
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(QueueError) as excinfo:
        capture_text(runtime, TEXT, now=NOW)

    assert excinfo.value.code == "corrupt_manifest"
    assert excinfo.value.affected == (str(manifest_path),)
    assert manifest_path.read_text(encoding="utf-8") == "{not json"


def test_a_wrong_typed_manifest_surfaces_as_corrupt_manifest(tmp_path: Path) -> None:
    """JSON that parses but rebuilds a bad dataclass is corrupt state, not a dropped request."""
    runtime = tmp_path / "var"
    manifest_path = QueueStore(runtime, CAPTURE_REL).path()
    manifest_path.parent.mkdir(parents=True)
    raw = '{"version": "not-a-number"}'
    manifest_path.write_text(raw, encoding="utf-8")

    with pytest.raises(QueueError) as excinfo:
        capture_text(runtime, TEXT, now=NOW)

    assert excinfo.value.code == "corrupt_manifest"
    assert excinfo.value.affected == (str(manifest_path),)
    assert manifest_path.read_text(encoding="utf-8") == raw


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
