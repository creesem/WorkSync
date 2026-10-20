"""The read seam's per-vault scan cache: reuse, invalidation, and single-scan Command Center."""

from __future__ import annotations

from datetime import date

from worksync.context import service

TODAY = date(2026, 10, 12)


def test_cached_scan_reuses_an_unchanged_vault(vault, write_note) -> None:
    write_note(vault, "Notes/a.md", "# A\n")
    first = service._cached_scan(vault)
    second = service._cached_scan(vault)
    assert first is second  # the same cached record tuple


def test_cached_scan_invalidates_on_edit(vault, write_note) -> None:
    write_note(vault, "Notes/a.md", "# A\n")
    first = service._cached_scan(vault)
    write_note(vault, "Notes/a.md", "# A edited\n")
    second = service._cached_scan(vault)
    assert first is not second
    assert {record.content_hash for record in second}


def test_command_center_is_stable_across_cached_calls(vault, write_note, tmp_path) -> None:
    write_note(vault, "Notes/a.md", "# A\n")
    runtime = tmp_path / "var"
    a = service.command_center(vault, runtime, TODAY, generated_at="g")
    b = service.command_center(vault, runtime, TODAY, generated_at="g")
    assert a == b


def test_command_center_scans_the_vault_once(monkeypatch, vault, write_note, tmp_path) -> None:
    write_note(vault, "Notes/a.md", "# A\n")
    calls: list[str] = []
    original = service.scan_vault

    def counting(v):
        calls.append(str(v))
        return original(v)

    monkeypatch.setattr(service, "scan_vault", counting)
    service._scan_cache.clear()
    service.command_center(vault, tmp_path / "var", TODAY, generated_at="g")
    assert len(calls) == 1  # the index and Since Last Check share one scan
