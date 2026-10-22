"""Gate 1: the versioned Command Center read contract (v1) and its entity route.

Exercises the live loopback server so the assertions cover the real serialized payload, then
validates it against the published ``contracts/command-center.v1.json`` artifact.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import quote

import jsonschema
import pytest

from worksync.context.association import index_associations
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.inventory.index import index_vault

TOKEN = "contract-token"
TODAY = "2026-02-01"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "command-center.v1.json"
ENTITY_FIELDS = {
    "entity_id",
    "entity_type",
    "label",
    "status",
    "priority",
    "owner",
    "owner_id",
    "due",
    "path",
    "attention",
    "timestamps",
    "tags",
    "aliases",
}


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\nperson_id: myles\n---\n# Myles\n")
    write_note(
        vault,
        "9. Project/Project - Alpha.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: alpha\n'
        "next_review: 2026-01-10\nlast_reviewed: 2026-01-01\n---\n# Project - Alpha\n",
    )
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\nproject: "[[Project - Alpha]]"\n'
        "action_id: a1\ndue: 2026-01-05\n---\n# Action One\n",
    )
    write_note(
        vault,
        "Tickets/blocked.md",
        '---\ntype: ticket\nstatus: blocked\nticket_id: blocked-ticket\nassignee: "[[Myles]]"\n'
        "manager_attention: true\n---\n# Blocked ticket\n",
    )


def _serve(gui: GuiService) -> Iterator[str]:
    server = create_server(gui, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def contract_server(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
    _seed(vault, write_note)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    gui = GuiService(vault=vault, db_path=db, runtime_root=tmp_path / "var", vault_name="vault", reviewer="Myles")
    server = create_server(gui, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", gui
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _get(base: str, path: str, token: str | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(base + path)
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_schema_is_a_valid_draft_2020_12_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(_schema())


def test_command_center_matches_the_v1_schema(contract_server: tuple[str, GuiService]) -> None:
    base, _gui = contract_server
    status, payload = _get(base, f"/api/command-center?today={TODAY}", TOKEN)
    assert status == 200
    jsonschema.Draft202012Validator(_schema()).validate(payload)


def test_viewer_and_vault_are_engine_sourced(contract_server: tuple[str, GuiService]) -> None:
    base, _gui = contract_server
    _status, payload = _get(base, f"/api/command-center?today={TODAY}", TOKEN)
    assert payload["contract_version"] == 1
    assert payload["vault"] == {"name": "vault"}
    assert payload["viewer"] == {"name": "Myles"}


def test_viewer_is_null_when_the_reviewer_is_unresolved(contract_server: tuple[str, GuiService]) -> None:
    _base, gui = contract_server
    unresolved = GuiService(
        vault=gui.vault,
        db_path=gui.db_path,
        runtime_root=gui.runtime_root,
        vault_name=gui.vault_name,
        reviewer=None,
    )
    for base in _serve(unresolved):
        _status, payload = _get(base, f"/api/command-center?today={TODAY}", TOKEN)
    assert payload["viewer"] == {"name": None}


def test_sections_carry_engine_titles(contract_server: tuple[str, GuiService]) -> None:
    base, _gui = contract_server
    _status, payload = _get(base, f"/api/command-center?today={TODAY}", TOKEN)
    sections = {section["section_id"]: section for section in payload["sections"]}
    assert sections["needs_attention"]["title"] == "Needs Attention"
    assert sections["my_priorities"]["title"] == "My Priorities"
    assert sections["since_last_check"]["title"] == "Since Last Check"
    assert all(section["subtitle"] for section in payload["sections"])


def test_profile_updated_at_is_null_not_empty(contract_server: tuple[str, GuiService]) -> None:
    base, _gui = contract_server
    _status, payload = _get(base, f"/api/command-center?today={TODAY}", TOKEN)
    assert payload["profile"]["updated_at"] is None


def test_needs_attention_row_carries_owner_severity_and_reason(
    contract_server: tuple[str, GuiService],
) -> None:
    base, _gui = contract_server
    _status, payload = _get(base, f"/api/command-center?today={TODAY}", TOKEN)
    section = next(item for item in payload["sections"] if item["section_id"] == "needs_attention")
    assert section["state"] == "items"
    row = section["items"][0]
    assert row["owner"] == "Myles"
    assert row["owner_id"] == "myles"
    assert row["severity"] in {"high", "medium", "low"}
    assert row["reason"]


def test_entity_route_returns_the_contract_entity(contract_server: tuple[str, GuiService]) -> None:
    base, _gui = contract_server
    status, payload = _get(base, f"/api/entity?id=a1&today={TODAY}", TOKEN)
    assert status == 200
    entity = payload["entity"]
    jsonschema.Draft202012Validator(_schema()["$defs"]["entity"]).validate(entity)
    assert set(entity) == ENTITY_FIELDS
    assert entity["entity_id"] == "a1"
    assert entity["entity_type"] == "action"
    assert entity["owner"] == "Myles"
    assert entity["owner_id"] == "myles"
    assert entity["due"] == "2026-01-05"


def test_entity_route_rejects_path_shaped_and_unknown_ids(
    contract_server: tuple[str, GuiService],
) -> None:
    base, _gui = contract_server
    for bad in ["../secrets", "Actions/A1.md", "A1", "a b", ""]:
        status, payload = _get(base, f"/api/entity?id={quote(bad)}&today={TODAY}", TOKEN)
        assert status == 400, bad
        assert payload["error"] == "bad_request"
    status, payload = _get(base, f"/api/entity?id=does-not-exist&today={TODAY}", TOKEN)
    assert status == 404
    assert payload["error"] == "not_found"


def test_entity_route_requires_the_token(contract_server: tuple[str, GuiService]) -> None:
    base, _gui = contract_server
    status, payload = _get(base, f"/api/entity?id=a1&today={TODAY}")
    assert status == 401
    assert payload["error"] == "unauthorized"


def test_read_cycle_does_not_modify_the_vault(contract_server: tuple[str, GuiService]) -> None:
    base, gui = contract_server

    def snapshot() -> dict:
        return {
            path.relative_to(gui.vault): path.read_bytes() for path in sorted(gui.vault.rglob("*")) if path.is_file()
        }

    before = snapshot()
    _get(base, f"/api/command-center?today={TODAY}", TOKEN)
    _get(base, f"/api/entity?id=a1&today={TODAY}", TOKEN)
    assert snapshot() == before
