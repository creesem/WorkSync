"""Ticket 05: note_project_links is the sole membership table; explicit/alias are authoritative."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.context.association import index_associations
from worksync.inventory.index import connect, index_vault


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Eleos Automation.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        "project_id: eleos-automation\naliases:\n  - Eleos Automation Service\n---\n# Project - Eleos Automation\n",
    )
    write_note(
        vault,
        "Tickets/T1.md",
        '---\ntype: ticket\nstatus: open\nproject: "[[Project - Eleos Automation]]"\n---\n# Ticket One\n',
    )
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nproject: "[[Eleos Automation Service]]"\n---\n# Action One\n',
    )
    write_note(
        vault,
        "Meetings/M1.md",
        "---\ntype: meeting\nstatus: held\ndate: 2026-01-01\n"
        'projects:\n  - "[[Project - Eleos Automation]]"\n---\n# Meeting One\n',
    )


def _links(db: Path) -> list[tuple[str, str, str, str]]:
    con = connect(db)
    try:
        return [
            (path, project_id, method, authority)
            for path, project_id, method, authority in con.execute(
                "SELECT path, project_id, association_method, evidence_authority FROM note_project_links"
            )
        ]
    finally:
        con.close()


def _build(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Path:
    _seed(vault, write_note)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    return db


def test_explicit_and_alias_membership_is_authoritative(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    db = _build(vault, write_note, tmp_path)
    links = {(path, method): authority for path, _, method, authority in _links(db)}
    assert links[("Tickets/T1.md", "explicit")] == "authoritative"
    assert links[("Actions/A1.md", "alias")] == "authoritative"
    assert links[("Meetings/M1.md", "explicit")] == "authoritative"


def test_project_notes_are_not_their_own_members(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    assert not any(path.startswith("9. Project/") for path, _, _, _ in _links(db))


def test_no_fts_membership_rows(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    assert {method for _, _, method, _ in _links(db)} <= {"explicit", "alias"}


def test_association_is_idempotent(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = _build(vault, write_note, tmp_path)
    first = sorted(_links(db))
    index_associations(db, vault)
    assert sorted(_links(db)) == first


def test_removed_note_links_are_gone(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Eleos.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: eleos\n---\n# Project - Eleos\n',
    )
    action = write_note(
        vault,
        "Actions/Gone.md",
        '---\ntype: action\nstatus: open\nproject: "[[Project - Eleos]]"\n---\n# Gone\n',
    )
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    assert any(path == "Actions/Gone.md" for path, _, _, _ in _links(db))
    action.unlink()
    index_vault(db, vault)
    index_associations(db, vault)
    assert not any(path == "Actions/Gone.md" for path, _, _, _ in _links(db))


def test_excluded_and_superseded_notes_downgrade_to_candidate(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    write_note(
        vault,
        "1. Rough Notes/Krisp Proposals/proposal.md",
        '---\ntype: meeting\nstatus: draft\nproject: "[[Project - Eleos Automation]]"\n---\n# Proposal\n',
    )
    write_note(
        vault,
        "7. Task Notes/Dropped/Task - dropped.md",
        '---\ntype: action\nstatus: dropped\nproject: "[[Project - Eleos Automation]]"\n---\n# Dropped\n',
    )
    write_note(
        vault,
        "Notes/Superseded.md",
        '---\ntype: action\nstatus: superseded\nproject: "[[Project - Eleos Automation]]"\n---\n# Superseded\n',
    )
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)

    authority = {(path, project_id): value for path, project_id, _, value in _links(db)}
    assert authority[("Tickets/T1.md", "eleos-automation")] == "authoritative"
    assert authority[("1. Rough Notes/Krisp Proposals/proposal.md", "eleos-automation")] == "candidate"
    assert authority[("7. Task Notes/Dropped/Task - dropped.md", "eleos-automation")] == "candidate"
    assert authority[("Notes/Superseded.md", "eleos-automation")] == "candidate"
