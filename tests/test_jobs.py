"""4b: durable background jobs (queue, run, dedupe, restart, failure, API)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from worksync.gui.controller import GuiService
from worksync.gui.jobs import JobError, JobRunner
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.work.jobs import job_path, list_jobs, read_job

TOKEN = "jobs-token"


def _gui(tmp_path: Path) -> GuiService:
    vault = tmp_path / "vault"
    vault.mkdir()
    return GuiService(
        vault=vault,
        db_path=tmp_path / "index.sqlite3",
        runtime_root=tmp_path / "var",
        vault_name="vault",
        reviewer="Myles",
    )


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fake_execute(runtime: Path):
    def execute(kind: str) -> dict:
        if kind == "ingest-scan":
            _write(
                runtime / "staging" / "ingest" / "manifest.json",
                {"version": 1, "proposals": [{"id": "p1", "status": "pending"}]},
            )
            return {"scan_token": "tok", "proposals": [{"id": "p1"}]}
        if kind == "duplicates-scan":
            return {"scan_token": "tok", "proposals": []}
        return {"summary": {"pulled": [], "skipped": []}}

    return execute


def _wait_status(runtime: Path, job_id: str, statuses: set[str], timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = read_job(runtime, job_id)
        if job is not None and job.get("status") in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {statuses}: {read_job(runtime, job_id)}")


def _runner(gui: GuiService, execute=None) -> JobRunner:
    runner = JobRunner(gui, execute=execute or _fake_execute(gui.runtime_root))
    runner.start()
    return runner


def test_a_scan_job_runs_to_awaiting_review(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    runner = _runner(gui)
    try:
        job = runner.submit("ingest-scan")
        assert job["status"] == "queued"
        done = _wait_status(gui.runtime_root, job["id"], {"awaiting_review", "completed", "failed"})
        assert done["status"] == "awaiting_review"
        assert done["result"]["pending"] == 1
        assert done["result"]["proposals"] == 1
        assert done["attempts"] == 1
    finally:
        runner.stop()


def test_a_scan_with_no_proposals_completes(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    runner = _runner(gui)
    try:
        job = runner.submit("duplicates-scan")
        done = _wait_status(gui.runtime_root, job["id"], {"completed", "failed"})
        assert done["status"] == "completed"
        assert done["result"]["pending"] == 0
    finally:
        runner.stop()


def test_an_active_job_is_deduplicated(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def blocked(kind: str) -> dict:
        started.set()
        release.wait(5)
        return {"scan_token": "tok", "proposals": []}

    runner = _runner(gui, execute=blocked)
    try:
        first = runner.submit("ingest-scan")
        assert started.wait(2)
        second = runner.submit("ingest-scan")
        assert second["id"] == first["id"]
        release.set()
        _wait_status(gui.runtime_root, first["id"], {"completed", "failed"})
    finally:
        release.set()
        runner.stop()


def test_a_failing_job_records_the_failure(tmp_path: Path) -> None:
    gui = _gui(tmp_path)

    def boom(kind: str) -> dict:
        raise RuntimeError("scan exploded")

    runner = _runner(gui, execute=boom)
    try:
        job = runner.submit("ingest-scan")
        done = _wait_status(gui.runtime_root, job["id"], {"failed"})
        assert "scan exploded" in done["error"]
        assert done["finished_at"]
    finally:
        runner.stop()


def test_an_interrupted_job_is_requeued_on_start(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    job_id = "job-interrupted"
    _write(
        job_path(gui.runtime_root, job_id),
        {
            "version": 1,
            "id": job_id,
            "kind": "duplicates-scan",
            "status": "running",
            "created_at": "2026-02-01T09:00:00+00:00",
            "started_at": "2026-02-01T09:00:01+00:00",
            "finished_at": None,
            "attempts": 1,
            "error": None,
            "result": None,
            "idempotency_key": None,
        },
    )
    runner = _runner(gui)
    try:
        done = _wait_status(gui.runtime_root, job_id, {"completed", "failed"})
        assert done["status"] == "completed"
        assert done["attempts"] == 2
    finally:
        runner.stop()


def test_a_repeatedly_interrupted_job_fails(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    job_id = "job-exhausted"
    _write(
        job_path(gui.runtime_root, job_id),
        {
            "version": 1,
            "id": job_id,
            "kind": "duplicates-scan",
            "status": "running",
            "created_at": "2026-02-01T09:00:00+00:00",
            "started_at": "2026-02-01T09:00:01+00:00",
            "finished_at": None,
            "attempts": 2,
            "error": None,
            "result": None,
            "idempotency_key": None,
        },
    )
    runner = _runner(gui)
    try:
        done = _wait_status(gui.runtime_root, job_id, {"failed"})
        assert "Interrupted repeatedly" in done["error"]
    finally:
        runner.stop()


def test_unknown_job_kinds_are_rejected(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    runner = JobRunner(gui, execute=_fake_execute(gui.runtime_root))
    with pytest.raises(JobError):
        runner.submit("not-a-job")


def test_job_records_reject_path_shaped_ids(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    assert read_job(gui.runtime_root, "../escape") is None
    assert list_jobs(gui.runtime_root) == []


def _get(base: str, path: str, token: str | None = TOKEN) -> tuple[int, dict]:
    request = urllib.request.Request(base + path)
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


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


def test_the_job_api_queues_and_lists_a_job(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    runner = _runner(gui)
    server = create_server(gui, TOKEN, port=0, jobs=runner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _post(base, "/api/jobs", {"kind": "ingest-scan"})
        assert status == 202
        job_id = payload["job"]["id"]
        _wait_status(gui.runtime_root, job_id, {"awaiting_review", "completed", "failed"})

        status, processing = _get(base, "/api/processing")
        assert status == 200
        assert any(job["id"] == job_id for job in processing["jobs"])
        assert processing["jobs"][0]["status"] in {"awaiting_review", "completed"}

        status, payload = _post(base, "/api/jobs", {"kind": "nope"})
        assert status == 400
        assert payload["error"] == "bad_request"

        status, payload = _post(base, "/api/jobs", {"kind": "ingest-scan"}, token=None)
        assert status == 401
        assert payload["error"] == "unauthorized"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        runner.stop()


def test_the_job_api_is_unavailable_without_a_runner(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    server = create_server(gui, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _post(base, "/api/jobs", {"kind": "ingest-scan"})
        assert status == 503
        assert payload["error"] == "jobs_unavailable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
