"""Spec 7 ticket 02: the GUI Duplicates review seam."""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from worksync.gui.actions import ActionError, dispatch_action
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server

TODAY = date(2026, 10, 6)
TOKEN = "dupes-token"
ACTIVE = "7. Task Notes/Active"


def _action(write_note: Callable[..., Path], vault: Path, name: str, title: str) -> Path:
    text = f"---\ntype: action\nstatus: open\n---\n# {title}\n"
    return write_note(vault, f"{ACTIVE}/{name}.md", text)


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    _action(write_note, vault, "A", "Call the vendor about the invoice")
    _action(write_note, vault, "B", "Call vendor about the invoice")


def _service(vault: Path, runtime: Path) -> GuiService:
    return GuiService(
        vault=vault, db_path=runtime / "index.sqlite3", runtime_root=runtime, vault_name="vault", reviewer="Myles"
    )


def test_duplicates_scan_returns_pairs(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    result = dispatch_action(_service(vault, tmp_path / "var"), "duplicates-scan", {}, today=TODAY)

    assert result["action"] == "duplicates-scan"
    assert result["committed"] is False
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["action"] == "merge"
    assert result["equivalent_cli"].startswith("worksync duplicates scan")


def test_duplicates_dismiss_requires_a_reason(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "duplicates-scan", {}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "duplicates-dismiss", {"id": proposal_id}, today=TODAY)
    assert excinfo.value.code == "missing_reason"
    assert excinfo.value.status == 400

    result = dispatch_action(service, "duplicates-dismiss", {"id": proposal_id, "reason": "keep both"}, today=TODAY)
    assert result["action"] == "duplicates-dismiss"
    assert result["proposals"][0]["status"] == "dismissed"
    assert result["equivalent_cli"].startswith("worksync duplicates dismiss")


def _post(base: str, path: str, payload: dict | None, token: str | None) -> tuple[int, bytes]:
    data = json.dumps(payload if payload is not None else {}).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture
def dup_server(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
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


def test_http_duplicates_scan(dup_server: tuple[str, GuiService]) -> None:
    base, _service = dup_server
    status, body = _post(base, "/api/action/duplicates-scan", {}, TOKEN)
    assert status == 200
    assert json.loads(body.decode("utf-8"))["proposals"]


def test_static_shell_exposes_the_duplicates_surface(dup_server: tuple[str, GuiService]) -> None:
    base, _service = dup_server
    with urllib.request.urlopen(base + "/app.js", timeout=5) as response:
        script = response.read().decode("utf-8")
    for action in ("duplicates-scan", "duplicates-dismiss"):
        assert action in script
