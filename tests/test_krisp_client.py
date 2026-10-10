"""Ticket 02: the HTTP Krisp client — headers, retry, and error mapping."""

from __future__ import annotations

import json
import urllib.error

import pytest

from worksync.ingest.krisp import KrispAPIError, KrispMeeting, MeetingStub
from worksync.ingest.krisp.client import HttpKrispClient


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_list_meetings_sends_bearer_and_browser_agent() -> None:
    captured: dict = {}

    def opener(request, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        return FakeResponse({"data": [{"id": "m1", "title": "Q3", "started_at": "2026-10-07T14:00:00Z"}]})

    client = HttpKrispClient("secret-key", open_url=opener)
    stubs = client.list_meetings(since_days=14)
    assert stubs == (MeetingStub("m1", "Q3", "2026-10-07T14:00:00Z"),)
    assert captured["headers"]["authorization"] == "Bearer secret-key"
    assert "python-urllib" not in captured["headers"].get("user-agent", "").lower()
    assert "/meetings" in captured["url"]


def test_get_meeting_builds_a_meeting() -> None:
    detail = {
        "id": "m1",
        "title": "Q3",
        "started_at": "2026-10-07T14:00:00Z",
        "duration_seconds": 60,
        "source": "krisp",
        "tags": ["sync"],
        "speakers": [{"index": 0, "first_name": "Myles", "last_name": "Creese", "email": ""}],
        "transcript": [{"speaker": "Myles Creese", "start": 0, "end": 4, "text": "Hello"}],
        "notes": {"blocks": []},
    }
    client = HttpKrispClient("k", open_url=lambda request, timeout: FakeResponse(detail))
    meeting = client.get_meeting("m1")
    assert isinstance(meeting, KrispMeeting)
    assert meeting.meeting_id == "m1"
    assert meeting.segments[0]["text"] == "Hello"


def test_retries_a_429_then_succeeds() -> None:
    calls = {"count": 0}

    def opener(request, timeout):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
        return FakeResponse({"data": []})

    client = HttpKrispClient("k", open_url=opener)
    assert client.list_meetings(since_days=1) == ()
    assert calls["count"] == 2


def test_unauthorized_maps_to_actionable_error() -> None:
    def opener(request, timeout):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    client = HttpKrispClient("k", open_url=opener)
    with pytest.raises(KrispAPIError) as excinfo:
        client.list_meetings(since_days=1)
    assert excinfo.value.code == "unauthorized"
