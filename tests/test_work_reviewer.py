"""Spec 3: current reviewer resolution and persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from worksync.work.reviewer import ReviewerError, load_reviewer, resolve_reviewer, store_reviewer


def test_explicit_reviewer_is_returned_and_persisted(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    assert resolve_reviewer(runtime, explicit="Myles") == "Myles"
    assert load_reviewer(runtime) == "Myles"


def test_stored_reviewer_is_used_when_no_explicit(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    store_reviewer(runtime, "Stored Reviewer")
    assert resolve_reviewer(runtime, configured="Config Reviewer") == "Stored Reviewer"


def test_configured_reviewer_is_used_when_nothing_stored(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    assert resolve_reviewer(runtime, configured="Config Reviewer") == "Config Reviewer"


def test_missing_reviewer_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ReviewerError) as excinfo:
        resolve_reviewer(tmp_path / "var")
    assert excinfo.value.code == "missing_reviewer"


def test_explicit_reviewer_overrides_stored(tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    store_reviewer(runtime, "Stored")
    assert resolve_reviewer(runtime, explicit="Override") == "Override"
    assert load_reviewer(runtime) == "Override"
