"""Spec 5 ticket 02: inbox discovery, deterministic enrichment, and `ingest scan`."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.ingest import IngestError, load_manifest, scan

TODAY = date(2026, 10, 6)
INBOX = "7. Task Notes/Inbox"
ACTIVE = "7. Task Notes/Active"
PROJECT = "9. Project/Project - Alpha.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        PROJECT,
        "---\ntype: project\nstatus: active\nproject_id: alpha\n"
        'owners:\n  - "[[Myles]]"\npriority: P1\n---\n# Project - Alpha\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def _inbox_note(vault: Path, write_note: Callable[..., Path], name: str, body: str, frontmatter: str = "") -> Path:
    text = f"---\n{frontmatter}---\n{body}" if frontmatter else body
    return write_note(vault, f"{INBOX}/{name}.md", text)


def test_scan_proposes_an_enriched_action(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    _inbox_note(
        vault,
        write_note,
        "Call vendor",
        "# Call the vendor about the invoice\n",
        'owners:\n  - "[[Myles]]"\nproject: "[[Project - Alpha]]"\npriority: 2\ndue: 2026-10-10\n',
    )
    manifest = scan(vault, tmp_path / "var", today=TODAY, inbox_path=INBOX)

    assert len(manifest.proposals) == 1
    proposal = manifest.proposals[0]
    assert proposal.action == "action"
    assert proposal.fields["title"] == "Call the vendor about the invoice"
    assert proposal.fields["owners"] == ["[[Myles]]"]
    assert proposal.fields["project"] == "[[Project - Alpha]]"
    assert proposal.fields["priority"] == "P2"
    assert proposal.fields["due"] == "2026-10-10"
    assert proposal.fields["status"] == "open"
    assert proposal.source_sha256
    assert any("title" in reason for reason in proposal.provenance)
    assert 0.4 <= proposal.confidence <= 0.95


def test_scan_inherits_project_owner_and_priority(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    _inbox_note(vault, write_note, "Follow up", "# Follow up on the report\n", 'project: "[[Project - Alpha]]"\n')
    manifest = scan(vault, tmp_path / "var", today=TODAY, inbox_path=INBOX)
    proposal = manifest.proposals[0]
    assert proposal.fields["owners"] == ["[[Myles]]"]
    assert proposal.fields["priority"] == "P1"
    assert any("project" in reason for reason in proposal.provenance)


def test_scan_proposes_link_existing_for_a_duplicate(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    write_note(
        vault, f"{ACTIVE}/Existing.md", "---\ntype: action\nstatus: open\n---\n# Call the vendor about the invoice\n"
    )
    _inbox_note(vault, write_note, "Call vendor", "# Call the vendor about the invoice\n")
    manifest = scan(vault, tmp_path / "var", today=TODAY, inbox_path=INBOX)
    proposal = manifest.proposals[0]
    assert proposal.action == "link-existing"
    assert proposal.target_path == f"{ACTIVE}/Existing.md"


def test_scan_proposes_drop_for_a_reference_and_skips_work_entities(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    _inbox_note(vault, write_note, "Ref", "# Reference material\n", "type: reference\n")
    _inbox_note(vault, write_note, "Proj", "# Project - Alpha\n", "type: project\nstatus: active\n")
    manifest = scan(vault, tmp_path / "var", today=TODAY, inbox_path=INBOX)
    actions = [p.action for p in manifest.proposals]
    assert actions == ["drop"]


def test_scan_requires_the_inbox_root(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    with pytest.raises(IngestError) as excinfo:
        scan(vault, tmp_path / "var", today=TODAY, inbox_path=INBOX)
    assert excinfo.value.code == "missing_root"


def test_rescan_retires_an_undiscovered_proposal(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    first = _inbox_note(vault, write_note, "One", "# First item\n")
    _inbox_note(vault, write_note, "Two", "# Second item\n")
    runtime = tmp_path / "var"
    manifest = scan(vault, runtime, today=TODAY, inbox_path=INBOX)
    assert {p.status for p in manifest.proposals} == {"pending"}

    first.unlink()
    manifest = scan(vault, runtime, today=TODAY, inbox_path=INBOX)
    statuses = {p.source_path: p.status for p in manifest.proposals}
    assert statuses[f"{INBOX}/One.md"] == "obsolete"
    assert statuses[f"{INBOX}/Two.md"] == "pending"


def test_cli_ingest_scan_and_show(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    _inbox_note(vault, write_note, "One", "# Do the thing\n")
    runtime = tmp_path / "var"
    base = ["--vault", str(vault), "--runtime", str(runtime)]
    code = main(["ingest", "scan", *base, "--inbox", INBOX, "--today", TODAY.isoformat(), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["proposals"][0]["action"] == "action"
    assert load_manifest(runtime) is not None

    code = main(["ingest", "show", *base, "--json"])
    assert code == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["scan_token"] == payload["scan_token"]
