"""Spec 5 ticket 05: the GUI triage screen dispatches ingest actions over the seam."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from worksync.gui.actions import ActionError, dispatch_action
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.ingest import load_manifest

TODAY = date(2026, 10, 6)
TOKEN = "triage-token"
INBOX = "7. Task Notes/Inbox"
ACTIVE = "7. Task Notes/Active"
DROPPED = "7. Task Notes/Dropped"
PROJECT = "9. Project/Project - Alpha.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        PROJECT,
        "---\ntype: project\nstatus: active\nproject_id: alpha\n"
        'owners:\n  - "[[Myles]]"\npriority: P1\n---\n# Project - Alpha\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(vault, f"{INBOX}/Note.md", '---\nproject: "[[Project - Alpha]]"\n---\n# Call the vendor\n')


def _service(vault: Path, runtime: Path, *, reviewer: str | None = "Myles") -> GuiService:
    return GuiService(
        vault=vault, db_path=runtime / "index.sqlite3", runtime_root=runtime, vault_name="vault", reviewer=reviewer
    )


def test_ingest_scan_returns_proposals(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    result = dispatch_action(service, "ingest-scan", {"inbox": INBOX}, today=TODAY)

    assert result["state"] == "ok"
    assert result["action"] == "ingest-scan"
    assert result["committed"] is False
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["action"] == "action"
    assert result["proposals"][0]["fields"]["title"] == "Call the vendor"
    assert result["equivalent_cli"].startswith("worksync ingest scan")
    assert (tmp_path / "var" / "staging" / "ingest" / "manifest.json").is_file()


def test_ingest_apply_creates_the_action_and_echoes_the_change_set(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    dispatch_action(service, "ingest-scan", {"inbox": INBOX}, today=TODAY)

    result = dispatch_action(service, "ingest-apply", {"reason": "Triage"}, today=TODAY)

    assert result["action"] == "ingest-apply"
    assert result["committed"] is True
    assert result["reviewer"] == "Myles"
    assert result["changes"]
    assert result["equivalent_cli"].startswith("worksync ingest apply")
    assert (vault / ACTIVE / "Call the vendor.md").is_file()
    assert (vault / DROPPED / "Note.md").is_file()
    loaded = load_manifest(tmp_path / "var")
    assert loaded is not None and loaded.proposals[0].status == "applied"


def test_ingest_apply_applies_inline_overrides(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "ingest-scan", {"inbox": INBOX}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    result = dispatch_action(
        service,
        "ingest-apply",
        {
            "reason": "Triage",
            "overrides": {proposal_id: {"title": "Call the supplier", "priority": "p2", "owners": "Myles"}},
        },
        today=TODAY,
    )

    assert "--set" in result["equivalent_cli"]
    created = (vault / ACTIVE / "Call the supplier.md").read_text(encoding="utf-8")
    assert "priority: P2" in created
    assert "[[Myles]]" in created


def test_ingest_apply_rejects_an_unknown_override_field(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "ingest-scan", {"inbox": INBOX}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    with pytest.raises(ActionError) as excinfo:
        dispatch_action(
            service,
            "ingest-apply",
            {"reason": "Triage", "overrides": {proposal_id: {"bogus": "x"}}},
            today=TODAY,
        )
    assert excinfo.value.code == "invalid_override"
    assert excinfo.value.status == 400


def test_ingest_scan_uses_the_pinned_inbox_root(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{INBOX}/Note.md", "# Default task\n")
    write_note(vault, "Custom/Inbox/Note.md", "# Custom task\n")
    runtime = tmp_path / "var"
    service = GuiService(
        vault=vault,
        db_path=runtime / "index.sqlite3",
        runtime_root=runtime,
        vault_name="vault",
        reviewer="Myles",
        inbox_path="Custom/Inbox",
    )
    result = dispatch_action(service, "ingest-scan", {}, today=TODAY)
    assert [proposal["source_path"] for proposal in result["proposals"]] == ["Custom/Inbox/Note.md"]


def test_ingest_drop_requires_confirmation(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    write_note(vault, f"{INBOX}/Ref.md", "---\ntype: reference\n---\n# Reference material\n")
    service = _service(vault, tmp_path / "var")
    dispatch_action(service, "ingest-scan", {"inbox": INBOX}, today=TODAY)

    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "ingest-apply", {"reason": "Not work"}, today=TODAY)
    assert excinfo.value.code == "needs_confirmation"
    assert excinfo.value.status == 409
    assert (vault / f"{INBOX}/Ref.md").is_file()


def test_ingest_dismiss_requires_a_reason(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    scan = dispatch_action(service, "ingest-scan", {"inbox": INBOX}, today=TODAY)
    proposal_id = scan["proposals"][0]["id"]

    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "ingest-dismiss", {"id": proposal_id}, today=TODAY)
    assert excinfo.value.code == "missing_reason"
    assert excinfo.value.status == 400

    result = dispatch_action(service, "ingest-dismiss", {"id": proposal_id, "reason": "not now"}, today=TODAY)
    assert result["action"] == "ingest-dismiss"
    assert result["proposals"][0]["status"] == "dismissed"
    assert result["equivalent_cli"].startswith("worksync ingest dismiss")


def test_ingest_apply_without_a_manifest_is_conflict(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    service = _service(vault, tmp_path / "var")
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(service, "ingest-apply", {"reason": "Triage"}, today=TODAY)
    assert excinfo.value.code == "no_manifest"
    assert excinfo.value.status == 409


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
def triage_server(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
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


def test_http_ingest_scan_and_apply(triage_server: tuple[str, GuiService]) -> None:
    base, service = triage_server
    status, body = _post(base, "/api/action/ingest-scan", {"inbox": INBOX}, TOKEN)
    assert status == 200
    scan = json.loads(body.decode("utf-8"))
    assert scan["action"] == "ingest-scan"
    assert len(scan["proposals"]) == 1

    status, body = _post(base, "/api/action/ingest-apply", {"reason": "Triage"}, TOKEN)
    assert status == 200
    result = json.loads(body.decode("utf-8"))
    assert result["committed"] is True
    assert (service.vault / ACTIVE / "Call the vendor.md").is_file()


def test_http_ingest_drop_without_confirmation_is_conflict(triage_server: tuple[str, GuiService]) -> None:
    base, service = triage_server
    (service.vault / INBOX / "Ref.md").write_text("---\ntype: reference\n---\n# Reference\n", encoding="utf-8")
    assert _post(base, "/api/action/ingest-scan", {"inbox": INBOX}, TOKEN)[0] == 200

    status, body = _post(base, "/api/action/ingest-apply", {"reason": "Not work"}, TOKEN)
    assert status == 409
    assert json.loads(body.decode("utf-8"))["error"] == "needs_confirmation"


def test_http_ingest_action_requires_the_token(triage_server: tuple[str, GuiService]) -> None:
    base, _service = triage_server
    assert _post(base, "/api/action/ingest-scan", {"inbox": INBOX}, None)[0] == 401
    assert _post(base, "/api/action/ingest-scan", {"inbox": INBOX}, "wrong")[0] == 401


def test_static_shell_exposes_the_triage_surface(triage_server: tuple[str, GuiService]) -> None:
    base, _service = triage_server
    with urllib.request.urlopen(base + "/", timeout=5) as response:
        html = response.read().decode("utf-8")
    assert 'data-section="triage"' in html
    with urllib.request.urlopen(base + "/app.js", timeout=5) as response:
        script = response.read().decode("utf-8")
    for action in ("ingest-scan", "ingest-apply", "ingest-dismiss"):
        assert action in script
