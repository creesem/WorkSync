"""Spec 7 ticket 04: the GUI Clarification review seam."""

from __future__ import annotations

import threading
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from worksync.gui.actions import ActionError, dispatch_action
from worksync.gui.controller import GuiService
from worksync.gui.server import create_server

TODAY = date(2026, 10, 6)
TOKEN = "clarify-token"
ACTIVE = "7. Task Notes/Active"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "9. Project/Project - Alpha.md", "---\ntype: project\nstatus: active\n---\n# Project - Alpha\n")
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(vault, f"{ACTIVE}/NoOwner.md", "---\ntype: action\nstatus: open\n---\n# Call the vendor\n")


def _service(vault: Path, runtime: Path) -> GuiService:
    return GuiService(
        vault=vault, db_path=runtime / "index.sqlite3", runtime_root=runtime, vault_name="vault", reviewer="Myles"
    )


def test_clarification_scan_returns_items(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    result = dispatch_action(_service(vault, tmp_path / "var"), "clarification-scan", {}, today=TODAY)

    assert result["action"] == "clarification-scan"
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["provenance"]
    assert result["equivalent_cli"].startswith("worksync clarification scan")


def test_clarification_apply_archive_requires_confirmation(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "clarification-scan", {}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    with pytest.raises(ActionError) as excinfo:
        dispatch_action(
            service,
            "clarification-apply",
            {"reason": "Not work", "ids": [proposal_id], "overrides": {proposal_id: {"resolution": "archive"}}},
            today=TODAY,
        )
    assert excinfo.value.code == "needs_confirmation"
    assert excinfo.value.status == 409


def test_clarification_apply_archive_confirmed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "clarification-scan", {}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    result = dispatch_action(
        service,
        "clarification-apply",
        {
            "reason": "Not work",
            "ids": [proposal_id],
            "overrides": {proposal_id: {"resolution": "archive"}},
            "confirmed": True,
        },
        today=TODAY,
    )
    assert result["committed"] is True
    assert result["equivalent_cli"].startswith("worksync clarification apply")


def test_clarification_dismiss_requires_a_reason(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "clarification-scan", {}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "clarification-dismiss", {"id": proposal_id}, today=TODAY)
    assert excinfo.value.code == "missing_reason"
    assert excinfo.value.status == 400

    result = dispatch_action(service, "clarification-dismiss", {"id": proposal_id, "reason": "fine"}, today=TODAY)
    assert result["proposals"][0]["status"] == "dismissed"
    assert result["equivalent_cli"].startswith("worksync clarification dismiss")


@pytest.fixture
def clarify_server(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    server = create_server(service, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", service
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_static_shell_exposes_the_clarification_surface(clarify_server: tuple[str, GuiService]) -> None:
    base, _service = clarify_server
    with urllib.request.urlopen(base + "/app.js", timeout=5) as response:
        script = response.read().decode("utf-8")
    for action in ("clarification-scan", "clarification-apply", "clarification-dismiss"):
        assert action in script
