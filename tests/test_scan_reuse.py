"""Equivalence of the shared-scan refactor: from_records / since_last_check_from_records.

These pin that the refactored entry points produce exactly the same result as the
scan-then-build originals, so the read seam can reuse a single cached scan.
"""

from __future__ import annotations

from worksync.inventory.parse import scan_vault
from worksync.work.repository import WorkIndex
from worksync.work.since_last_check import Checkpoint, since_last_check, since_last_check_from_records


def test_workindex_from_records_matches_from_vault(vault, write_note) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\nperson_id: myles\n---\n# Myles\n")
    write_note(vault, "Notes/scratch.md", "# Scratch\n")

    by_vault = WorkIndex.from_vault(vault)
    by_records = WorkIndex.from_records(scan_vault(vault), vault)

    assert [entity.path for entity in by_vault.entities] == [entity.path for entity in by_records.entities]
    assert by_vault.issues == by_records.issues
    assert by_vault.counts() == by_records.counts()


def test_since_last_check_from_records_matches_scan(vault, write_note) -> None:
    write_note(vault, "Notes/a.md", "# A\n")
    write_note(vault, "Notes/b.md", "# B\n")
    checkpoint = Checkpoint(acknowledged_at="t", notes={})

    by_scan = since_last_check(vault, checkpoint, generated_at="g")
    by_records = since_last_check_from_records(scan_vault(vault), checkpoint, generated_at="g")

    assert by_scan == by_records
