"""Ticket 14 (Task 2): the Command Center route applies the layout profile."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from worksync.context.association import index_associations
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.inventory.index import index_vault
from worksync.work.layout_profile import (
    KNOWN_SECTIONS,
    PROFILE_FILENAME,
    default_profile,
    profile_path,
)
from worksync.work.layout_profile_store import save_profile

TODAY = "2026-02-01"
TOKEN = "layout-profile-route-token"
NOW = "2026-10-18T12:30:00+00:00"
OWNER = "dana"
OWNER_ACTION = "Actions/for-dana.md"
OWNER_TICKET = "Tickets/for-dana.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "People/Dana.md",
        "---\ntype: person\nstatus: active\nperson_id: dana\n---\n# Dana\n",
    )
    write_note(
        vault,
        OWNER_ACTION,
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Dana]]"\n---\n# Dana action\n',
    )
    write_note(
        vault,
        OWNER_TICKET,
        '---\ntype: ticket\nstatus: open\nassignee: "[[Dana]]"\n---\n# Dana ticket\n',
    )


@pytest.fixture
def route(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
    _seed(vault, write_note)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    gui = GuiService(
        vault=vault,
        db_path=db,
        runtime_root=tmp_path / "var",
        vault_name="vault",
        reviewer="Dana",
    )
    server = create_server(gui, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", gui
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _get(base: str, path: str) -> tuple[int, str, dict]:
    request = urllib.request.Request(base + path)
    request.add_header(TOKEN_HEADER, TOKEN)
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.headers.get_content_type(), json.loads(response.read().decode("utf-8"))


def _post(base: str, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header(TOKEN_HEADER, TOKEN)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_command_center_route_returns_the_default_profile_and_section_order(
    route: tuple[str, GuiService],
) -> None:
    base, _gui = route

    status, content_type, payload = _get(base, f"/api/command-center?today={TODAY}")

    assert status == 200
    assert content_type == "application/json"
    assert payload["profile"]["owner_id"] is None
    assert payload["profile"]["section_order"] == list(KNOWN_SECTIONS)
    assert payload["profile"]["visibility"] == {section: True for section in KNOWN_SECTIONS}
    assert [section["section_id"] for section in payload["sections"]] == list(KNOWN_SECTIONS)


def test_command_center_route_reorders_and_drops_hidden_sections(route: tuple[str, GuiService], vault: Path) -> None:
    base, gui = route
    requested = replace(
        default_profile(),
        owner_id=OWNER,
        section_order=("since_last_check", "needs_attention", "my_priorities"),
        visibility={"needs_attention": True, "my_priorities": False, "since_last_check": True},
    )
    save_profile(vault, gui.runtime_root, requested, now=NOW)

    status, _content_type, payload = _get(base, f"/api/command-center?today={TODAY}")

    assert status == 200
    assert [section["section_id"] for section in payload["sections"]] == [
        "since_last_check",
        "needs_attention",
    ]
    assert payload["profile"]["section_order"] == [
        "since_last_check",
        "needs_attention",
        "my_priorities",
    ]
    assert payload["profile"]["visibility"]["my_priorities"] is False
    assert payload["profile"]["owner_id"] == OWNER


def test_command_center_route_owner_makes_my_priorities_available(route: tuple[str, GuiService], vault: Path) -> None:
    base, gui = route
    save_profile(vault, gui.runtime_root, replace(default_profile(), owner_id=OWNER), now=NOW)

    status, _content_type, payload = _get(base, f"/api/command-center?today={TODAY}")

    assert status == 200
    sections = {section["section_id"]: section for section in payload["sections"]}
    assert sections["my_priorities"]["availability"] == "available"
    assert sections["my_priorities"]["effective_filters"] == {"owner_id": OWNER}
    assert {item["path"] for item in sections["my_priorities"]["items"]} == {
        OWNER_ACTION,
        OWNER_TICKET,
    }


def test_save_layout_profile_action_changes_the_next_route_read(route: tuple[str, GuiService], vault: Path) -> None:
    """Ticket 15: the GUI's save action drives the next route read, without touching a note."""
    base, _gui = route
    before = _snapshot(vault)
    visibility = {"needs_attention": False, "my_priorities": True, "since_last_check": False}

    status, payload = _post(
        base,
        "/api/action/save-layout-profile",
        {
            "section_order": ["my_priorities", "since_last_check", "needs_attention"],
            "visibility": visibility,
            "owner_id": OWNER,
        },
    )

    assert status == 200
    assert payload["committed"] is True
    assert payload["profile"]["revision"] == 2

    status, _content_type, command_center = _get(base, f"/api/command-center?today={TODAY}")
    assert status == 200
    assert [section["section_id"] for section in command_center["sections"]] == ["my_priorities"]
    assert command_center["profile"]["owner_id"] == OWNER
    assert command_center["sections"][0]["effective_filters"] == {"owner_id": OWNER}
    assert _snapshot(vault) == before


def test_command_center_route_degrades_on_a_malformed_profile(route: tuple[str, GuiService], vault: Path) -> None:
    """A corrupt profile must not fail the read: the defaults render instead of a 400."""
    base, gui = route
    target = profile_path(gui.runtime_root)
    target.parent.mkdir(parents=True)
    target.write_text("{not valid json", encoding="utf-8")
    assert target.name == PROFILE_FILENAME

    status, content_type, payload = _get(base, f"/api/command-center?today={TODAY}")

    assert status == 200
    assert content_type == "application/json"
    assert [section["section_id"] for section in payload["sections"]] == list(KNOWN_SECTIONS)
    assert payload["profile"]["owner_id"] is None
    assert payload["profile"]["section_order"] == list(KNOWN_SECTIONS)
    # The degraded read is read-only: the corrupt file is left as-is for the save path to repair.
    assert target.read_text(encoding="utf-8") == "{not valid json"
