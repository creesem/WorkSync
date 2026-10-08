"""Spec 5 ticket 01: the ingest proposal model and stale-safe manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.ingest.manifest import (
    Manifest,
    load_manifest,
    manifest_path,
    manifest_sha256,
    save_manifest,
)
from worksync.ingest.proposal import Proposal


def _proposal(**overrides: object) -> Proposal:
    base = {
        "id": "inbox/Note.md#0",
        "action": "action",
        "source_path": "inbox/Note.md",
        "source_sha256": "abc",
        "fields": {"title": "Do a thing", "priority": "P2"},
        "confidence": 0.72,
        "provenance": ("heading -> title", "explicit -> priority"),
    }
    base.update(overrides)
    return Proposal(**base)  # type: ignore[arg-type]


def test_proposal_round_trips() -> None:
    proposal = _proposal(target_path="7. Task Notes/Active/x.md", status="blocked", reviewer="Myles", reason="why")
    restored = Proposal.from_dict(proposal.to_dict())
    assert restored == proposal


def test_manifest_round_trips(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    manifest = Manifest(scan_token="token-1").with_proposals((_proposal(),))
    save_manifest(runtime, manifest, expected_absent=True)

    loaded = load_manifest(runtime)
    assert loaded is not None
    assert loaded.scan_token == "token-1"
    assert loaded.proposals == (_proposal(),)
    assert json.loads(manifest_path(runtime).read_text(encoding="utf-8"))["version"] == 1


def test_load_manifest_returns_none_when_absent(tmp_path: Path) -> None:
    assert load_manifest(tmp_path / "var") is None
    assert manifest_sha256(tmp_path / "var") is None


def test_first_create_race_fails_closed(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    save_manifest(runtime, Manifest(scan_token="a"), expected_absent=True)
    with pytest.raises(RuntimeError):
        save_manifest(runtime, Manifest(scan_token="b"), expected_absent=True)


def test_guarded_update_requires_the_current_hash(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    save_manifest(runtime, Manifest(scan_token="a"), expected_absent=True)
    current = manifest_sha256(runtime)
    assert current is not None

    with pytest.raises(RuntimeError):
        save_manifest(runtime, Manifest(scan_token="b"), expected="deadbeef")

    save_manifest(runtime, Manifest(scan_token="c"), expected=current)
    loaded = load_manifest(runtime)
    assert loaded is not None and loaded.scan_token == "c"


def test_manifest_lives_in_the_staging_zone(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    save_manifest(runtime, Manifest(scan_token="a"), expected_absent=True)
    assert manifest_path(runtime).is_relative_to((runtime / "staging").resolve())
