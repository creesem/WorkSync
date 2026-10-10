"""Ticket 04: the optional local-model meeting-body draft."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.ingest import scan
from worksync.ingest.krisp import write_sidecar

PERSON = "---\ntype: person\nstatus: active\n---\n# Myles Creese\n"


class FakeModel:
    def __init__(self, response: object = None) -> None:
        self.response = response
        self.prompts: list[str] = []

    def suggest(self, prompt: str, schema: dict) -> object:
        self.prompts.append(prompt)
        return self.response


class BoomModel:
    def suggest(self, prompt: str, schema: dict) -> object:
        raise RuntimeError("model down")


def _seed(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> tuple[Path, Path]:
    (vault / "7. Task Notes" / "Inbox").mkdir(parents=True, exist_ok=True)
    write_note(vault, "People/Myles Creese.md", PERSON)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    inbox.mkdir(parents=True)
    transcript = inbox / "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
    transcript.write_text("Myles Creese | 0:00\nUNIQUE_TRANSCRIPT_MARKER\n", encoding="utf-8")
    write_sidecar(
        inbox,
        transcript,
        {
            "meeting_id": "a1b2c3d4e5f6",
            "title": "Q3 Sync",
            "started_at": "2026-10-07T14:00:00Z",
            "duration_seconds": 60,
            "source": "krisp",
            "tags": [],
            "speakers": [{"first_name": "Myles", "last_name": "Creese"}],
            "segments": [{"speaker": "Myles Creese", "start": 0, "end": 4, "text": "Hello"}],
            "notes": {
                "blocks": [
                    {"type": "key_points", "children": [{"type": "key_point", "text": "Ship v2"}]},
                    {
                        "type": "action_items",
                        "children": [{"type": "action_item", "text": "Send deck"}],
                    },
                ]
            },
        },
    )
    return runtime, inbox


def _meeting(manifest):
    return next(p for p in manifest.proposals if p.action == "meeting")


def test_no_model_records_the_deterministic_mode(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    proposal = _meeting(scan(vault, runtime, krisp_inbox_path=inbox))
    assert "notes_text" not in proposal.fields
    assert any("deterministic" in reason for reason in proposal.provenance)


def test_model_drafts_the_notes_prose(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    model = FakeModel({"notes": "- Summarised"})
    proposal = _meeting(scan(vault, runtime, krisp_inbox_path=inbox, model=model))
    assert proposal.fields["notes_text"] == "- Summarised"
    assert any("local model" in reason for reason in proposal.provenance)
    assert proposal.fields["status"] == "held"
    assert proposal.status == "pending"


def test_model_failure_falls_back_to_deterministic(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    proposal = _meeting(scan(vault, runtime, krisp_inbox_path=inbox, model=BoomModel()))
    assert "notes_text" not in proposal.fields
    assert any("deterministic" in reason for reason in proposal.provenance)


def test_model_prompt_excludes_the_raw_transcript(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    runtime, inbox = _seed(vault, write_note, tmp_path)
    model = FakeModel({"notes": "x"})
    scan(vault, runtime, krisp_inbox_path=inbox, model=model)
    prompt = model.prompts[0]
    assert "UNIQUE_TRANSCRIPT_MARKER" not in prompt
    assert len(prompt) < 2000
