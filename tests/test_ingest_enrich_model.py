"""Spec 5 ticket 04: optional local-model enrichment with a deterministic fallback."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from worksync.ingest.discover import Source
from worksync.ingest.enrich import enrich
from worksync.inventory.parse import parse_note
from worksync.work.repository import WorkIndex

TODAY = date(2026, 10, 6)
INBOX = "7. Task Notes/Inbox"
PROJECT = "9. Project/Project - Alpha.md"


class StubModel:
    """A model stub: returns a fixed suggestion or raises on request."""

    def __init__(self, suggestion: object) -> None:
        self.suggestion = suggestion
        self.calls = 0
        self.prompts: list[str] = []

    def suggest(self, prompt: str, schema: dict) -> dict | None:
        self.calls += 1
        self.prompts.append(prompt)
        if isinstance(self.suggestion, Exception):
            raise self.suggestion
        return self.suggestion  # type: ignore[return-value]


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        PROJECT,
        "---\ntype: project\nstatus: active\nproject_id: alpha\n"
        'owners:\n  - "[[Myles]]"\npriority: P1\n---\n# Project - Alpha\n',
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")


def _source(vault: Path, write_note: Callable[..., Path], body: str, frontmatter: str = "") -> Source:
    text = f"---\n{frontmatter}---\n{body}" if frontmatter else body
    path = write_note(vault, f"{INBOX}/Note.md", text)
    return Source(record=parse_note(path, vault), origin="inbox")


def test_model_fills_only_weak_fields_with_provenance_and_a_cap(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    source = _source(vault, write_note, "# Call the vendor\n")
    model = StubModel(
        {
            "title": "model title",
            "owners": "Myles",
            "project": "Project - Alpha",
            "priority": "P1",
            "due": "2026-10-20",
        }
    )
    proposal = enrich(source, WorkIndex.from_vault(vault), today=TODAY, model=model)

    assert proposal is not None
    assert proposal.fields["title"] == "Call the vendor"  # deterministic title wins
    assert proposal.fields["owners"] == ["[[Myles]]"]
    assert proposal.fields["project"] == "[[Project - Alpha]]"
    assert proposal.fields["priority"] == "P1"
    assert proposal.fields["due"] == "2026-10-20"
    assert any("local model" in reason for reason in proposal.provenance)
    assert proposal.confidence <= 0.5
    assert proposal.status == "pending"


def test_model_is_not_consulted_when_every_field_is_already_resolved(
    vault: Path, write_note: Callable[..., Path]
) -> None:
    _seed(vault, write_note)
    source = _source(
        vault,
        write_note,
        "# Follow up\n",
        'owners:\n  - "[[Myles]]"\nproject: "[[Project - Alpha]]"\npriority: 2\ndue: 2026-10-11\n',
    )
    model = StubModel({"owners": "Ghost"})
    proposal = enrich(source, WorkIndex.from_vault(vault), today=TODAY, model=model)

    assert proposal is not None
    assert model.calls == 0
    assert not any("local model" in reason for reason in proposal.provenance)


def test_model_failure_falls_back_to_the_deterministic_result(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    source = _source(vault, write_note, "# Call the vendor\n")
    proposal = enrich(source, WorkIndex.from_vault(vault), today=TODAY, model=StubModel(RuntimeError("down")))

    assert proposal is not None
    assert "owners" not in proposal.fields
    assert "project" not in proposal.fields
    assert proposal.status == "pending"
    assert not any("local model" in reason for reason in proposal.provenance)


def test_model_suggestion_is_validated_against_the_index(vault: Path, write_note: Callable[..., Path]) -> None:
    _seed(vault, write_note)
    source = _source(vault, write_note, "# Call the vendor\n")
    model = StubModel({"owners": "Ghost", "project": "Ghost Project", "priority": "P9", "due": "not-a-date"})
    proposal = enrich(source, WorkIndex.from_vault(vault), today=TODAY, model=model)

    assert proposal is not None
    assert "owners" not in proposal.fields
    assert "project" not in proposal.fields
    assert "priority" not in proposal.fields
    assert "due" not in proposal.fields
