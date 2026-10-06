"""Ticket 13: end-to-end parity gates, correction fixtures, and old-vs-new comparison."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.context import service
from worksync.context.association import index_associations
from worksync.gui.controller import GuiService
from worksync.inventory.index import index_vault
from worksync.inventory.parse import scan_vault
from worksync.inventory.validate import structural_issues
from worksync.mcp.main import Server
from worksync.work.repository import WorkIndex
from worksync.work.views import build_views, view_zones, write_views

TODAY = date(2026, 2, 1)
TODAY_ISO = "2026-02-01"
GENERATED_AT = "2026-02-01T09:00:00+00:00"
PROJECT_NOTE = "9. Project/Project - Eleos.md"
MEETING_NOTE = "10. Meetings/2026-01-01 Kickoff.md"
ACTION_NOTE = "Actions/A1.md"
LEGACY_TASK_NOTE = "Notes/Legacy task.md"
MALFORMED_NOTE = "Notes/Malformed.md"
LEGACY_ROOT_ENV = "WORKSYNC_LEGACY_ROOT"


def _seed(vault: Path, write_note: Callable[..., Path], repo: Path) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: eleos\n'
        'aliases:\n  - eleos-alias\nrepos:\n  - "' + repo.as_posix() + '"\n'
        "next_review: 2026-01-10\nlast_reviewed: 2026-01-01\n---\n# Project - Eleos\n",
    )
    write_note(
        vault,
        MEETING_NOTE,
        '---\ntype: meeting\nstatus: held\ndate: 2026-01-01\nproject: "[[Project - Eleos]]"\n'
        "---\n# Kickoff\nThe ProgramIds migration completed.\n",
    )
    write_note(
        vault,
        ACTION_NOTE,
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\n'
        'project: "[[Project - Eleos]]"\ndue: 2026-01-05\n---\n# Action One\n',
    )
    write_note(vault, "Tickets/T1.md", "---\ntype: ticket\nstatus: in_progress\nmanager_attention: true\n---\n# T1\n")
    write_note(vault, LEGACY_TASK_NOTE, "---\ntype: task\nstatus: todo\n---\n# Legacy task\n")
    write_note(vault, MALFORMED_NOTE, "---\ntype: project\nstatus: active\n# never closed\n")


def _built(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    _seed(vault, write_note, repo)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    return repo, db


def _write_projection(repo: Path, vault: Path, notes: tuple[str, ...]) -> None:
    output = repo / ".project"
    output.mkdir(parents=True, exist_ok=True)
    digests = {note: hashlib.sha256((vault / note).read_bytes()).hexdigest() for note in notes}
    (output / "WORKSYNC_CONTEXT.md").write_text(
        f"# Context\n\nGenerated: 2026-09-20T10:00:00+00:00\n\n<!-- worksync-sources: {json.dumps(digests)} -->\n",
        encoding="utf-8",
    )


def test_correction_fixtures_parse_tolerantly_and_map_legacy_task(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    _seed(vault, write_note, repo)

    records = scan_vault(vault)
    paths = {record.path for record in records}
    assert MALFORMED_NOTE in paths
    assert any(item["path"] == MALFORMED_NOTE for item in structural_issues(records))

    index = WorkIndex.from_vault(vault)
    legacy = next(entity for entity in index.entities if entity.path == LEGACY_TASK_NOTE)
    assert legacy.entity_type.value == "action"


def test_end_to_end_read_scenarios(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo, db = _built(vault, write_note, tmp_path)
    _write_projection(repo, vault, (MEETING_NOTE, ACTION_NOTE))

    search = service.search_evidence(vault, db, "ProgramIds", project_id="eleos")
    assert [item["path"] for item in search["results"]] == [MEETING_NOTE]
    evidence = service.read_evidence(vault, db, "eleos", MEETING_NOTE)
    assert evidence["state"] == "ok"
    assert "ProgramIds migration completed" in evidence["content"]

    assert service.resolve_project(vault, {"name": "Eleos"}) == {"status": "resolved", "project_id": "eleos"}
    assert service.read_context(vault, db, "eleos")["state"] == "ok"
    assert service.get_staleness(vault, db, "eleos") == {"project_id": "eleos", "fresh": True, "reasons": []}

    relationships = service.relationships(vault, "project", "Eleos")
    assert relationships is not None
    assert relationships["people"] == ["Myles"]
    assert relationships["meetings"] == ["Kickoff"]
    assert service.get_entity(vault, "project", "Eleos") is not None
    assert service.attention(vault, TODAY)
    assert service.project_review(vault, "Eleos", TODAY)["project"]["project_id"] == "eleos"


def test_view_render_containment(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _repo, _db = _built(vault, write_note, tmp_path)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    index = WorkIndex.from_vault(vault)
    views = build_views(index, today=TODAY, generated_at=datetime.fromisoformat(GENERATED_AT))
    zones = view_zones(tmp_path / "var", vault_root=vault)
    assert write_views(views, zones, confirmed=True).committed is True
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before


def test_cli_output_is_deterministic_for_a_fixed_reference_date(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _repo, db = _built(vault, write_note, tmp_path)
    commands = [
        ["review", "today", "--vault", str(vault), "--today", TODAY_ISO, "--json"],
        ["review", "projects", "--vault", str(vault), "--today", TODAY_ISO, "--json"],
        ["search", "ProgramIds", "--vault", str(vault), "--db", str(db), "--project", "eleos", "--json"],
        ["views", "render", "--vault", str(vault), "--today", TODAY_ISO, "--generated-at", GENERATED_AT, "--json"],
    ]
    for command in commands:
        assert main(command) == 0
        first = capsys.readouterr().out
        assert main(command) == 0
        second = capsys.readouterr().out
        assert first == second, command


def test_cli_mcp_and_gui_return_the_same_provenance_envelope(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _repo, db = _built(vault, write_note, tmp_path)
    expected = service.search_evidence(vault, db, "ProgramIds", project_id="eleos")

    assert main(["search", "ProgramIds", "--vault", str(vault), "--db", str(db), "--project", "eleos", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == expected

    server = Server(vault, db, stdin=StringIO(), stdout=StringIO(), stderr=StringIO())
    mcp = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "context_search", "arguments": {"project_id": "eleos", "query": "ProgramIds"}},
        }
    )
    assert mcp is not None and "error" not in mcp
    assert mcp["result"]["structuredContent"] == expected

    gui = GuiService(vault=vault, db_path=db, runtime_root=tmp_path / "var", vault_name="vault")
    assert gui.search("ProgramIds", project_id="eleos")["result"] == expected


def _legacy_root() -> Path:
    override = os.environ.get(LEGACY_ROOT_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1].parent / "WorkSync-Control-Center"


def test_old_vs_new_read_capabilities_match(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    legacy_root = _legacy_root()
    legacy_src = legacy_root / "src"
    if not (legacy_src / "context_service.py").is_file():
        pytest.skip(f"Legacy repository not available at {legacy_root}")

    repo = tmp_path / "repo"
    _seed(vault, write_note, repo)
    new_src = Path(__file__).resolve().parents[1] / "src"
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "vault, legacy_src, new_src = sys.argv[1:4]\n"
        "sys.path.insert(0, legacy_src)\n"
        "import context_service as legacy\n"
        "sys.path.insert(0, new_src)\n"
        "from worksync.context import service\n"
        "hints = [{'project_id': 'eleos'}, {'name': 'Eleos'}, {'alias': 'eleos-alias'}, {'name': 'Missing'}]\n"
        "resolved = []\n"
        "for hint in hints:\n"
        "    old = legacy.resolve_project(Path(vault), hint)\n"
        "    new = service.resolve_project(vault, hint)\n"
        "    resolved.append({'status': [old.get('status'), new.get('status')],\n"
        "                     'project_id': [old.get('project_id'), new.get('project_id')]})\n"
        "def norm(items):\n"
        "    return sorted((i['project_id'], i['name'], i['status']) for i in items if i.get('project_id'))\n"
        "print(json.dumps({'resolved': resolved,\n"
        "                  'list': [norm(legacy.list_projects(Path(vault))), norm(service.list_projects(vault))]}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(vault), str(legacy_src), str(new_src)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    for entry in payload["resolved"]:
        assert entry["status"][0] == entry["status"][1], entry
        assert entry["project_id"][0] == entry["project_id"][1], entry
    legacy_list, new_list = payload["list"]
    assert legacy_list == new_list
