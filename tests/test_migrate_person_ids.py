"""WP-01: assign a stable person_id to person notes that lack one."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.migrate.person_ids import REASON, REVIEWER, apply_person_ids, detect_person_ids
from worksync.safety.models import MutationError


def _write(vault: Path, name: str, text: str) -> Path:
    path = vault / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_detect_assigns_a_kebab_id(vault: Path) -> None:
    _write(vault, "People/Carlos Barnes.md", "---\ntype: person\nstatus: active\n---\n# Carlos Barnes\n")
    assignments = {a.path: a.person_id for a in detect_person_ids(vault)}
    assert assignments == {"People/Carlos Barnes.md": "carlos-barnes"}


def test_detect_dedupes_within_the_vault(vault: Path) -> None:
    _write(vault, "People/A.md", "---\ntype: person\nstatus: active\n---\n# Carlos\n")
    _write(vault, "People/B.md", "---\ntype: person\nstatus: active\n---\n# Carlos\n")
    assert sorted(a.person_id for a in detect_person_ids(vault)) == ["carlos", "carlos-2"]


def test_detect_avoids_an_existing_id(vault: Path) -> None:
    _write(vault, "People/A.md", "---\ntype: person\nstatus: active\nperson_id: carlos\n---\n# Carlos\n")
    _write(vault, "People/B.md", "---\ntype: person\nstatus: active\n---\n# Carlos\n")
    assignments = {a.path: a.person_id for a in detect_person_ids(vault)}
    assert assignments == {"People/B.md": "carlos-2"}


def test_detect_ignores_notes_that_already_have_an_id(vault: Path) -> None:
    _write(vault, "People/A.md", "---\ntype: person\nstatus: active\nperson_id: carlos\n---\n# Carlos\n")
    assert detect_person_ids(vault) == ()


def test_detect_ignores_non_person_notes(vault: Path) -> None:
    _write(
        vault,
        "9. Project/Project - Alpha.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[A]]"\n---\n# Project - Alpha\n',
    )
    assert detect_person_ids(vault) == ()


def test_apply_assigns_ids_backs_up_and_is_idempotent(vault: Path, tmp_path: Path) -> None:
    _write(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    runtime = tmp_path / "var"
    result = apply_person_ids(vault, runtime)
    assert result is not None and result.committed is True
    assert (vault / "People/Myles.md").read_text(encoding="utf-8") == (
        "---\ntype: person\nstatus: active\nperson_id: myles\n---\n# Myles\n"
    )
    assert result.changes[0]["reviewer"] == REVIEWER
    assert result.changes[0]["reason"] == REASON
    assert list((runtime / "backups").glob("backup-*/file-*"))
    assert detect_person_ids(vault) == ()
    assert apply_person_ids(vault, runtime) is None


def test_changed_source_fails_closed(vault: Path, tmp_path: Path) -> None:
    _write(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    assignments = detect_person_ids(vault)
    target = vault / "People/Myles.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(MutationError) as excinfo:
        apply_person_ids(vault, tmp_path / "var", assignments=assignments)
    assert excinfo.value.code == "stale_hash"


def test_cli_person_ids_assigns_and_reports(vault: Path, tmp_path: Path, capsys) -> None:
    _write(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    runtime = tmp_path / "var"
    code = main(["migrate", "person-ids", "--vault", str(vault), "--runtime", str(runtime), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert payload["assigned"] == [{"path": "People/Myles.md", "person_id": "myles"}]
    assert "person_id: myles" in (vault / "People/Myles.md").read_text(encoding="utf-8")


def test_cli_person_ids_dry_run_writes_nothing(vault: Path, tmp_path: Path, capsys) -> None:
    _write(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    before = (vault / "People/Myles.md").read_bytes()
    code = main(
        ["migrate", "person-ids", "--vault", str(vault), "--runtime", str(tmp_path / "var"), "--dry-run", "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True and payload["committed"] is False
    assert (vault / "People/Myles.md").read_bytes() == before
