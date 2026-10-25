"""CLI parity for ``worksync tag apply`` and ``worksync tag remove``."""

from __future__ import annotations

import json
from pathlib import Path

from supertag_fakes import seed_design_vault
from worksync.cli.main import main
from worksync.inventory.parse import read_frontmatter


def _frontmatter(vault: Path, name: str = "A1") -> dict:
    return read_frontmatter((vault / f"Actions/{name}.md").read_text(encoding="utf-8")).data


def test_cli_tag_apply_and_remove(vault: Path, write_note, tmp_path: Path, capsys) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"

    code = main(
        [
            "tag",
            "apply",
            entity_id,
            "design-task",
            "--reason",
            "Triage",
            "--reviewer",
            "myles",
            "--confirm",
            "--json",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "apply-supertag"
    assert payload["committed"] is True
    assert payload["tags"] == ["design-task"]
    assert "design_phase" in payload["defaults_written"]
    assert _frontmatter(vault)["supertags"] == ["design-task"]

    code = main(
        [
            "tag",
            "remove",
            entity_id,
            "design-task",
            "--reason",
            "No longer",
            "--reviewer",
            "myles",
            "--confirm",
            "--json",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "remove-supertag"
    assert payload["committed"] is True
    assert payload["tags"] == []
    assert "supertags" not in _frontmatter(vault)
    assert _frontmatter(vault)["design_phase"] == "discovery"


def test_cli_tag_apply_requires_confirmation(vault: Path, write_note, tmp_path: Path, capsys) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"

    code = main(
        [
            "tag",
            "apply",
            entity_id,
            "design-task",
            "--reason",
            "Triage",
            "--reviewer",
            "myles",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
        ]
    )

    assert code == 1
    assert "needs_confirmation" in capsys.readouterr().err
    assert "supertags" not in _frontmatter(vault)
