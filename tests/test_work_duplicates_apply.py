"""Spec 7 ticket 03: resolve duplicate pairs as one batch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.duplicates import DuplicatesError, apply, load_manifest, scan

TODAY = date(2026, 10, 6)
ACTIVE = "7. Task Notes/Active"


def _action(write_note: Callable[..., Path], vault: Path, name: str, title: str, *, body: str = "") -> Path:
    text = f"---\ntype: action\nstatus: open\n---\n# {title}\n\n{body}\n"
    return write_note(vault, f"{ACTIVE}/{name}.md", text)


def _seed(vault: Path, write_note: Callable[..., Path]) -> tuple[Path, Path]:
    first = _action(write_note, vault, "A", "Call the vendor about the invoice", body="Canonical detail.")
    second = _action(write_note, vault, "B", "Call vendor about the invoice", body="Duplicate detail.")
    return first, second


def _vault_state(vault: Path) -> dict[str, bytes]:
    return {path.as_posix(): path.read_bytes() for path in vault.rglob("*.md")}


def test_apply_merge_copies_body_and_redirects_duplicate(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal = scan(vault, runtime, today=TODAY).proposals[0]

    result = apply(vault, runtime, reviewer="Myles", reason="Duplicate", confirmed=True, today=TODAY)

    assert result.committed is True
    canonical = (vault / proposal.target_path).read_text(encoding="utf-8")
    assert "## Merged context" in canonical
    assert "Duplicate detail." in canonical

    duplicate = (vault / proposal.source_path).read_text(encoding="utf-8")
    assert "type: redirect" in duplicate
    assert "status: cancelled" in duplicate
    assert "redirect:" in duplicate

    assert (vault / proposal.source_path).is_file()
    assert (vault / proposal.target_path).is_file()
    loaded = load_manifest(runtime)
    assert loaded is not None and loaded.proposals[0].status == "applied"


def test_apply_redirect_leaves_the_canonical_body_untouched(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal = scan(vault, runtime, today=TODAY).proposals[0]
    canonical_before = (vault / proposal.target_path).read_text(encoding="utf-8")

    apply(
        vault,
        runtime,
        reviewer="Myles",
        reason="Redirect",
        confirmed=True,
        today=TODAY,
        overrides={proposal.id: {"resolution": "redirect"}},
    )

    assert (vault / proposal.target_path).read_text(encoding="utf-8") == canonical_before
    assert "type: redirect" in (vault / proposal.source_path).read_text(encoding="utf-8")


def test_apply_override_flips_the_canonical_side(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal = scan(vault, runtime, today=TODAY).proposals[0]

    apply(
        vault,
        runtime,
        reviewer="Myles",
        reason="Other canonical",
        confirmed=True,
        today=TODAY,
        overrides={proposal.id: {"canonical": proposal.source_path}},
    )

    # The note originally chosen as canonical is now the retired redirect.
    assert "type: redirect" in (vault / proposal.target_path).read_text(encoding="utf-8")
    assert "## Merged context" in (vault / proposal.source_path).read_text(encoding="utf-8")


def test_apply_canonical_override_must_name_a_pair_side(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    third = _action(write_note, vault, "C", "Unrelated dashboard task")
    runtime = tmp_path / "var"
    proposal = scan(vault, runtime, today=TODAY).proposals[0]
    before = _vault_state(vault)

    with pytest.raises(DuplicatesError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="Myles",
            reason="Third canonical",
            confirmed=True,
            today=TODAY,
            overrides={proposal.id: {"canonical": third.relative_to(vault).as_posix()}},
        )

    assert excinfo.value.code == "invalid_target"
    assert _vault_state(vault) == before


def test_apply_canonical_override_rejects_an_ambiguous_path(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal = scan(vault, runtime, today=TODAY).proposals[0]
    before = _vault_state(vault)

    with pytest.raises(DuplicatesError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="Myles",
            reason="Ambiguous canonical",
            confirmed=True,
            today=TODAY,
            overrides={proposal.id: {"canonical": "7. Task Notes/Active/NotThere.md"}},
        )

    assert excinfo.value.code == "invalid_target"
    assert _vault_state(vault) == before


def test_apply_requires_confirmation(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    scan(vault, runtime, today=TODAY)
    before = _vault_state(vault)

    with pytest.raises(MutationError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Duplicate", today=TODAY)

    assert excinfo.value.code == "needs_confirmation"
    assert _vault_state(vault) == before


def test_apply_stale_note_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    first, _second = _seed(vault, write_note)
    runtime = tmp_path / "var"
    scan(vault, runtime, today=TODAY)
    first.write_text(first.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    before = _vault_state(vault)

    with pytest.raises(DuplicatesError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Duplicate", confirmed=True, today=TODAY)

    assert excinfo.value.code == "stale_source"
    assert _vault_state(vault) == before


def test_apply_missing_canonical_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal = scan(vault, runtime, today=TODAY).proposals[0]
    (vault / proposal.target_path).unlink()

    with pytest.raises(DuplicatesError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Duplicate", confirmed=True, today=TODAY)

    assert excinfo.value.code == "missing_source"


def test_apply_mid_batch_failure_rolls_back(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
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
        apply(vault, runtime, reviewer="Myles", reason="Duplicate", confirmed=True, today=TODAY)

    assert excinfo.value.code == "rolled_back"
    assert _vault_state(vault) == before
    loaded = load_manifest(runtime)
    assert loaded is not None and all(proposal.status == "pending" for proposal in loaded.proposals)
