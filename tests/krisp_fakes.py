"""Shared offline fakes and builders for the Krisp test suites.

One deterministic ``FakeKrispClient`` and one meeting/sidecar builder, so the pull,
discovery, apply, CLI, and GUI suites cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from worksync.ingest.krisp import KrispMeeting, MeetingStub

DEFAULT_MEETING_ID = "a1b2c3d4e5f6"
DEFAULT_TITLE = "Q3 Sync"
DEFAULT_STARTED_AT = "2026-10-07T14:00:00Z"


class FakeKrispClient:
    """Deterministic offline stand-in for the Krisp API adapter."""

    def __init__(
        self,
        meetings: tuple[KrispMeeting, ...] = (),
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self._meetings = {meeting.meeting_id: meeting for meeting in meetings}
        self._failures = dict(failures or {})
        self.list_calls = 0

    def list_meetings(self, *, since_days: int, limit: int | None = None) -> tuple[MeetingStub, ...]:
        self.list_calls += 1
        stubs = tuple(MeetingStub(m.meeting_id, m.title, m.started_at) for m in self._meetings.values())
        return stubs[:limit] if limit else stubs

    def get_meeting(self, meeting_id: str) -> KrispMeeting:
        if meeting_id in self._failures:
            raise self._failures[meeting_id]
        return self._meetings[meeting_id]


def meeting(
    meeting_id: str = DEFAULT_MEETING_ID,
    title: str = DEFAULT_TITLE,
    started_at: str = DEFAULT_STARTED_AT,
    *,
    segments: tuple[dict[str, Any], ...] | None = None,
    notes: dict[str, Any] | None = None,
    speakers: tuple[dict[str, Any], ...] | None = None,
    duration_seconds: int = 2520,
    source: str = "krisp",
    tags: tuple[str, ...] = ("sync",),
) -> KrispMeeting:
    """Build a full meeting; pass ``segments=()`` or ``notes={}`` for the empty cases."""
    return KrispMeeting(
        meeting_id=meeting_id,
        title=title,
        started_at=started_at,
        duration_seconds=duration_seconds,
        source=source,
        tags=tags,
        speakers=speakers
        if speakers is not None
        else ({"index": 0, "first_name": "Myles", "last_name": "Creese", "email": ""},),
        segments=segments
        if segments is not None
        else ({"speaker": "Myles Creese", "start": 0, "end": 5, "text": "Hello team"},),
        notes=notes
        if notes is not None
        else {"blocks": [{"type": "key_points", "children": [{"type": "key_point", "text": "Ship v2"}]}]},
    )


def sidecar(meeting_id: str = DEFAULT_MEETING_ID, started_at: str = DEFAULT_STARTED_AT) -> dict[str, Any]:
    """Build a sidecar payload: one attendee, one project mention, and one assigned action."""
    return {
        "meeting_id": meeting_id,
        "title": DEFAULT_TITLE,
        "started_at": started_at,
        "duration_seconds": 60,
        "source": "krisp",
        "tags": ["sync"],
        "speakers": [{"first_name": "Myles", "last_name": "Creese"}],
        "segments": [{"speaker": "Myles Creese", "start": 0, "end": 4, "text": "Project - Eleos is on track"}],
        "notes": {
            "blocks": [
                {"type": "key_points", "children": [{"type": "key_point", "text": "Ship v2"}]},
                {
                    "type": "action_items",
                    "children": [
                        {
                            "type": "action_item",
                            "text": "Send deck",
                            "assignee": {"first_name": "Myles", "last_name": "Creese"},
                        }
                    ],
                },
            ]
        },
    }
