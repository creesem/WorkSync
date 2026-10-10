"""The Krisp API adapter.

A small, injectable client over the Krisp meeting API. The network is reached only by the
default opener; tests inject a fake opener or a fake client so no test hits the network.
The adapter never writes to the vault or runtime; it only reads from Krisp.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

DEFAULT_BASE = "https://meeting-api.krisp.ai/v1"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WorkSync/0.1 (+local)"
DEFAULT_TIMEOUT = 30
DEFAULT_LIMIT = 25
MAX_ATTEMPTS = 5


class KrispAPIError(RuntimeError):
    """Raised when a Krisp request cannot be completed."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class MeetingStub:
    """A lightweight meeting reference returned by the list endpoint."""

    meeting_id: str
    title: str
    started_at: str


@dataclass(frozen=True)
class KrispMeeting:
    """A full meeting fetched from Krisp, ready to be written as a transcript + sidecar."""

    meeting_id: str
    title: str
    started_at: str
    duration_seconds: int = 0
    source: str = ""
    tags: tuple[str, ...] = ()
    speakers: tuple[dict[str, Any], ...] = ()
    segments: tuple[dict[str, Any], ...] = ()
    notes: dict[str, Any] = field(default_factory=dict)


class KrispClient(Protocol):
    """The seam every consumer depends on; a fake stands in for tests."""

    def list_meetings(self, *, since_days: int, limit: int | None = None) -> tuple[MeetingStub, ...]: ...

    def get_meeting(self, meeting_id: str) -> KrispMeeting: ...


class HttpKrispClient:
    """A urllib-backed Krisp client with Bearer auth and 429 retry."""

    def __init__(
        self,
        api_key: str,
        *,
        base: str = DEFAULT_BASE,
        timeout: int = DEFAULT_TIMEOUT,
        open_url: object | None = None,
    ) -> None:
        self._api_key = str(api_key)
        self._base = base.rstrip("/")
        self._timeout = timeout
        self._open_url = open_url

    def list_meetings(self, *, since_days: int, limit: int | None = None) -> tuple[MeetingStub, ...]:
        """Return recent meeting references, newest first."""
        since = (date.today() - timedelta(days=max(int(since_days), 0))).isoformat()
        payload = self._get(
            "/meetings",
            {"sort_by": "date", "order": "newest", "limit": str(limit or DEFAULT_LIMIT), "from": since},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return ()
        stubs: list[MeetingStub] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            stubs.append(
                MeetingStub(
                    meeting_id=str(item["id"]),
                    title=str(item.get("title") or ""),
                    started_at=str(item.get("started_at") or ""),
                )
            )
        return tuple(stubs)

    def get_meeting(self, meeting_id: str) -> KrispMeeting:
        """Return one full meeting, including transcript segments and Krisp notes."""
        payload = self._get(
            f"/meetings/{urllib.parse.quote(str(meeting_id))}",
            {"fields": "title,started_at,transcript,notes"},
        )
        if not isinstance(payload, dict):
            raise KrispAPIError("bad_response", f"Krisp returned no meeting for {meeting_id}.")
        return _meeting_from_detail(payload)

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = self._base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        for attempt in range(MAX_ATTEMPTS):
            try:
                with self._open(request) as response:
                    raw = response.read()
                parsed = json.loads(raw.decode("utf-8"))
                return parsed if isinstance(parsed, dict) else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < MAX_ATTEMPTS - 1:
                    time.sleep(_retry_after(exc))
                    continue
                raise _http_error(exc) from exc
            except urllib.error.URLError as exc:
                raise KrispAPIError("network", f"Could not reach Krisp: {exc.reason}") from exc
            except (ValueError, UnicodeDecodeError) as exc:
                raise KrispAPIError("bad_response", "Krisp returned an unreadable response.") from exc
        raise KrispAPIError("rate_limited", "Krisp rate limit was not cleared after retries.")

    def _open(self, request: urllib.request.Request) -> Any:
        if self._open_url is not None:
            return self._open_url(request, self._timeout)  # type: ignore[operator]
        return urllib.request.urlopen(request, timeout=self._timeout)


def build_client(api_key: str, *, base: str = DEFAULT_BASE, timeout: int = DEFAULT_TIMEOUT) -> HttpKrispClient:
    """Build the default HTTP client; a seam so the CLI can inject a fake in tests."""
    return HttpKrispClient(api_key, base=base, timeout=timeout)


def _retry_after(exc: urllib.error.HTTPError) -> float:
    raw = (exc.headers or {}).get("Retry-After") if exc.headers else None
    try:
        return max(float(str(raw)), 0.0)
    except (TypeError, ValueError):
        return 1.0


def _http_error(exc: urllib.error.HTTPError) -> KrispAPIError:
    if exc.code in (401, 403):
        return KrispAPIError("unauthorized", "Krisp rejected the API key (401/403).", status=exc.code)
    if exc.code == 429:
        return KrispAPIError("rate_limited", "Krisp rate limit was not cleared after retries.", status=exc.code)
    return KrispAPIError("http_error", f"Krisp request failed with status {exc.code}.", status=exc.code)


def _meeting_from_detail(payload: dict[str, Any]) -> KrispMeeting:
    transcript = payload.get("transcript")
    if isinstance(transcript, list):
        segments = transcript
    elif isinstance(transcript, dict):
        segments = transcript.get("segments") or []
    else:
        segments = []
    tags = payload.get("tags") or []
    speakers = payload.get("speakers") or []
    notes = payload.get("notes")
    return KrispMeeting(
        meeting_id=str(payload.get("id") or ""),
        title=str(payload.get("title") or ""),
        started_at=str(payload.get("started_at") or ""),
        duration_seconds=int(payload.get("duration_seconds") or 0),
        source=str(payload.get("source") or ""),
        tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
        speakers=tuple(dict(item) for item in speakers if isinstance(item, dict)) if isinstance(speakers, list) else (),
        segments=tuple(dict(item) for item in segments if isinstance(item, dict)) if isinstance(segments, list) else (),
        notes=dict(notes) if isinstance(notes, dict) else {},
    )
