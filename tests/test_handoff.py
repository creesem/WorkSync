"""Tests for the handoff/tracker generator (scripts/handoff.py)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "handoff.py"
_spec = importlib.util.spec_from_file_location("worksync_handoff", SCRIPT)
assert _spec is not None and _spec.loader is not None
handoff = importlib.util.module_from_spec(_spec)
sys.modules["worksync_handoff"] = handoff
_spec.loader.exec_module(handoff)


def _ticket(root: Path, name: str, text: str) -> Path:
    path = root / "09-x" / "issues" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_ticket_reads_status_boxes_and_identity(tmp_path: Path) -> None:
    path = _ticket(tmp_path, "01-thing.md", "**Status:** ready-for-agent\n\n- [x] a\n- [ ] b\n")
    ticket = handoff.parse_ticket(path, tmp_path)
    assert ticket.status == "ready-for-agent"
    assert (ticket.done_boxes, ticket.total_boxes) == (1, 2)
    assert ticket.milestone == "09-x"
    assert ticket.number == "01"
    assert ticket.title == "thing"
    assert ticket.open is True
    assert ticket.stale is False


def test_all_boxes_ticked_but_open_status_is_stale(tmp_path: Path) -> None:
    path = _ticket(tmp_path, "01-thing.md", "**Status:** ready-for-agent\n\n- [x] a\n- [x] b\n")
    ticket = handoff.parse_ticket(path, tmp_path)
    assert ticket.stale is True
    assert ticket.open is False


def test_unknown_status_is_flagged(tmp_path: Path) -> None:
    path = _ticket(tmp_path, "01-thing.md", "**Status:** provisional\n\n- [ ] a\n")
    assert handoff.parse_ticket(path, tmp_path).unknown is True


def test_status_with_a_verification_note_is_recognized(tmp_path: Path) -> None:
    path = _ticket(
        tmp_path, "01-thing.md", "**Status:** done (verified 2026-10-07; full suite 360 passed)\n\n- [x] a\n"
    )
    ticket = handoff.parse_ticket(path, tmp_path)
    assert ticket.status == "done"
    assert ticket.stale is False
    assert ticket.unknown is False
    assert ticket.open is False


def test_discover_and_render_block(tmp_path: Path) -> None:
    _ticket(tmp_path, "01-a.md", "**Status:** ready-for-agent\n\n- [ ] x\n")
    _ticket(tmp_path, "02-b.md", "**Status:** done\n\n- [x] x\n")
    tickets = handoff.discover_tickets(tmp_path)
    assert [ticket.number for ticket in tickets] == ["01", "02"]
    block = handoff.render_block(
        tickets, sha="abc1234", subject="test commit", today="2026-10-10", tests="1 passed", active="09-x"
    )
    assert "- Open tickets: 1 (active: 1)" in block
    assert "`09-x/01`" in block
    assert "- Tests: 1 passed" in block
    assert "- Next milestone: 09-x" in block


def test_render_summarizes_other_milestones(tmp_path: Path) -> None:
    _ticket(tmp_path, "01-a.md", "**Status:** ready-for-agent\n\n- [ ] x\n")
    other = tmp_path / "10-y" / "issues" / "01-c.md"
    other.parent.mkdir(parents=True)
    other.write_text("**Status:** ready-for-agent\n\n- [ ] x\n", encoding="utf-8")
    tickets = handoff.discover_tickets(tmp_path)
    block = handoff.render_block(tickets, sha="abc", subject="s", today="2026-10-10", active="09-x")
    assert "- Open tickets: 2 (active: 1)" in block
    assert "10-y (1)" in block
    assert "`10-y/01`" not in block


def test_active_milestone_reads_next_session(tmp_path: Path) -> None:
    handoff_file = tmp_path / "NEXT-SESSION.md"
    handoff_file.write_text("Build `.scratch/worksync-platform-v2/09-project-lifecycle/`.", encoding="utf-8")
    assert handoff.active_milestone(handoff_file) == "09-project-lifecycle"
    assert handoff.active_milestone(tmp_path / "missing.md") is None


def test_write_block_replaces_only_between_markers() -> None:
    text = f"before\n{handoff.BEGIN}\nold\n{handoff.END}\nafter\n"
    out = handoff.write_block(text, "new")
    assert "old" not in out
    assert "new" in out
    assert out.startswith("before")
    assert out.rstrip().endswith("after")


def test_scaffold_carries_the_markers() -> None:
    assert handoff.BEGIN in handoff.SCAFFOLD
    assert handoff.END in handoff.SCAFFOLD
