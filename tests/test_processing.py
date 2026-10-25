"""4a: read-only operational status (queues, Krisp sync, recent activity)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.work import queue
from worksync.work.processing import PROPOSAL_STATUSES, processing_status

TOKEN = "processing-token"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def processing_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "var"
    _write(
        runtime / "staging" / "capture" / "manifest.json",
        {
            "version": 1,
            "updated_at": "2026-10-24T09:00:00+00:00",
            "proposals": [
                {"id": "c1", "status": "pending"},
                {"id": "c2", "status": "pending"},
                {"id": "c3", "status": "applied"},
            ],
        },
    )
    _write(
        runtime / "staging" / "ingest" / "manifest.json",
        {"version": 1, "proposals": [{"id": "i1", "status": "pending"}]},
    )
    (runtime / "staging" / "duplicates").mkdir(parents=True)
    (runtime / "staging" / "duplicates" / "manifest.json").write_text("{not json", encoding="utf-8")
    _write(
        runtime / "krisp" / "sync-status.json",
        {
            "last_attempt_at": "2026-10-24T08:00:00+00:00",
            "last_success_at": "2026-10-24T07:00:00+00:00",
            "failed": [{"meeting": "m1"}, {"meeting": "m2"}],
        },
    )
    month = datetime.now(UTC).strftime("%Y-%m")
    events = [
        {
            "timestamp": "2026-10-24T10:00:00+00:00",
            "type": "write",
            "verb": "save_override",
            "class": "user_state",
            "reviewer": "Myles",
            "reason": "Save pin override for a1",
            "result": "committed",
            "path": "runtime/user_state/overrides.json",
        },
        {
            "timestamp": "2026-10-24T10:01:00+00:00",
            "type": "write",
            "verb": "save_layout",
            "class": "user_state",
            "reviewer": "Myles",
            "reason": "Save the Command Center layout profile",
            "result": "committed",
            "path": "runtime/user_state/layout_profile.json",
        },
        {
            "timestamp": "2026-10-24T10:02:00+00:00",
            "type": "write",
            "verb": "capture",
            "class": "derived",
            "reviewer": None,
            "reason": "",
            "result": "committed",
        },
    ]
    (runtime / "activity").mkdir(parents=True)
    (runtime / "activity" / f"{month}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )
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
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", runtime
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _get(base: str, path: str, token: str | None = TOKEN) -> tuple[int, dict]:
    request = urllib.request.Request(base + path)
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_processing_status_reports_queues_krisp_and_activity(
    processing_server: tuple[str, Path],
) -> None:
    base, _runtime = processing_server

    status, payload = _get(base, "/api/processing")

    assert status == 200
    assert payload["contract_version"] == 1
    queues = {item["id"]: item for item in payload["queues"]}
    assert queues["capture"]["pending"] == 2
    assert queues["capture"]["total"] == 3
    assert queues["capture"]["by_status"]["applied"] == 1
    assert queues["ingest"]["pending"] == 1
    assert queues["duplicates"]["error"] == "unreadable"
    assert queues["identity"]["total"] == 0
    assert payload["krisp"]["last_success_at"] == "2026-10-24T07:00:00+00:00"
    assert payload["krisp"]["failed_count"] == 2
    assert [event["verb"] for event in payload["activity"]] == ["capture", "save_layout", "save_override"]
    assert all("path" not in event for event in payload["activity"])


def test_processing_status_requires_the_token(processing_server: tuple[str, Path]) -> None:
    base, _runtime = processing_server

    status, payload = _get(base, "/api/processing", token=None)

    assert status == 401
    assert payload["error"] == "unauthorized"


def test_processing_status_is_read_only(processing_server: tuple[str, Path]) -> None:
    base, runtime = processing_server
    before = _snapshot(runtime)

    _get(base, "/api/processing")

    assert _snapshot(runtime) == before


def test_processing_status_payload_does_not_need_the_vault(processing_server: tuple[str, Path]) -> None:
    base, runtime = processing_server

    payload = processing_status(runtime)

    assert [item["id"] for item in payload["queues"]] == [
        "capture",
        "ingest",
        "duplicates",
        "identity",
        "clarification",
    ]


def test_processing_hides_legacy_queue_proposals_and_reports_generation(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _write(
        runtime / "user_state" / "work_generation.json",
        {
            "schema_version": 1,
            "generation": 2,
            "legacy_action_ids": ["action-old"],
            "legacy_action_paths": ["Actions/Old.md"],
            "legacy_ticket_ids": [],
            "legacy_ticket_paths": [],
            "cutover_at": "2026-10-24T09:00:00+00:00",
            "reviewer": "Myles",
            "reason": "Start clean",
        },
    )
    _write(
        runtime / "staging" / "duplicates" / "manifest.json",
        {
            "version": 1,
            "proposals": [
                {
                    "id": "old-1",
                    "status": "pending",
                    "source_path": "Actions/Old.md",
                    "target_path": "Actions/Other.md",
                },
                {
                    "id": "live-1",
                    "status": "pending",
                    "source_path": "Actions/Live.md",
                    "target_path": "Actions/Other.md",
                },
            ],
        },
    )

    payload = processing_status(runtime)

    duplicates = next(item for item in payload["queues"] if item["id"] == "duplicates")
    assert duplicates["pending"] == 1
    assert [proposal["id"] for proposal in duplicates["proposals"]] == ["live-1"]
    assert payload["generation"] == {
        "generation": 2,
        "cutover_at": "2026-10-24T09:00:00+00:00",
        "legacy_action_count": 1,
        "legacy_ticket_count": 0,
        "error": None,
    }


def test_processing_degrades_when_the_generation_record_is_corrupt(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    path = runtime / "user_state" / "work_generation.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    payload = processing_status(runtime)

    assert payload["generation"]["error"] == "unreadable"
    assert payload["generation"]["legacy_action_count"] == 0


def test_processing_lists_both_sides_and_evidence_for_duplicates(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _write(
        runtime / "staging" / "duplicates" / "manifest.json",
        {
            "version": 1,
            "updated_at": "2026-10-24T09:00:00+00:00",
            "proposals": [
                {
                    "id": "pair-1",
                    "action": "merge",
                    "status": "pending",
                    "source_path": "Actions/Duplicate.md",
                    "target_path": "Actions/Canonical.md",
                    "source_sha256": "a" * 64,
                    "target_sha256": "b" * 64,
                    "fields": {
                        "canonical_title": "Canonical",
                        "duplicate_title": "Duplicate",
                        "similarity": "0.9100",
                    },
                    "confidence": 0.91,
                    "provenance": ["same title", "shared project"],
                }
            ],
        },
    )

    payload = processing_status(runtime)

    duplicates = next(item for item in payload["queues"] if item["id"] == "duplicates")
    proposal = duplicates["proposals"][0]
    assert proposal["source_path"] == "Actions/Duplicate.md"
    assert proposal["target_path"] == "Actions/Canonical.md"
    assert proposal["confidence"] == 0.91
    assert proposal["provenance"] == ["same title", "shared project"]


def test_proposal_status_vocabulary_matches_the_queue_contract() -> None:
    assert PROPOSAL_STATUSES == queue.PROPOSAL_STATUSES
