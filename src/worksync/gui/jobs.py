"""Durable, single-process background jobs for non-canonical processing.

The GUI can enqueue the existing scan/pull actions (ingest, duplicates, identity,
clarification, Krisp pull) instead of blocking an HTTP request on them. Jobs are persisted
one file per job under ``runtime/jobs/``; the runner requeues interrupted work on startup and
deduplicates an active job of the same kind. Canonical apply/dismiss decisions are not jobs.
"""

from __future__ import annotations

import queue
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from worksync.gui.actions import dispatch_action
from worksync.safety.derived import write_json
from worksync.work.jobs import (
    JOB_DIRNAME,
    JOB_KINDS,
    JOB_QUEUE_BY_KIND,
    list_jobs,
    read_job,
)
from worksync.work.processing import processing_status

if TYPE_CHECKING:
    from worksync.gui.actions import WriteContext

MAX_ATTEMPTS = 2


class JobError(ValueError):
    """A rejected job submission with its HTTP status."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return f"job-{datetime.now(UTC):%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"


def _summarize(kind: str, response: object, pending: int) -> dict:
    result: dict[str, object] = {"pending": pending}
    if not isinstance(response, dict):
        return result
    scan_token = response.get("scan_token")
    if isinstance(scan_token, str):
        result["scan_token"] = scan_token
    proposals = response.get("proposals")
    if isinstance(proposals, list):
        result["proposals"] = len(proposals)
    summary = response.get("summary")
    if isinstance(summary, dict):
        for key in ("pulled", "skipped", "failed", "empty_transcripts", "notes_unavailable"):
            value = summary.get(key)
            if isinstance(value, list):
                result[key] = len(value)
    return result


class JobRunner:
    """One daemon worker over a durable job store."""

    def __init__(
        self,
        service: WriteContext,
        *,
        execute: Callable[[str], object] | None = None,
    ) -> None:
        self.service = service
        self.runtime_root = Path(service.runtime_root)
        self._execute = execute or self._run_action
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Requeue interrupted/queued jobs, then start the worker thread."""
        self._recover()
        self._thread = threading.Thread(target=self._loop, name="worksync-jobs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def submit(self, kind: str, idempotency_key: str | None = None) -> dict:
        """Create (or return the active) job for *kind*; never blocks on the work."""
        name = str(kind or "").strip()
        if name not in JOB_KINDS:
            raise JobError("bad_request", f"Unknown job kind: {name or '(empty)'}.", 400)
        with self._lock:
            active = [
                job for job in list_jobs(self.runtime_root, limit=200) if job.get("status") in ("queued", "running")
            ]
            if idempotency_key:
                for job in active:
                    if job.get("idempotency_key") == idempotency_key:
                        return job
            else:
                for job in active:
                    if job.get("kind") == name:
                        return job
            job = {
                "version": 1,
                "id": _new_id(),
                "kind": name,
                "status": "queued",
                "created_at": _now(),
                "started_at": None,
                "finished_at": None,
                "attempts": 0,
                "error": None,
                "result": None,
                "idempotency_key": idempotency_key,
            }
            self._write(job)
        self._queue.put(job["id"])
        return job

    def _loop(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if job_id is None:
                break
            try:
                self._run(job_id)
            except Exception:  # noqa: BLE001 - a job failure must not kill the worker
                continue

    def _run(self, job_id: str) -> None:
        job = read_job(self.runtime_root, job_id)
        if job is None:
            return
        job["status"] = "running"
        job["started_at"] = _now()
        job["attempts"] = int(job.get("attempts") or 0) + 1
        job["error"] = None
        self._write(job)
        try:
            response = self._execute(job["kind"])
            pending = self._pending(job["kind"])
            job["status"] = "awaiting_review" if pending else "completed"
            job["result"] = _summarize(job["kind"], response, pending)
        except Exception as exc:  # noqa: BLE001 - record the failure, keep the worker alive
            job["status"] = "failed"
            job["error"] = str(exc)[:500]
        finally:
            job["finished_at"] = _now()
            self._write(job)

    def _pending(self, kind: str) -> int:
        queue_id = JOB_QUEUE_BY_KIND.get(kind)
        if not queue_id:
            return 0
        for row in processing_status(self.runtime_root)["queues"]:
            if row["id"] == queue_id:
                return int(row.get("pending") or 0)
        return 0

    def _run_action(self, kind: str) -> object:
        return dispatch_action(self.service, kind, {})

    def _recover(self) -> None:
        for job in list_jobs(self.runtime_root, limit=200):
            status = job.get("status")
            if status == "running":
                if int(job.get("attempts") or 0) >= MAX_ATTEMPTS:
                    job["status"] = "failed"
                    job["error"] = "Interrupted repeatedly; not retried."
                    job["finished_at"] = _now()
                    self._write(job)
                else:
                    job["status"] = "queued"
                    job["error"] = "Interrupted; requeued."
                    self._write(job)
                    self._queue.put(job["id"])
            elif status == "queued":
                self._queue.put(job["id"])

    def _write(self, job: dict) -> None:
        write_json(self.runtime_root, Path(JOB_DIRNAME) / f"{job['id']}.json", job)
