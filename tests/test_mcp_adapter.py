"""Ticket 10: the read-only stdio MCP adapter over the retrieval service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from io import StringIO
from pathlib import Path

from worksync.cli.main import main as cli_main
from worksync.context import service
from worksync.mcp.main import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    TOOL_NAMES,
    Server,
)

PROJECT_NOTE = "9. Project/Project - Eleos.md"
MEMBER_NOTE = "10. Meetings/2026-01-01 Kickoff.md"
NON_MEMBER_NOTE = "Notes/unlinked.md"
EXPECTED_TOOLS = {
    "project_resolve",
    "project_list",
    "entity_read",
    "entity_list",
    "relationships",
    "attention_list",
    "project_review",
    "person_workload",
    "context_search",
    "evidence_read",
    "context_read",
    "context_staleness",
}


def _seed(vault: Path, write_note: Callable[..., Path], repo: Path) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        f'project_id: eleos\nrepos:\n  - "{repo.as_posix()}"\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        MEMBER_NOTE,
        '---\ntype: meeting\nstatus: held\ndate: 2026-01-01\nproject: "[[Project - Eleos]]"\n'
        "---\n# Kickoff\nThe ProgramIds migration completed.\n",
    )
    write_note(vault, NON_MEMBER_NOTE, "---\ntype: reference\n---\n# Other\nProgramIds elsewhere.\n")


def _build(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> tuple[Path, Path, Server]:
    repo = tmp_path / "repo"
    _seed(vault, write_note, repo)
    db = tmp_path / "index.sqlite3"
    assert cli_main(["index", "--vault", str(vault), "--db", str(db)]) == 0
    server = Server(vault, db, stdin=StringIO(), stdout=StringIO(), stderr=StringIO())
    return repo, db, server


def _call(server: Server, name: str, arguments: dict) -> dict:
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    assert response is not None
    assert "error" not in response, response
    return response["result"]["structuredContent"]


def test_initialize_pins_protocol(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _repo, _db, server = _build(vault, write_note, tmp_path)
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSION}}
    )
    assert response is not None
    result = response["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert result["serverInfo"]["name"] == "worksync-mcp"
    assert result["capabilities"] == {"tools": {}}

    bad = server.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}
    )
    assert bad is not None
    assert bad["error"]["code"] == INVALID_PARAMS


def test_tools_list_is_a_read_only_set(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _repo, _db, server = _build(vault, write_note, tmp_path)
    response = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert response is not None
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == EXPECTED_TOOLS
    assert TOOL_NAMES == EXPECTED_TOOLS
    forbidden = {"write", "mutate", "create", "update", "delete", "commit", "apply", "drop", "merge"}
    assert names.isdisjoint(forbidden)


def test_project_and_entity_tools(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _repo, _db, server = _build(vault, write_note, tmp_path)
    assert _call(server, "project_resolve", {"name": "Eleos"}) == {"status": "resolved", "project_id": "eleos"}
    projects = _call(server, "project_list", {})["projects"]
    assert projects[0]["project_id"] == "eleos"

    project = _call(server, "entity_read", {"type": "project", "name": "Eleos"})["entity"]
    assert "Eleos" in project["title"]
    assert _call(server, "entity_read", {"type": "project", "name": "Missing"})["state"] == "not_found"
    meetings = _call(server, "entity_list", {"type": "meeting"})["entities"]
    assert [entity["title"] for entity in meetings] == ["Kickoff"]

    related = _call(server, "relationships", {"type": "project", "name": "Eleos"})
    assert related["state"] == "ok"
    assert related["people"] == ["Myles"]
    assert related["meetings"] == ["Kickoff"]


def test_review_tools(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _repo, _db, server = _build(vault, write_note, tmp_path)
    attention = _call(server, "attention_list", {"today": "2026-02-01"})
    assert isinstance(attention["items"], list)
    review = _call(server, "project_review", {"name": "Eleos", "today": "2026-02-01"})
    assert review["state"] == "ok"
    assert "Eleos" in review["review"]["project"]["title"]
    workload = _call(server, "person_workload", {"name": "Myles", "today": "2026-02-01"})
    assert workload["state"] == "ok"
    assert workload["workload"]["person"]["title"] == "Myles"


def test_context_search_matches_the_retrieval_service(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _repo, db, server = _build(vault, write_note, tmp_path)
    payload = _call(server, "context_search", {"project_id": "eleos", "query": "ProgramIds"})
    assert [item["path"] for item in payload["results"]] == [MEMBER_NOTE]
    assert payload["results"][0]["association"]["tier"] == "A"
    assert payload["results"][0]["stale"] is False

    direct = service.search_evidence(vault, db, "ProgramIds", project_id="eleos")
    assert payload == direct


def test_evidence_read_returns_content_and_provenance(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _repo, _db, server = _build(vault, write_note, tmp_path)
    payload = _call(server, "evidence_read", {"project_id": "eleos", "source_id": MEMBER_NOTE})
    assert payload["state"] == "ok"
    assert payload["association"] == {"method": "explicit", "authority": "authoritative", "tier": "A"}
    assert "ProgramIds migration completed" in payload["content"]


def test_context_read_and_staleness(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo, db, server = _build(vault, write_note, tmp_path)
    output = repo / ".project"
    output.mkdir(parents=True)
    digest = hashlib.sha256((vault / MEMBER_NOTE).read_bytes()).hexdigest()
    (output / "WORKSYNC_CONTEXT.md").write_text(
        f"# Context\n\nGenerated: 2026-09-20T10:00:00+00:00\n\n"
        f"<!-- worksync-sources: {json.dumps({MEMBER_NOTE: digest})} -->\n",
        encoding="utf-8",
    )
    assert _call(server, "context_read", {"project_id": "eleos"})["state"] == "ok"
    assert _call(server, "context_staleness", {"project_id": "eleos"}) == {
        "project_id": "eleos",
        "fresh": True,
        "reasons": [],
    }


def test_protocol_errors(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _repo, _db, server = _build(vault, write_note, tmp_path)
    assert server.handle_line("{not json")["error"]["code"] == -32700
    invalid = server.handle_message({"id": 1, "method": "tools/list"})
    assert invalid is not None
    assert invalid["error"]["code"] == INVALID_REQUEST

    unknown_method = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {}})
    assert unknown_method is not None
    assert unknown_method["error"]["code"] == METHOD_NOT_FOUND

    unknown_tool = server.handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "write_note", "arguments": {}}}
    )
    assert unknown_tool is not None
    assert unknown_tool["error"]["code"] == INVALID_PARAMS

    assert server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
