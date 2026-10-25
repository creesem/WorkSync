"""Durable background-job records: the read-only view and the job vocabulary.

The GUI's job runner writes one JSON record per job under ``runtime/jobs/``. This module is
read-only and imports no safety/write helper, so the GUI read seam can list jobs without
dragging the write seam into its import closure.
"""

from __future__ import annotations

import json
from pathlib import Path

JOB_DIRNAME = "jobs"
JOB_STATUSES = ("queued", "running", "awaiting_review", "completed", "failed")
JOB_KINDS = ("ingest-scan", "duplicates-scan", "identity-scan", "clarification-scan", "krisp-pull")
JOB_QUEUE_BY_KIND: dict[str, str | None] = {
    "ingest-scan": "ingest",
    "duplicates-scan": "duplicates",
    "identity-scan": "identity",
    "clarification-scan": "clarification",
    "krisp-pull": None,
}
JOB_LABELS: dict[str, str] = {
    "ingest-scan": "Ingest scan",
    "duplicates-scan": "Duplicate scan",
    "identity-scan": "Identity scan",
    "clarification-scan": "Clarification scan",
    "krisp-pull": "Krisp pull",
}


def jobs_root(runtime_root: str | Path) -> Path:
    return Path(runtime_root).expanduser().resolve() / JOB_DIRNAME


def job_path(runtime_root: str | Path, job_id: str) -> Path:
    return jobs_root(runtime_root) / f"{job_id}.json"


def read_job(runtime_root: str | Path, job_id: str) -> dict | None:
    """Return one job record, or ``None`` when it is missing or unreadable."""
    if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
        return None
    path = job_path(runtime_root, job_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_jobs(runtime_root: str | Path, *, limit: int = 20) -> list[dict]:
    """Return the newest job records first, skipping unreadable files."""
    root = jobs_root(runtime_root)
    if not root.is_dir():
        return []
    jobs: list[dict] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            jobs.append(data)
        if len(jobs) >= limit:
            break
    return jobs
