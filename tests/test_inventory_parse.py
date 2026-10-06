"""Ticket 02: the YAML-faithful parse layer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from worksync.inventory.parse import (
    parse_note,
    read_frontmatter,
    scan_vault,
    set_frontmatter_fields,
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
