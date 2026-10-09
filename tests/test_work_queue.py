"""Spec 7 ticket 01: the generic review-queue primitive in `work.queue`.

The primitive owns proposal/manifest shape, guarded stale-safe persistence, decision
basis invalidation, and merge-on-rescan. It holds no domain detection logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worksync.work.queue import (
    DecisionEntry,
    Manifest,
    Proposal,
    QueueStore,
    merge_manifest,
)

REL = Path("dupes") / "manifest.json"


def _proposal(**overrides: object) -> Proposal:
    base: dict[str, object] = {
        "id": "a.md|b.md",
        "action": "merge",
        "source_path": "a.md",
        "source_sha256": "s1",
        "fields": {"title": "Do a thing"},
    }
    base.update(overrides)
    return Proposal(**base)  # type: ignore[arg-type]


def test_proposal_round_trips_basis_and_decision_history() -> None:
    entry = DecisionEntry(outcome="dismissed", reason="basis changed", at="2026-10-06T10:00:00+00:00")
    proposal = _proposal(
        basis_sha256="baseline",
        target_path="t.md",
        target_sha256="ts",
        status="dismissed",
        reviewer="Myles",
        reason="keep both",
        decided_at="2026-10-06T09:00:00+00:00",
        decision_history=(entry,),
    )
    assert Proposal.from_dict(proposal.to_dict()) == proposal


def test_unset_decision_fields_are_omitted_from_json() -> None:
    serialized = _proposal().to_dict()
    for key in ("basis_sha256", "target_sha256", "decided_at", "decision_history"):
        assert key not in serialized
    assert Proposal.from_dict(serialized) == _proposal()


def test_effective_basis_falls_back_to_the_source_hash() -> None:
    assert _proposal(source_sha256="s9").effective_basis() == "s9"
    assert _proposal(source_sha256="s9", basis_sha256="explicit").effective_basis() == "explicit"


def test_manifest_round_trips() -> None:
    manifest = Manifest(scan_token="token-1").with_proposals((_proposal(),))
    assert Manifest.from_dict(manifest.to_dict()) == manifest


def test_store_first_create_race_fails_closed(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "var", REL)
    store.save(Manifest(scan_token="a"), expected_absent=True)
    with pytest.raises(RuntimeError):
        store.save(Manifest(scan_token="b"), expected_absent=True)


def test_store_guarded_update_requires_the_current_hash(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "var", REL)
    store.save(Manifest(scan_token="a"), expected_absent=True)
    current = store.sha256()
    assert current is not None

    with pytest.raises(RuntimeError):
        store.save(Manifest(scan_token="b"), expected="deadbeef")

    store.save(Manifest(scan_token="c"), expected=current)
    loaded = store.load()
    assert loaded is not None and loaded.scan_token == "c"
    assert store.load_with_hash() is not None


def test_store_lives_in_the_staging_zone(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "var", REL)
    store.save(Manifest(scan_token="a"), expected_absent=True)
    assert store.path().is_relative_to((tmp_path / "var" / "staging").resolve())
    assert store.path().name == "manifest.json"


def test_manifest_update_op_is_a_staging_operation(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "var", REL)
    op = store.manifest_op(Manifest(scan_token="t"), expected="abc")
    assert op.kind == "update"
    assert op.zone == "staging"
    assert op.path == REL
    assert op.expected == "abc"
    assert op.content is not None


def test_dismissed_decision_is_retained_while_the_basis_is_unchanged() -> None:
    previous = Manifest(scan_token="t1").with_proposals(
        (
            _proposal(
                basis_sha256="baseline",
                status="dismissed",
                reviewer="Myles",
                reason="keep both",
            ),
        )
    )
    fresh = _proposal(basis_sha256="baseline", source_sha256="s1")

    merged = merge_manifest(previous, (fresh,), token="t2")

    assert merged.proposals[0].status == "dismissed"
    assert merged.proposals[0].reason == "keep both"
    assert merged.proposals[0].decision_history == ()


def test_basis_change_voids_the_decision_into_pending_with_history() -> None:
    previous = Manifest(scan_token="t1").with_proposals(
        (_proposal(basis_sha256="baseline", status="dismissed", reviewer="Myles", reason="keep both"),)
    )
    fresh = _proposal(basis_sha256="changed", source_sha256="s2")

    merged = merge_manifest(previous, (fresh,), token="t2")
    proposal = merged.proposals[0]

    assert proposal.status == "pending"
    assert proposal.basis_sha256 == "changed"
    assert proposal.decision_history[-1].outcome == "dismissed"
    assert proposal.decision_history[-1].reason
    assert proposal.decision_history[-1].at


def test_undiscovered_pending_proposal_is_retired() -> None:
    one = _proposal(id="one", source_path="one.md")
    two = _proposal(id="two", source_path="two.md")
    previous = Manifest(scan_token="t1").with_proposals((one, two))

    merged = merge_manifest(previous, (one,), token="t2")
    statuses = {proposal.id: proposal.status for proposal in merged.proposals}

    assert statuses["one"] == "pending"
    assert statuses["two"] == "obsolete"
