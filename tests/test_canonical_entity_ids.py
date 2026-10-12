"""Milestone 11 / ticket 01: ticket, meeting, and action carry canonical ids."""

from __future__ import annotations

from pathlib import Path

from worksync.inventory.parse import scan_vault
from worksync.work.models import Action, Meeting, Ticket
from worksync.work.schema import entity_from_record
from worksync.work.validate import validate_all


def _write(vault: Path, name: str, text: str) -> None:
    path = vault / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _entity(vault: Path, path: str):
    record = next(record for record in scan_vault(vault) if record.path == path)
    return entity_from_record(record)


def test_ticket_meeting_and_action_read_their_canonical_ids(vault: Path) -> None:
    _write(vault, "Tickets/Login bug.md", "---\ntype: ticket\nstatus: open\nticket_id: login-bug\n---\n# Login bug\n")
    _write(
        vault,
        "Meetings/Weekly sync.md",
        "---\ntype: meeting\nstatus: held\nmeeting_id: weekly-sync\n---\n# Weekly sync\n",
    )
    _write(
        vault, "Actions/Send notes.md", "---\ntype: action\nstatus: open\naction_id: send-notes\n---\n# Send notes\n"
    )

    ticket = _entity(vault, "Tickets/Login bug.md")
    meeting = _entity(vault, "Meetings/Weekly sync.md")
    action = _entity(vault, "Actions/Send notes.md")

    assert isinstance(ticket, Ticket) and ticket.ticket_id == "login-bug"
    assert isinstance(meeting, Meeting) and meeting.meeting_id == "weekly-sync"
    assert isinstance(action, Action) and action.action_id == "send-notes"


def _validation_rules(vault: Path) -> list[tuple[str, str, str]]:
    entities = [entity_from_record(record) for record in scan_vault(vault)]
    return [(issue.path, issue.rule, issue.severity) for issue in validate_all([e for e in entities if e], set())]


def test_invalid_canonical_id_is_an_error(vault: Path) -> None:
    _write(vault, "Tickets/Bad.md", "---\ntype: ticket\nstatus: open\nticket_id: Not Kebab\n---\n# Bad\n")
    assert ("Tickets/Bad.md", "ticket_id", "error") in _validation_rules(vault)


def test_duplicate_canonical_id_within_a_type_fails_closed(vault: Path) -> None:
    _write(vault, "Actions/A.md", "---\ntype: action\nstatus: open\naction_id: send-notes\n---\n# A\n")
    _write(vault, "Actions/B.md", "---\ntype: action\nstatus: open\naction_id: send-notes\n---\n# B\n")
    rules = _validation_rules(vault)
    assert ("Actions/A.md", "action_id", "error") in rules
    assert ("Actions/B.md", "action_id", "error") in rules


def test_same_value_across_different_types_is_not_a_duplicate(vault: Path) -> None:
    _write(vault, "Tickets/T.md", "---\ntype: ticket\nstatus: open\nticket_id: sync\n---\n# T\n")
    _write(vault, "Meetings/M.md", "---\ntype: meeting\nstatus: held\nmeeting_id: sync\n---\n# M\n")
    assert not [rule for rule in _validation_rules(vault) if rule[1] in {"ticket_id", "meeting_id"}]
