"""WP-05: the GUI Identity review seam."""

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
TOKEN = "identity-token"
PEOPLE = "People"


def _person(
    write_note: Callable[..., Path],
    vault: Path,
    name: str,
    title: str,
    *,
    person_id: str,
    role: str | None = None,
    team: str | None = None,
    email: str | None = None,
) -> Path:
    lines = ["---", "type: person", "status: active", f"person_id: {person_id}"]
    if role:
        lines.append(f"role: {role}")
    if team:
        lines.append(f"team: {team}")
    if email:
        lines.append(f"email: {email}")
    lines.append("---")
    return write_note(vault, f"{PEOPLE}/{name}.md", "\n".join(lines) + f"\n# {title}\n")


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", role="PM", team="IT")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b", email="carlos@example.com")


def _service(vault: Path, runtime: Path) -> GuiService:
    return GuiService(
        vault=vault, db_path=runtime / "index.sqlite3", runtime_root=runtime, vault_name="vault", reviewer="Myles"
    )


def test_identity_scan_returns_pairs(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    result = dispatch_action(_service(vault, tmp_path / "var"), "identity-scan", {}, today=TODAY)

    assert result["action"] == "identity-scan"
    assert result["committed"] is False
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["id"].startswith("person-dup:")
    assert result["equivalent_cli"] == "worksync identity scan"


def test_identity_dismiss_requires_a_reason(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "identity-scan", {}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "identity-dismiss", {"id": proposal_id}, today=TODAY)
    assert excinfo.value.code == "missing_reason"
    assert excinfo.value.status == 400

    result = dispatch_action(service, "identity-dismiss", {"id": proposal_id, "reason": "keep both"}, today=TODAY)
    assert result["proposals"][0]["status"] == "dismissed"
    assert result["equivalent_cli"].startswith("worksync identity dismiss")


def test_identity_apply_requires_confirmation(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "identity-scan", {}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "identity-apply", {"id": proposal_id, "reason": "same person"}, today=TODAY)
    assert excinfo.value.code == "needs_confirmation"
    assert excinfo.value.status == 409


def test_identity_apply_merges_confirmed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "identity-scan", {}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    result = dispatch_action(
        service, "identity-apply", {"id": proposal_id, "reason": "same person", "confirmed": True}, today=TODAY
    )
    assert result["committed"] is True
    assert result["equivalent_cli"].startswith("worksync identity apply")
    assert "type: redirect" in (vault / f"{PEOPLE}/Carlos B.md").read_text(encoding="utf-8")


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
def identity_server(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
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


def test_http_identity_scan(identity_server: tuple[str, GuiService]) -> None:
    base, _service = identity_server
    status, body = _post(base, "/api/action/identity-scan", {}, TOKEN)
    assert status == 200
    assert json.loads(body.decode("utf-8"))["proposals"]


def test_static_shell_exposes_the_identity_surface(identity_server: tuple[str, GuiService]) -> None:
    base, _service = identity_server
    with urllib.request.urlopen(base + "/app.js", timeout=5) as response:
        script = response.read().decode("utf-8")
    for action in ("identity-scan", "identity-dismiss", "identity-apply"):
        assert action in script
