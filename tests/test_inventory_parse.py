"""Ticket 02: the YAML-faithful parse layer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from worksync.inventory.parse import (
    edit_frontmatter_fields,
    parse_note,
    read_frontmatter,
    scan_vault,
    set_frontmatter_fields,
    set_frontmatter_values,
    split_frontmatter,
)

NESTED = """---
type: project
owners:
  - "[[Myles Creese]]"
meta:
  phase: 1
  tags:
    - a
    - b
priority: P1
---
# Project - Example
Body [[Other Note]] #tag
- [ ] open item
- [x] done item
"""


def test_typed_reader_preserves_block_lists_and_nested_maps() -> None:
    frontmatter = read_frontmatter(NESTED)
    assert frontmatter.present and frontmatter.closed and not frontmatter.malformed
    assert frontmatter.data["owners"] == ["[[Myles Creese]]"]
    assert frontmatter.data["meta"] == {"phase": 1, "tags": ["a", "b"]}
    assert frontmatter.data["priority"] == "P1"


def test_malformed_frontmatter_is_read_tolerantly() -> None:
    frontmatter = read_frontmatter("---\nfoo: [1, 2\n---\n# x")
    assert frontmatter.present and frontmatter.closed and frontmatter.malformed
    assert frontmatter.data == {}


def test_unclosed_frontmatter_is_reported() -> None:
    frontmatter = read_frontmatter("---\ntype: project\n# no closing delimiter")
    assert frontmatter.present
    assert not frontmatter.closed


def test_absent_frontmatter_is_not_malformed() -> None:
    frontmatter = read_frontmatter("# Just a note")
    assert not frontmatter.present
    assert frontmatter.closed
    assert not frontmatter.malformed


def test_split_frontmatter_requires_well_formed_blocks() -> None:
    assert split_frontmatter("---\ntype: project\n---\n# Body") == ("type: project", "# Body")
    assert split_frontmatter("---\ntype: project\n# Body") == ("", "---\ntype: project\n# Body")


def test_set_frontmatter_fields_round_trips(vault: Path, write_note: Callable[..., Path]) -> None:
    path = write_note(vault, "note.md", NESTED)
    updated = set_frontmatter_fields(path.read_text(encoding="utf-8"), {"status": "active"})
    frontmatter = read_frontmatter(updated)
    assert frontmatter.data["status"] == "active"
    assert frontmatter.data["owners"] == ["[[Myles Creese]]"]
    assert frontmatter.data["meta"]["phase"] == 1
    assert "# Project - Example" in updated


def test_edit_frontmatter_replaces_scalar_in_place_and_keeps_quotes() -> None:
    text = '---\ntype: "task"\nstatus: todo\npriority: 2\nowner: x\n---\n# T\n'
    edited = edit_frontmatter_fields(text, set_fields={"status": "open", "priority": "P2"})
    assert edited == '---\ntype: "task"\nstatus: open\npriority: P2\nowner: x\n---\n# T\n'


def test_edit_frontmatter_renames_key_removes_and_appends() -> None:
    text = "---\ntype: meeting\npeople:\n  - a\npriority: 2\n---\n# M\n"
    edited = edit_frontmatter_fields(
        text, set_fields={"status": "held", "priority": None}, rename_keys={"people": "attendees"}
    )
    assert edited == "---\ntype: meeting\nattendees:\n  - a\nstatus: held\n---\n# M\n"


def test_edit_frontmatter_removes_key_and_its_block() -> None:
    text = "---\ntype: action\npriority: 2\ntags:\n  - a\n  - b\n---\n# A\n"
    edited = edit_frontmatter_fields(text, set_fields={"priority": None})
    assert edited == "---\ntype: action\ntags:\n  - a\n  - b\n---\n# A\n"


def test_edit_frontmatter_preserves_crlf_and_body() -> None:
    text = "---\r\ntype: task\r\nstatus: todo\r\n---\r\n# Body\r\nline\r\n"
    edited = edit_frontmatter_fields(text, set_fields={"type": "action", "status": "open"})
    assert edited == "---\r\ntype: action\r\nstatus: open\r\n---\r\n# Body\r\nline\r\n"


def test_set_frontmatter_fields_synthesizes_a_block_when_absent() -> None:
    assert set_frontmatter_fields("# Body\n", {"status": "active"}) == "---\nstatus: active\n---\n# Body\n"


def test_set_frontmatter_values_handles_lists_and_quotes_strings() -> None:
    text = "---\ntype: action\nsupertags:\n  - old\nstatus: open\n---\n# Body\n"

    updated = set_frontmatter_values(
        text,
        {
            "supertags": ["design-task", "vendor-followup"],
            "reviewer": "[[Myles]]",
            "review_date": "2026-11-01",
        },
    )

    frontmatter = read_frontmatter(updated)
    assert frontmatter.data["supertags"] == ["design-task", "vendor-followup"]
    assert frontmatter.data["reviewer"] == "[[Myles]]"
    assert frontmatter.data["review_date"] == "2026-11-01"
    assert frontmatter.data["type"] == "action"
    assert "  - old" not in updated
    assert updated.endswith("# Body\n")


def test_set_frontmatter_values_removes_a_key_and_its_block() -> None:
    text = "---\ntype: action\nsupertags:\n  - one\n  - two\nstatus: open\n---\n# Body\n"

    updated = set_frontmatter_values(text, {"supertags": None})

    assert "supertags" not in updated
    assert "status: open" in updated
    assert updated.endswith("# Body\n")


def test_set_frontmatter_values_writes_empty_and_scalar_values() -> None:
    text = "---\ntype: action\nsupertags:\n  - one\n---\n# Body\n"

    updated = set_frontmatter_values(text, {"supertags": [], "priority": "P1", "flagged": True, "count": 2})

    frontmatter = read_frontmatter(updated)
    assert frontmatter.data["supertags"] == []
    assert frontmatter.data["priority"] == "P1"
    assert frontmatter.data["flagged"] is True
    assert frontmatter.data["count"] == 2


def test_set_frontmatter_values_preserves_crlf() -> None:
    text = "---\r\ntype: action\r\nsupertags: [old]\r\nstatus: open\r\n---\r\n# Body\r\nline\r\n"

    updated = set_frontmatter_values(text, {"supertags": ["new"], "reviewer": "[[Myles]]"})

    assert "\n" not in updated.replace("\r\n", "")
    frontmatter = read_frontmatter(updated)
    assert frontmatter.data["supertags"] == ["new"]
    assert frontmatter.data["reviewer"] == "[[Myles]]"
    assert updated.endswith("# Body\r\nline\r\n")


def test_set_frontmatter_values_creates_frontmatter_when_absent() -> None:
    assert (
        set_frontmatter_values("# Body\n", {"supertags": ["design-task"]})
        == "---\nsupertags:\n  - design-task\n---\n# Body\n"
    )


def test_set_frontmatter_values_rejects_unterminated_frontmatter() -> None:
    with pytest.raises(ValueError):
        set_frontmatter_values("---\ntype: action\n# no close\n", {"supertags": ["x"]})


def test_parse_note_extracts_structure(vault: Path, write_note: Callable[..., Path]) -> None:
    path = write_note(vault, "10. Meetings/Example.md", NESTED)
    record = parse_note(path, vault)
    assert record.path == "10. Meetings/Example.md"
    assert record.title == "Project - Example"
    assert record.headings == [(1, "Project - Example")]
    assert ("Other Note", None) in record.links
    assert "tag" in record.tags
    assert [task[0] for task in record.tasks] == [False, True]
    assert record.frontmatter["type"] == "project"


def test_parse_note_reads_bom_tolerantly(vault: Path, write_note: Callable[..., Path]) -> None:
    path = write_note(vault, "bom.md", "---\ntype: person\n---\n# BOM")
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    record = parse_note(path, vault)
    assert record.frontmatter["type"] == "person"


def test_scan_is_deterministic_and_excludes_hidden(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "b.md", "---\ntype: person\n---\n# B")
    write_note(vault, "a.md", "---\ntype: person\n---\n# A")
    write_note(vault, ".obsidian/config.md", "x")
    write_note(vault, ".trash/old.md", "x")
    assert [record.path for record in scan_vault(vault)] == ["a.md", "b.md"]
