"""Spec 5 ticket 03: one-batch apply and dismissal through the gateway."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.ingest import IngestError, load_manifest
from worksync.ingest.apply import apply, dismiss
from worksync.ingest.manifest import Manifest, save_manifest
from worksync.ingest.proposal import Proposal
from worksync.safety import gateway
from worksync.safety.files import sha256_file
from worksync.safety.models import MutationError

TODAY = date(2026, 10, 6)
INBOX = "7. Task Notes/Inbox"
ACTIVE = "7. Task Notes/Active"
DROPPED = "7. Task Notes/Dropped"
PROJECT = "9. Project/Project - Alpha.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        PROJECT,
        "---\ntype: project\nstatus: active\nproject_id: alpha\n"
        'owners:\n  - "[[Myles]]"\npriority: P1\n---\n# Project - Alpha\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def _source(vault: Path, write_note: Callable[..., Path], name: str, title: str) -> Proposal:
    path = write_note(vault, f"{INBOX}/{name}.md", f"# {title}\n\nDo the thing.\n")
    return Proposal(
        id=f"{INBOX}/{name}.md#0",
        action="action",
        source_path=f"{INBOX}/{name}.md",
        source_sha256=sha256_file(path),
        fields={"title": title, "status": "open", "owners": ["[[Myles]]"], "source": f"{INBOX}/{name}.md"},
        confidence=0.6,
        provenance=("title <- heading",),
    )


def _save(runtime: Path, *proposals: Proposal) -> None:
    save_manifest(runtime, Manifest(scan_token="t").with_proposals(tuple(proposals)), expected_absent=True)


def test_apply_creates_action_and_archives_source(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal = _source(vault, write_note, "Note", "Do a thing")
    _save(runtime, proposal)

    result = apply(vault, runtime, reviewer="Myles", reason="Triage", today=TODAY)

    assert result.committed is True
    active = vault / ACTIVE / "Do a thing.md"
    assert active.is_file()
    text = active.read_text(encoding="utf-8")
    assert "type: action" in text and "status: open" in text
    assert "Do the thing." in text
    assert not (vault / INBOX / "Note.md").exists()
    assert (vault / DROPPED / "Note.md").is_file()
    loaded = load_manifest(runtime)
    assert loaded is not None and loaded.proposals[0].status == "applied"


def test_apply_link_existing_archives_without_creating(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{ACTIVE}/Existing.md", "---\ntype: action\nstatus: open\n---\n# Existing\n")
    runtime = tmp_path / "var"
    source = write_note(vault, f"{INBOX}/Dup.md", "# Existing\n")
    proposal = Proposal(
        id=f"{INBOX}/Dup.md#0",
        action="link-existing",
        source_path=f"{INBOX}/Dup.md",
        source_sha256=sha256_file(source),
        target_path=f"{ACTIVE}/Existing.md",
        fields={"title": "Existing", "source": f"{INBOX}/Dup.md"},
    )
    _save(runtime, proposal)

    apply(vault, runtime, reviewer="Myles", reason="Duplicate", today=TODAY)
    assert len(list((vault / ACTIVE).glob("*.md"))) == 1
    assert (vault / DROPPED / "Dup.md").is_file()
    assert not (vault / INBOX / "Dup.md").exists()


def test_apply_merge_fills_target_fields(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    target = write_note(vault, f"{ACTIVE}/Existing.md", "---\ntype: action\nstatus: open\n---\n# Existing\n")
    runtime = tmp_path / "var"
    source = write_note(vault, f"{INBOX}/More.md", "# Existing\n\nMore detail.\n")
    proposal = Proposal(
        id=f"{INBOX}/More.md#0",
        action="merge",
        source_path=f"{INBOX}/More.md",
        source_sha256=sha256_file(source),
        target_path=f"{ACTIVE}/Existing.md",
        fields={"title": "Existing", "priority": "P2", "due": "2026-10-12"},
    )
    _save(runtime, proposal)

    apply(vault, runtime, reviewer="Myles", reason="Merge", confirmed=True, today=TODAY)
    text = target.read_text(encoding="utf-8")
    assert "priority: P2" in text and "due: 2026-10-12" in text
    assert (vault / DROPPED / "More.md").is_file()


def test_apply_drop_requires_confirmation(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    source = write_note(vault, f"{INBOX}/Ref.md", "# Reference\n")
    proposal = Proposal(
        id=f"{INBOX}/Ref.md#0",
        action="drop",
        source_path=f"{INBOX}/Ref.md",
        source_sha256=sha256_file(source),
    )
    _save(runtime, proposal)

    with pytest.raises(MutationError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Not work", today=TODAY)
    assert excinfo.value.code == "needs_confirmation"
    assert (vault / INBOX / "Ref.md").is_file()

    apply(vault, runtime, reviewer="Myles", reason="Not work", confirmed=True, today=TODAY)
    assert (vault / DROPPED / "Ref.md").is_file()


def test_apply_stale_source_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal = _source(vault, write_note, "Note", "Do a thing")
    _save(runtime, proposal)
    (vault / INBOX / "Note.md").write_text("# Do a thing\n\nchanged\n", encoding="utf-8")

    with pytest.raises(IngestError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Triage", today=TODAY)
    assert excinfo.value.code == "stale_source"
    assert not (vault / ACTIVE).exists()


def test_apply_missing_target_fails_closed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    source = write_note(vault, f"{INBOX}/More.md", "# More\n")
    proposal = Proposal(
        id=f"{INBOX}/More.md#0",
        action="merge",
        source_path=f"{INBOX}/More.md",
        source_sha256=sha256_file(source),
        target_path=f"{ACTIVE}/Gone.md",
        fields={"title": "More", "priority": "P2"},
    )
    _save(runtime, proposal)
    with pytest.raises(IngestError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Merge", confirmed=True, today=TODAY)
    assert excinfo.value.code == "missing_source"


def test_apply_link_existing_missing_target_fails_closed(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    source = write_note(vault, f"{INBOX}/Dup.md", "# Dup\n")
    proposal = Proposal(
        id=f"{INBOX}/Dup.md#0",
        action="link-existing",
        source_path=f"{INBOX}/Dup.md",
        source_sha256=sha256_file(source),
        target_path=f"{ACTIVE}/Gone.md",
        fields={"title": "Dup"},
    )
    _save(runtime, proposal)
    with pytest.raises(IngestError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Duplicate", today=TODAY)
    assert excinfo.value.code == "missing_source"
    assert (vault / INBOX / "Dup.md").is_file()


def test_apply_merge_with_nothing_to_fill_fails_closed(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    write_note(
        vault,
        f"{ACTIVE}/Existing.md",
        "---\ntype: action\nstatus: open\npriority: P2\ndue: 2026-10-12\n---\n# Existing\n",
    )
    runtime = tmp_path / "var"
    source = write_note(vault, f"{INBOX}/More.md", "# Existing\n")
    proposal = Proposal(
        id=f"{INBOX}/More.md#0",
        action="merge",
        source_path=f"{INBOX}/More.md",
        source_sha256=sha256_file(source),
        target_path=f"{ACTIVE}/Existing.md",
        fields={"title": "Existing", "priority": "P2", "due": "2026-10-12"},
    )
    _save(runtime, proposal)
    with pytest.raises(IngestError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Merge", confirmed=True, today=TODAY)
    assert excinfo.value.code == "merge_noop"
    assert (vault / INBOX / "More.md").is_file()


def test_apply_mid_batch_failure_rolls_back(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    first = _source(vault, write_note, "One", "First item")
    second = _source(vault, write_note, "Two", "Second item")
    _save(runtime, first, second)
    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if path.name == "Second item.md":
            raise OSError("disk full")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply(vault, runtime, reviewer="Myles", reason="Triage", today=TODAY)
    assert excinfo.value.code == "rolled_back"
    assert (vault / INBOX / "One.md").is_file()
    assert (vault / INBOX / "Two.md").is_file()
    assert not list((vault / ACTIVE).glob("*.md"))
    loaded = load_manifest(runtime)
    assert loaded is not None and all(p.status == "pending" for p in loaded.proposals)


def test_dismiss_requires_reviewer_and_reason(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal = _source(vault, write_note, "Note", "Do a thing")
    _save(runtime, proposal)

    with pytest.raises(IngestError) as excinfo:
        dismiss(runtime, proposal.id, reviewer="", reason="why")
    assert excinfo.value.code == "missing_reviewer"

    manifest = dismiss(runtime, proposal.id, reviewer="Myles", reason="not now")
    assert manifest.proposals[0].status == "dismissed"
    assert manifest.proposals[0].reason == "not now"
    loaded = load_manifest(runtime)
    assert loaded is not None and loaded.proposals[0].status == "dismissed"


def test_cli_ingest_apply_and_dismiss(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{INBOX}/Note.md", "# Do a thing\n")
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]
    assert main(["ingest", "scan", *base, "--inbox", INBOX, "--today", TODAY.isoformat()]) == 0
    capsys.readouterr()

    code = main(["ingest", "apply", *base, "--reviewer", "Myles", "--reason", "Triage", "--json"])
    assert code == 0
    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert (vault / ACTIVE / "Do a thing.md").is_file()
