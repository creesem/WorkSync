"""Ticket 11: the tokenized loopback server serves the shell and the read-only API."""

from __future__ import annotations

import ast
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

import worksync
import worksync.work.capture as capture_module
from worksync.context import service
from worksync.context.association import index_associations
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.inventory.index import index_vault
from worksync.safety.files import sha256_bytes
from worksync.work.layout_profile import (
    DEFAULT_VIEW,
    KNOWN_SECTIONS,
    PROFILE_FILENAME,
    default_profile,
    profile_path,
    read_profile,
)

TODAY = "2026-02-01"
# A day before any attention trigger in the fixture vault (project review due 2026-01-10,
# action A1 due 2026-01-05), so Needs Attention is genuinely empty.
QUIET_TODAY = "2026-01-05"
TOKEN = "test-run-token"
PROJECT_NOTE = "9. Project/Project - Alpha.md"
A_PATH = "Actions/A1.md"
BLOCKED_TICKET = "Tickets/blocked.md"
BLOCKED_TICKET_NOTE = (
    '---\ntype: ticket\nstatus: blocked\nticket_id: blocked-ticket\nowners:\n  - "[[Myles]]"\n---\n# Blocked ticket\n'
)
OWNER_PERSON_NOTE = "---\ntype: person\nstatus: active\nperson_id: dana\n---\n# Dana\n"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: alpha\n'
        "next_review: 2026-01-10\nlast_reviewed: 2026-01-01\n---\n# Project - Alpha\n",
    )
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\n'
        'project: "[[Project - Alpha]]"\ndue: 2026-01-05\n---\n# Action One\n',
    )


@pytest.fixture
def gui_server(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
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


def _get(base: str, path: str, token: str | None = None) -> tuple[int, str, bytes]:
    request = urllib.request.Request(base + path)
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get_content_type(), exc.read()


def _json(body: bytes) -> dict:
    return json.loads(body.decode("utf-8"))


def _snapshot(root: Path) -> dict[Path, bytes]:
    """Every file under *root* keyed by its relative path, for write detectors."""
    return {path.relative_to(root): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _post(base: str, path: str, payload: dict | None, token: str | None = None) -> tuple[int, str, bytes]:
    data = json.dumps(payload if payload is not None else {}).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get_content_type(), exc.read()


def test_api_requires_the_per_run_token(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, content_type, body = _get(base, "/api/today")
    assert status == 401
    assert content_type == "application/json"
    assert _json(body)["error"] == "unauthorized"

    assert _get(base, "/api/today", "wrong-token")[0] == 401
    assert _get(base, "/api/today", TOKEN)[0] == 200


def test_today_endpoint_matches_the_retrieval_service(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, _content_type, body = _get(base, f"/api/today?today={TODAY}", TOKEN)
    assert status == 200
    payload = _json(body)
    assert payload["equivalent_cli"] == "worksync review today --today 2026-02-01"
    assert payload["attention"] == service.attention(gui.vault, date.fromisoformat(TODAY))


def test_every_section_carries_an_equivalent_command(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    endpoints = [
        f"/api/today?today={TODAY}",
        f"/api/command-center?today={TODAY}",
        f"/api/review?today={TODAY}",
        "/api/projects",
        f"/api/project?name=Alpha&today={TODAY}",
        f"/api/team?today={TODAY}",
        f"/api/person?name=Myles&today={TODAY}",
        f"/api/tickets?today={TODAY}",
        "/api/search?q=Alpha",
        "/api/health",
        "/api/settings",
    ]
    for endpoint in endpoints:
        status, _content_type, body = _get(base, endpoint, TOKEN)
        assert status == 200, endpoint
        assert _json(body)["equivalent_cli"].startswith("worksync "), endpoint


def test_gui_read_surface_does_not_write(gui_server: tuple[str, GuiService], vault: Path) -> None:
    base, gui = gui_server
    before_vault = {path: path.read_bytes() for path in vault.rglob("*.md")}
    before_db = gui.db_path.read_bytes()
    endpoints = [
        f"/api/today?today={TODAY}",
        f"/api/command-center?today={TODAY}",
        f"/api/review?today={TODAY}",
        "/api/projects",
        f"/api/project?name=Alpha&today={TODAY}",
        f"/api/team?today={TODAY}",
        f"/api/person?name=Myles&today={TODAY}",
        f"/api/tickets?today={TODAY}",
        "/api/search?q=Alpha",
        "/api/health",
        "/api/settings",
    ]
    for endpoint in endpoints:
        assert _get(base, endpoint, TOKEN)[0] == 200, endpoint
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before_vault
    assert gui.db_path.read_bytes() == before_db


def test_command_center_endpoint_returns_the_three_sections(
    gui_server: tuple[str, GuiService], vault: Path, write_note: Callable[..., Path]
) -> None:
    base, _gui = gui_server
    write_note(vault, "People/Dana.md", OWNER_PERSON_NOTE)
    write_note(vault, BLOCKED_TICKET, BLOCKED_TICKET_NOTE)

    status, content_type, body = _get(base, f"/api/command-center?today={TODAY}", TOKEN)

    assert status == 200
    assert content_type == "application/json"
    payload = _json(body)
    assert payload["equivalent_cli"] == "worksync command-center"
    assert payload["generated_at"]
    sections = payload["sections"]
    assert [section["section_id"] for section in sections] == [
        "needs_attention",
        "my_priorities",
        "since_last_check",
    ]
    for section in sections:
        assert section["state"], section["section_id"]
        assert isinstance(section["total_count"], int)
        assert isinstance(section["items"], list)
        assert section["total_count"] == len(section["items"]), section["section_id"]

    blocked = next(item for item in sections[0]["items"] if item["path"] == BLOCKED_TICKET)
    assert blocked["entity_type"] == "ticket"
    assert blocked["status"] == "blocked"
    assert blocked["label"] == "Blocked ticket"
    assert "blocked" in blocked["attention"]
    assert sections[0]["state"] == "items"
    assert "state" not in sections[0]["items"][0]  # state is a section-level derivation, not an item field


def test_command_center_states_are_distinct(
    gui_server: tuple[str, GuiService], vault: Path, write_note: Callable[..., Path]
) -> None:
    base, _gui = gui_server

    status, _content_type, body = _get(base, f"/api/command-center?today={QUIET_TODAY}", TOKEN)
    assert status == 200
    quiet = {section["section_id"]: section for section in _json(body)["sections"]}

    assert quiet["needs_attention"]["availability"] == "available"
    assert quiet["needs_attention"]["total_count"] == 0
    assert quiet["needs_attention"]["state"] == "empty"
    assert quiet["my_priorities"]["availability"] == "unavailable"
    assert quiet["my_priorities"]["error_state"] == "source_unavailable"
    assert quiet["my_priorities"]["state"] == "unavailable"
    assert quiet["since_last_check"]["availability"] == "unavailable"
    assert quiet["since_last_check"]["error_state"] == "no_checkpoint"
    assert quiet["since_last_check"]["state"] == "unavailable"

    write_note(vault, BLOCKED_TICKET, BLOCKED_TICKET_NOTE)
    status, _content_type, body = _get(base, f"/api/command-center?today={TODAY}", TOKEN)
    assert status == 200
    populated = {section["section_id"]: section for section in _json(body)["sections"]}

    assert populated["needs_attention"]["state"] == "items"
    assert populated["needs_attention"]["total_count"] >= 1
    assert any(item["path"] == BLOCKED_TICKET for item in populated["needs_attention"]["items"])


def test_command_center_degrades_on_a_malformed_checkpoint(
    gui_server: tuple[str, GuiService], vault: Path, write_note: Callable[..., Path]
) -> None:
    """A corrupt checkpoint must not brick the route: Since Last Check degrades, the rest renders."""
    base, gui = gui_server
    write_note(vault, BLOCKED_TICKET, BLOCKED_TICKET_NOTE)
    checkpoint = gui.runtime_root / "user_state" / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text("{not valid json", encoding="utf-8")

    status, content_type, body = _get(base, f"/api/command-center?today={TODAY}", TOKEN)

    assert status == 200
    assert content_type == "application/json"
    sections = {section["section_id"]: section for section in _json(body)["sections"]}
    assert sections["since_last_check"]["availability"] == "unavailable"
    assert sections["since_last_check"]["error_state"] == "no_checkpoint"
    assert sections["needs_attention"]["availability"] == "available"
    assert any(item["path"] == BLOCKED_TICKET for item in sections["needs_attention"]["items"])
    assert sections["my_priorities"]["availability"] == "unavailable"


def test_command_center_route_does_not_write(
    gui_server: tuple[str, GuiService], vault: Path, write_note: Callable[..., Path]
) -> None:
    """No Command Center section item writes to a canonical note (or anywhere else)."""
    base, gui = gui_server
    write_note(vault, BLOCKED_TICKET, BLOCKED_TICKET_NOTE)
    before = _snapshot(vault)

    assert _get(base, f"/api/command-center?today={TODAY}", TOKEN)[0] == 200

    assert _snapshot(vault) == before
    assert not (gui.runtime_root / "user_state").exists()


def test_action_endpoint_requires_the_token(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    assert _post(base, "/api/action/complete-action", {"path": A_PATH, "reason": "x"})[0] == 401
    assert _post(base, "/api/action/complete-action", {"path": A_PATH, "reason": "x"}, "wrong")[0] == 401


def test_action_endpoint_unknown_action_is_not_found(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, _content_type, body = _post(base, "/api/action/nope", {}, TOKEN)
    assert status == 404
    assert _json(body)["error"] == "unknown_action"


def test_action_endpoint_rejects_a_malformed_body(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    request = urllib.request.Request(base + "/api/action/complete-action", data=b"{not json", method="POST")
    request.add_header(TOKEN_HEADER, TOKEN)
    try:
        with urllib.request.urlopen(request, timeout=5):
            status = 200
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 400


def test_action_endpoint_completes_an_action(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, _content_type, body = _post(
        base, "/api/action/complete-action", {"path": A_PATH, "reason": "Finished"}, TOKEN
    )
    assert status == 200
    payload = _json(body)
    assert payload["state"] == "ok"
    assert payload["committed"] is True
    assert payload["equivalent_cli"].startswith("worksync task complete")
    assert payload["changes"] and payload["changes"][0]["reviewer"] == "Myles"
    assert "status: done" in (gui.vault / A_PATH).read_text(encoding="utf-8")


def test_action_endpoint_stale_sha_is_conflict(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    payload = {"path": A_PATH, "reason": "Finished", "expected": "deadbeef"}
    status, _content_type, body = _post(base, "/api/action/complete-action", payload, TOKEN)
    assert status == 409
    assert _json(body)["error"] == "stale_hash"
    assert "status: open" in (gui.vault / A_PATH).read_text(encoding="utf-8")


def test_action_endpoint_missing_reason_is_bad_request(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, _content_type, body = _post(base, "/api/action/complete-action", {"path": A_PATH}, TOKEN)
    assert status == 400
    assert _json(body)["error"] == "missing_reason"


def test_set_reviewer_action_persists(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, _content_type, body = _post(base, "/api/action/set-reviewer", {"reviewer": "Dana"}, TOKEN)
    assert status == 200
    assert _json(body)["reviewer"] == "Dana"
    assert (gui.runtime_root / "reviewer.json").is_file()


def test_save_layout_profile_rejects_an_invalid_payload(gui_server: tuple[str, GuiService]) -> None:
    """Ticket 15: a bad order/visibility/owner is a 400 and writes nothing at all."""
    base, gui = gui_server
    before = _snapshot(gui.vault)
    visible = {section: True for section in KNOWN_SECTIONS}
    invalid = [
        {"section_order": ["needs_attention", "my_priorities"], "visibility": visible, "owner_id": None},
        {
            "section_order": ["needs_attention", "needs_attention", "my_priorities"],
            "visibility": visible,
            "owner_id": None,
        },
        {"section_order": [*KNOWN_SECTIONS, "extra"], "visibility": visible, "owner_id": None},
        {"section_order": "needs_attention", "visibility": visible, "owner_id": None},
        {"section_order": list(KNOWN_SECTIONS), "visibility": {"needs_attention": True}, "owner_id": None},
        {
            "section_order": list(KNOWN_SECTIONS),
            "visibility": {"needs_attention": "yes", "my_priorities": True, "since_last_check": True},
            "owner_id": None,
        },
        {"section_order": list(KNOWN_SECTIONS), "owner_id": None},
        {"section_order": list(KNOWN_SECTIONS), "visibility": visible, "owner_id": 7},
        {"section_order": list(KNOWN_SECTIONS), "visibility": visible, "owner_id": None, "reset": "yes"},
    ]

    for payload in invalid:
        status, content_type, body = _post(base, "/api/action/save-layout-profile", payload, TOKEN)
        assert status == 400, payload
        assert content_type == "application/json", payload
        assert _json(body)["error"] == "bad_request", payload

    assert _snapshot(gui.vault) == before
    assert not profile_path(gui.runtime_root).exists()


def test_save_layout_profile_persists_order_visibility_and_owner(
    gui_server: tuple[str, GuiService],
) -> None:
    """Ticket 15: the action saves the layout and bumps the revision on each save."""
    base, gui = gui_server
    before = _snapshot(gui.vault)
    order = ["since_last_check", "needs_attention", "my_priorities"]
    visibility = {"needs_attention": False, "my_priorities": True, "since_last_check": True}

    status, content_type, body = _post(
        base,
        "/api/action/save-layout-profile",
        {"section_order": order, "visibility": visibility, "owner_id": "dana"},
        TOKEN,
    )

    assert status == 200
    assert content_type == "application/json"
    payload = _json(body)
    assert payload["state"] == "ok"
    assert payload["action"] == "save-layout-profile"
    assert payload["committed"] is True
    assert payload["equivalent_cli"] is None
    assert payload["profile"]["section_order"] == order
    assert payload["profile"]["visibility"] == visibility
    assert payload["profile"]["owner_id"] == "dana"
    assert payload["profile"]["default_view"] == DEFAULT_VIEW
    assert payload["profile"]["revision"] == 2
    assert payload["profile"]["updated_at"]

    stored = read_profile(gui.runtime_root)
    assert stored.section_order == tuple(order)
    assert stored.visibility == visibility
    assert stored.owner_id == "dana"
    assert stored.revision == 2

    # A second save reads the stored revision back, so the revision keeps climbing.
    swapped = ["needs_attention", "since_last_check", "my_priorities"]
    status, _content_type, body = _post(
        base,
        "/api/action/save-layout-profile",
        {"section_order": swapped, "visibility": visibility, "owner_id": "dana"},
        TOKEN,
    )
    assert status == 200
    assert _json(body)["profile"]["revision"] == 3
    assert read_profile(gui.runtime_root).section_order == tuple(swapped)

    # No canonical write: the vault is byte-identical and the only user_state file is the
    # profile itself (the journal and backups live outside it).
    assert _snapshot(gui.vault) == before
    user_state = gui.runtime_root / "user_state"
    assert [path.name for path in user_state.iterdir()] == [PROFILE_FILENAME]


def test_save_layout_profile_reset_restores_the_defaults(
    gui_server: tuple[str, GuiService],
) -> None:
    """Ticket 15: ``reset`` writes the default profile (revision 1) and no note."""
    base, gui = gui_server
    custom = {
        "section_order": ["since_last_check", "needs_attention", "my_priorities"],
        "visibility": {"needs_attention": False, "my_priorities": True, "since_last_check": True},
        "owner_id": "dana",
    }
    assert _post(base, "/api/action/save-layout-profile", custom, TOKEN)[0] == 200
    before = _snapshot(gui.vault)

    status, content_type, body = _post(base, "/api/action/save-layout-profile", {"reset": True}, TOKEN)

    assert status == 200
    assert content_type == "application/json"
    payload = _json(body)
    assert payload["state"] == "ok"
    assert payload["action"] == "save-layout-profile"
    assert payload["committed"] is True
    expected = default_profile()
    assert payload["profile"]["section_order"] == list(expected.section_order)
    assert payload["profile"]["visibility"] == expected.visibility
    assert payload["profile"]["owner_id"] is None
    assert payload["profile"]["revision"] == expected.revision
    assert payload["profile"]["updated_at"]

    stored = read_profile(gui.runtime_root)
    assert stored.owner_id is None
    assert stored.section_order == KNOWN_SECTIONS
    assert stored.visibility == {section: True for section in KNOWN_SECTIONS}
    assert stored.revision == 1
    assert _snapshot(gui.vault) == before


def test_save_layout_profile_repairs_a_corrupt_profile(
    gui_server: tuple[str, GuiService],
) -> None:
    """A corrupt profile degrades the read; the next save replaces it instead of failing."""
    base, gui = gui_server
    target = profile_path(gui.runtime_root)
    target.parent.mkdir(parents=True)
    target.write_text("{not valid json", encoding="utf-8")
    before = _snapshot(gui.vault)

    status, _content_type, body = _post(
        base,
        "/api/action/save-layout-profile",
        {
            "section_order": ["my_priorities", "needs_attention", "since_last_check"],
            "visibility": {section: True for section in KNOWN_SECTIONS},
            "owner_id": "dana",
        },
        TOKEN,
    )

    assert status == 200
    assert _json(body)["committed"] is True
    assert read_profile(gui.runtime_root).owner_id == "dana"
    assert _snapshot(gui.vault) == before


def test_capture_action_requires_text(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    for payload in ({}, {"text": ""}, {"text": "   "}):
        status, _content_type, body = _post(base, "/api/action/capture", payload, TOKEN)
        assert status == 400, payload
        assert _json(body)["error"] == "bad_request"


def test_capture_action_queues_a_proposal_without_touching_the_vault(
    gui_server: tuple[str, GuiService],
) -> None:
    base, gui = gui_server
    text = "Follow up with Dana about the Alpha handoff."
    before = _snapshot(gui.vault)

    status, _content_type, body = _post(base, "/api/action/capture", {"text": text}, TOKEN)

    assert status == 200
    payload = _json(body)
    assert payload["state"] == "ok"
    assert payload["action"] == "capture"
    assert payload["committed"] is False
    assert payload["equivalent_cli"] is None
    proposal = payload["proposal"]
    digest = sha256_bytes(text.encode("utf-8"))
    assert proposal["id"] == digest[:12]
    assert proposal["action"] == "capture"
    assert proposal["source_path"] == ""
    assert proposal["source_sha256"] == digest
    assert proposal["fields"] == {"text": text}
    assert proposal["provenance"] == ["capture"]
    assert proposal["status"] == "pending"

    assert _snapshot(gui.vault) == before
    assert (gui.runtime_root / "staging" / "capture" / "manifest.json").is_file()


def test_capture_action_maps_a_stale_queue_to_conflict(
    gui_server: tuple[str, GuiService], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _gui = gui_server

    def stale_save(self, manifest, *, expected=None, expected_absent=False):
        raise RuntimeError("File changed during processing.")

    monkeypatch.setattr(capture_module.QueueStore, "save", stale_save)

    status, content_type, body = _post(base, "/api/action/capture", {"text": "Race"}, TOKEN)

    assert status == 409
    assert content_type == "application/json"
    assert _json(body)["error"] == "stale_hash"
    assert _json(body)["message"]


def test_capture_action_reports_a_failed_staging_write_as_a_server_error(
    gui_server: tuple[str, GuiService], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filesystem failure is a 500 with a message, not a dropped connection or a 409 retry."""
    base, _gui = gui_server

    def failing_save(self, manifest, *, expected=None, expected_absent=False):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(capture_module.QueueStore, "save", failing_save)

    status, content_type, body = _post(base, "/api/action/capture", {"text": "Notice me"}, TOKEN)

    assert status == 500
    assert content_type == "application/json"
    assert _json(body)["error"] == "write_failed"
    assert _json(body)["message"]


def test_capture_action_reports_a_wrong_typed_manifest_as_a_server_error(
    gui_server: tuple[str, GuiService],
) -> None:
    """A manifest that parses but has wrong-typed fields is a 500, not a dropped connection."""
    base, gui = gui_server
    manifest = gui.runtime_root / "staging" / "capture" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    raw = '{"version": "not-a-number"}'
    manifest.write_text(raw, encoding="utf-8")

    status, content_type, body = _post(base, "/api/action/capture", {"text": "Still here"}, TOKEN)

    assert status == 500
    assert content_type == "application/json"
    assert _json(body)["error"] == "corrupt_manifest"
    assert _json(body)["message"]
    assert manifest.read_text(encoding="utf-8") == raw


def test_action_endpoint_applies_a_batch(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    second = gui.vault / "Actions/A2.md"
    second.write_text("---\ntype: action\nstatus: open\n---\n# Action Two\n", encoding="utf-8")
    payload = {
        "reason": "Batch tidy",
        "items": [
            {"action": "complete-action", "path": A_PATH},
            {"action": "complete-action", "path": "Actions/A2.md"},
        ],
    }
    status, _content_type, body = _post(base, "/api/action/apply-batch", payload, TOKEN)
    assert status == 200
    result = _json(body)
    assert result["committed"] is True
    assert len(result["changes"]) == 2
    assert "status: done" in (gui.vault / A_PATH).read_text(encoding="utf-8")
    assert "status: done" in second.read_text(encoding="utf-8")


def test_action_endpoint_batch_rolls_back_on_a_stale_intent(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    second = gui.vault / "Actions/A2.md"
    second.write_text("---\ntype: action\nstatus: open\n---\n# Action Two\n", encoding="utf-8")
    payload = {
        "reason": "Batch tidy",
        "items": [
            {"action": "complete-action", "path": A_PATH},
            {"action": "complete-action", "path": "Actions/A2.md", "expected": "deadbeef"},
        ],
    }
    status, _content_type, body = _post(base, "/api/action/apply-batch", payload, TOKEN)
    assert status == 409
    assert _json(body)["error"] == "stale_hash"
    assert "status: open" in (gui.vault / A_PATH).read_text(encoding="utf-8")
    assert "status: open" in second.read_text(encoding="utf-8")


def test_health_endpoint_surfaces_validation_issues(
    gui_server: tuple[str, GuiService], vault: Path, write_note: Callable[..., Path]
) -> None:
    base, _gui = gui_server
    write_note(vault, "Bad.md", "---\ntype: project\n---\n# Bad\n")
    status, _content_type, body = _get(base, "/api/health", TOKEN)
    assert status == 200
    payload = _json(body)
    assert payload["equivalent_cli"] == "worksync health"
    assert payload["errors"] >= 1
    assert any(issue["path"] == "Bad.md" for issue in payload["issues"])


def test_missing_parameter_and_unknown_endpoint_fail_cleanly(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    assert _get(base, "/api/project", TOKEN)[0] == 400
    assert _get(base, "/api/today?today=not-a-date", TOKEN)[0] == 400
    status, _content_type, body = _get(base, "/api/nope", TOKEN)
    assert status == 404
    assert _json(body)["error"] == "not_found"


def test_static_responses_are_never_cached(gui_server: tuple[str, GuiService]) -> None:
    """The shell and assets change during development; the browser must not cache them."""
    base, _gui = gui_server
    with urllib.request.urlopen(base + "/app.js", timeout=5) as response:
        assert response.headers.get("Cache-Control") == "no-store"


def test_static_shell_is_self_contained_and_injects_the_token(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, content_type, body = _get(base, "/")
    assert status == 200
    assert content_type == "text/html"
    text = body.decode("utf-8")
    assert f'window.__GUI_TOKEN__ = "{TOKEN}"' in text
    assert 'src="http' not in text
    assert 'href="http' not in text

    # Ticket 10: the Command Center is the rail's default entry and the topbar carries the
    # back/forward controls; no "task" noun (ADR-0002) appears in the shell.
    assert 'data-section="command-center"' in text
    assert 'id="back"' in text
    assert 'id="forward"' in text
    assert "task" not in text.lower()

    # Ticket 12: a single-line capture bar sits at the bottom of every section.
    assert 'class="capture-bar"' in text
    assert 'id="capture-input"' in text
    assert 'id="capture-submit"' in text

    assert _get(base, "/styles.css", TOKEN)[0] == 200
    css = _get(base, "/styles.css", TOKEN)[2].decode("utf-8")
    # Ticket 12: one shared height keeps the fixed bar, the detail pane's bottom edge, and the
    # content column's bottom padding from drifting apart.
    assert "--bar-height: 3.4rem" in css
    assert css.count("3.4rem") == 1
    assert "padding-bottom: var(--bar-height)" in css
    assert "bottom: var(--bar-height)" in css
    assert "min-height: var(--bar-height)" in css

    app_js = _get(base, "/app.js", TOKEN)[2].decode("utf-8")
    assert 'postAction("capture"' in app_js
    # Ticket 12: nothing reads the capture manifest yet (review/apply is CC-05), so the bar
    # reports only that the text was captured, and reports a decided proposal's own status.
    assert '"Captured"' in app_js
    assert "Already captured (" in app_js
    assert "to review queue" not in app_js
    assert "if (captureInFlight) return;" in app_js  # one capture in flight at a time


def test_static_shell_pins_the_detail_pane_and_canonical_link(gui_server: tuple[str, GuiService]) -> None:
    """Ticket 11: the on-demand detail pane and the client-side obsidian:// link are pinned.

    No JS test harness exists, so this mirrors Block 3's static-shell assertion for the rail:
    the markup and the canonical-link construction are asserted by string, the behaviour is
    verified by hand.
    """
    base, _gui = gui_server
    html = _get(base, "/")[2].decode("utf-8")
    assert 'id="detail"' in html
    assert 'class="detail"' in html
    assert 'id="detail" aria-label="Item detail" hidden' in html  # on demand, not always visible
    assert "task" not in html.lower()

    app_js = _get(base, "/app.js", TOKEN)[2].decode("utf-8")
    assert "obsidian://open" in app_js
    assert "Open in Obsidian" in app_js
    assert "data-cc-item" in app_js  # Command Center rows are selectable
    assert "vaultNameOnce" in app_js  # the vault name is cached from /api/settings
    assert "detailGeneration" in app_js  # a selection that lost a section change bails
    assert "task" not in app_js.lower()


def test_static_shell_pins_the_layout_controls(gui_server: tuple[str, GuiService]) -> None:
    """Ticket 15: the "Me" picker, the hide/show and reorder buttons, and reset are served.

    No JS test harness exists, so the markup and the action wiring are asserted by string;
    the behaviour is verified by hand.
    """
    base, _gui = gui_server
    html = _get(base, "/")[2].decode("utf-8")
    assert 'id="layout-bar"' in html
    assert 'id="me-select"' in html
    assert 'aria-label="Me"' in html
    assert 'id="layout-sections"' in html
    assert "Reset layout" in html
    assert "task" not in html.lower()

    app_js = _get(base, "/app.js", TOKEN)[2].decode("utf-8")
    assert 'postAction("save-layout-profile"' in app_js
    assert "data-layout-visibility" in app_js  # per-section hide/show
    assert "data-layout-move" in app_js  # per-section up/down reorder
    assert "layout-reset" in app_js
    assert "state.profile" in app_js  # the route's profile is the controls' source
    assert "task" not in app_js.lower()

    css = _get(base, "/styles.css", TOKEN)[2].decode("utf-8")
    assert ".layout-bar" in css


def test_server_refuses_a_non_loopback_host(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    gui = GuiService(vault=vault, db_path=tmp_path / "i.sqlite3", runtime_root=tmp_path / "var", vault_name="vault")
    with pytest.raises(ValueError):
        create_server(gui, TOKEN, host="0.0.0.0")


def _module_index() -> dict[str, Path]:
    src = Path(worksync.__file__).parent.parent
    modules: dict[str, Path] = {}
    for path in (src / "worksync").rglob("*.py"):
        parts = list(path.relative_to(src).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    return modules


def _imports_of(module_name: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module_name if path.name == "__init__.py" else module_name.rsplit(".", 1)[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
            else:
                base = node.module or ""
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _closure(entries: tuple[str, ...], modules: dict[str, Path]) -> set[str]:
    seen: set[str] = set()
    stack = list(entries)
    while stack:
        name = stack.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        for imported in _imports_of(name, modules[name]):
            for candidate in sorted(modules, key=len, reverse=True):
                if imported == candidate or imported.startswith(candidate + "."):
                    if candidate not in seen:
                        stack.append(candidate)
                    break
    return seen


def _closure_targets(closure: set[str], modules: dict[str, Path]) -> set[str]:
    targets: set[str] = set()
    for name in closure:
        targets |= _imports_of(name, modules[name])
    return targets


def test_gui_read_seam_import_closure_reaches_no_write_helper() -> None:
    modules = _module_index()
    targets = _closure_targets(_closure(("worksync.gui.controller",), modules), modules)
    assert "worksync.inventory.index.connect" not in targets
    assert not any(target == "worksync.safety" or target.startswith("worksync.safety.") for target in targets)


def test_gui_write_seam_reaches_the_gateway() -> None:
    modules = _module_index()
    closure = _closure(("worksync.gui.actions",), modules)
    targets = _closure_targets(closure, modules)
    assert "worksync.safety.gateway" in targets
    assert not any(name.startswith("worksync.context") for name in closure)
    assert not any(name.startswith("worksync.inventory.index") for name in closure)
    assert "sqlite3" not in targets
