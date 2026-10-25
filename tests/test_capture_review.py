"""CC-05: capture review/apply (an inbox note) and dismiss."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.ingest import IngestError
from worksync.ingest.capture import capture_apply
from worksync.work.capture import CAPTURE_REL, capture_dismiss, capture_text
from worksync.work.processing import processing_status
from worksync.work.queue import QueueError, QueueStore

TOKEN = "capture-review-token"
INBOX = Path("7. Task Notes") / "Inbox"
TEXT = "Follow up with the vendor\nby Friday."


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    return workspace_fixture(tmp_path)


def _manifest(runtime: Path):
    return QueueStore(runtime, CAPTURE_REL).load()


def test_capture_apply_writes_a_raw_note_in_the_ingest_inbox(tmp_path: Path) -> None:
    vault, runtime = workspace_fixture(tmp_path)
    manifest = capture_text(runtime, TEXT)
    proposal = manifest.proposals[0]

    result = capture_apply(vault, runtime, reviewer="Myles", reason="Review captures", ids=(proposal.id,))

    assert result.committed is True
    assert result.applied == (proposal.id,)
    notes = list((vault / INBOX).glob("*.md"))
    assert len(notes) == 1
    content = notes[0].read_text(encoding="utf-8")
    assert content == TEXT + "\n"
    assert not content.startswith("---")
    stored = _manifest(runtime).proposals[0]
    assert stored.status == "applied"
    assert stored.reviewer == "Myles"
    assert stored.reason == "Review captures"


def workspace_fixture(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    (vault / INBOX).mkdir(parents=True)
    return vault, tmp_path / "var"


def test_capture_apply_is_one_shot(tmp_path: Path) -> None:
    vault, runtime = workspace_fixture(tmp_path)
    manifest = capture_text(runtime, TEXT)
    capture_apply(vault, runtime, reviewer="Myles", reason="Review", ids=(manifest.proposals[0].id,))

    with pytest.raises(QueueError) as error:
        capture_apply(vault, runtime, reviewer="Myles", reason="Review")

    assert error.value.code == "no_proposals"


def test_capture_apply_requires_a_reviewer_and_reason(tmp_path: Path) -> None:
    vault, runtime = workspace_fixture(tmp_path)
    capture_text(runtime, TEXT)

    with pytest.raises(QueueError):
        capture_apply(vault, runtime, reviewer="", reason="Review")
    with pytest.raises(QueueError):
        capture_apply(vault, runtime, reviewer="Myles", reason="")


def test_capture_apply_fails_closed_without_the_inbox(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "var"
    manifest = capture_text(runtime, TEXT)

    with pytest.raises(IngestError):
        capture_apply(vault, runtime, reviewer="Myles", reason="Review", ids=(manifest.proposals[0].id,))


def test_capture_apply_never_overwrites(tmp_path: Path) -> None:
    vault, runtime = workspace_fixture(tmp_path)
    existing = vault / INBOX / "Follow up with the vendor.md"
    existing.write_text("original\n", encoding="utf-8")
    manifest = capture_text(runtime, TEXT)

    capture_apply(vault, runtime, reviewer="Myles", reason="Review", ids=(manifest.proposals[0].id,))

    notes = sorted((vault / INBOX).glob("*.md"))
    assert existing.read_text(encoding="utf-8") == "original\n"
    assert len(notes) == 2


def test_capture_dismiss_writes_only_the_manifest(tmp_path: Path) -> None:
    vault, runtime = workspace_fixture(tmp_path)
    manifest = capture_text(runtime, TEXT)
    proposal = manifest.proposals[0]

    manifest = capture_dismiss(runtime, proposal.id, reviewer="Myles", reason="Noise")

    assert manifest.proposals[0].status == "dismissed"
    assert list((vault / INBOX).glob("*.md")) == []


def test_processing_status_lists_pending_captures(tmp_path: Path) -> None:
    _vault, runtime = workspace_fixture(tmp_path)
    capture_text(runtime, TEXT)

    payload = processing_status(runtime)

    capture = next(queue for queue in payload["queues"] if queue["id"] == "capture")
    assert capture["pending"] == 1
    assert capture["proposals"][0]["action"] == "capture"
    assert capture["proposals"][0]["fields"]["text"] == TEXT


def _post(base: str, path: str, payload: dict, token: str | None = TOKEN) -> tuple[int, dict]:
    request = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_capture_apply_and_dismiss_endpoints(tmp_path: Path) -> None:
    vault, runtime = workspace_fixture(tmp_path)
    capture_text(runtime, TEXT)
    proposal = _manifest(runtime).proposals[0]
    gui = GuiService(
        vault=vault,
        db_path=tmp_path / "index.sqlite3",
        runtime_root=runtime,
        vault_name="vault",
        reviewer="Myles",
    )
    server = create_server(gui, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _post(
            base,
            "/api/action/capture-apply",
            {"ids": [proposal.id], "reason": "Reviewed in the review panel", "confirmed": True},
        )
        assert status == 200
        assert payload["committed"] is True
        assert payload["applied"] == [proposal.id]
        assert list((vault / INBOX).glob("*.md"))

        capture_text(runtime, "A second thought")
        second = next(item for item in _manifest(runtime).proposals if item.status == "pending")
        status, payload = _post(base, "/api/action/capture-dismiss", {"id": second.id, "reason": "Noise"})
        assert status == 200
        assert payload["committed"] is False

        status, payload = _post(
            base, "/api/action/capture-apply", {"ids": [proposal.id], "reason": "Again"}, token=None
        )
        assert status == 401
        assert payload["error"] == "unauthorized"

        status, payload = _post(base, "/api/action/capture-apply", {"ids": [proposal.id], "reason": ""})
        assert status == 400
        assert payload["error"] == "missing_reason"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
