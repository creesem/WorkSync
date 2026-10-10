"""Krisp: pull transcripts and (later) propose meeting-note candidates.

This package is a discovery source on the existing ``ingest`` pipeline. It reaches the
network only through an injected :class:`KrispClient`, writes raw files only into the
runtime inbox, and never imports ``context`` or ``html``.
"""

from __future__ import annotations

from worksync.ingest.krisp.client import (
    DEFAULT_BASE,
    HttpKrispClient,
    KrispAPIError,
    KrispClient,
    KrispMeeting,
    MeetingStub,
    build_client,
)
from worksync.ingest.krisp.pull import PullResult, pull, sync_status
from worksync.ingest.krisp.sidecar import (
    format_transcript,
    read_sidecar,
    sidecar_path,
    sidecar_payload,
    transcript_filename,
    write_sidecar,
)

build_krisp_client = build_client

__all__ = [
    "DEFAULT_BASE",
    "HttpKrispClient",
    "KrispAPIError",
    "KrispClient",
    "KrispMeeting",
    "MeetingStub",
    "PullResult",
    "build_client",
    "build_krisp_client",
    "format_transcript",
    "pull",
    "read_sidecar",
    "sidecar_path",
    "sidecar_payload",
    "sync_status",
    "transcript_filename",
    "write_sidecar",
]
