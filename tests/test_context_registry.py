"""Ticket 05: canonical project identity, resolution, and listing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from worksync.context.association import index_associations
from worksync.context.registry import list_projects, load_projects, resolve_project
from worksync.inventory.index import index_vault
from worksync.work.repository import WorkIndex


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Eleos Automation.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        "project_id: eleos-automation\naliases:\n  - Eleos Automation Service\n"
        'repos:\n  - "C:/repos/eleos"\n---\n# Project - Eleos Automation\n',
    )
    write_note(
        vault,
        "9. Project/Project - PRTF.md",
        '---\ntype: project\nstatus: paused\nowners:\n  - "[[Myles]]"\nproject_id: prtf\n---\n# Project - PRTF\n',
    )


def _index(vault: Path) -> WorkIndex:
    return WorkIndex.from_vault(vault)


def test_load_projects_reads_identity_from_notes(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    records = {record.project_id: record for record in load_projects(_index(vault))}
    assert records["eleos-automation"].name == "Eleos Automation"
    assert records["eleos-automation"].aliases == ("Eleos Automation Service",)
    assert records["eleos-automation"].repos == ("C:/repos/eleos",)
    assert records["prtf"].status == "paused"


def test_resolve_by_project_id_name_and_alias(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = _index(vault)
    assert resolve_project(index, {"project_id": "eleos-automation"}) == {
        "status": "resolved",
        "project_id": "eleos-automation",
    }
    assert resolve_project(index, {"name": "Project - Eleos Automation"})["status"] == "resolved"
    assert resolve_project(index, {"alias": "Eleos Automation Service"})["status"] == "resolved"


def test_resolve_by_repo_path_and_cwd(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    index = _index(vault)
    assert resolve_project(index, {"repo_path": "C:/repos/eleos/src"})["status"] == "resolved"
    assert resolve_project(index, {"cwd": "C:/repos/eleos"})["status"] == "resolved"
    assert resolve_project(index, {"cwd": "C:/elsewhere"})["status"] == "not_found"


def test_ambiguous_and_not_found(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    for name, project_id in (("Alpha", "alpha"), ("Beta", "beta")):
        write_note(
            vault,
            f"9. Project/Project - {name}.md",
            '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
            f"project_id: {project_id}\naliases:\n  - Shared\n---\n# Project - {name}\n",
        )
    index = _index(vault)
    ambiguous = resolve_project(index, {"alias": "Shared"})
    assert ambiguous["status"] == "ambiguous"
    assert {candidate["project_id"] for candidate in ambiguous["candidates"]} == {"alpha", "beta"}
    assert resolve_project(index, {"name": "Missing"}) == {"status": "not_found"}


def test_resolve_does_not_mutate_the_vault(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    resolve_project(_index(vault), {"name": "Eleos Automation"})
    after = {path: path.read_bytes() for path in vault.rglob("*.md")}
    assert before == after


def test_list_projects_reports_repo_and_context_availability(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    (repo / ".project").mkdir(parents=True)
    (repo / ".project" / "WORKSYNC_CONTEXT.md").write_text("# context", encoding="utf-8")
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Eleos.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        f'project_id: eleos\nrepos:\n  - "{repo.as_posix()}"\n---\n# Project - Eleos\n',
    )
    listing = {item["project_id"]: item for item in list_projects(_index(vault))}
    assert listing["eleos"]["name"] == "Eleos"
    assert listing["eleos"]["registered_repo"] == repo.as_posix()
    assert listing["eleos"]["context_available"] is True


def test_list_projects_excludes_error_projects(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "9. Project/Project - Broken.md", "---\ntype: project\nstatus: active\nowners: []\n---\n# B\n")
    assert list_projects(_index(vault)) == []


def test_list_projects_wires_context_staleness(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".project").mkdir(parents=True)
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Eleos.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        f'project_id: eleos\nrepos:\n  - "{repo.as_posix()}"\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        "10. Meetings/2026-01-01 Kickoff.md",
        '---\ntype: meeting\ndate: 2026-01-01\nproject: "[[Project - Eleos]]"\n---\n# Kickoff\n',
    )
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    source = "10. Meetings/2026-01-01 Kickoff.md"
    digest = hashlib.sha256((vault / source).read_bytes()).hexdigest()
    (repo / ".project" / "WORKSYNC_CONTEXT.md").write_text(
        f"# Context\n\n<!-- worksync-sources: {json.dumps({source: digest})} -->\n", encoding="utf-8"
    )
    index = _index(vault)

    assert list_projects(index)[0]["context_stale"] is None
    assert list_projects(index, db_path=db)[0]["context_stale"] is False

    meeting = vault / source
    meeting.write_text(meeting.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")
    assert list_projects(index, db_path=db)[0]["context_stale"] is True
