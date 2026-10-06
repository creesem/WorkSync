"""Ticket 09: generated views through the CLI render and gated write."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main
from worksync.work.views import VIEW_NAMES

GENERATED_AT = "2026-01-15T09:00:00+00:00"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(
        vault,
        "9. Project/P.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        "next_review: 2026-01-10\nlast_reviewed: 2026-01-01\n---\n# Project Alpha\n",
    )
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\n'
        'project: "[[Project Alpha]]"\ndue: 2026-01-05\n---\n# Action One\n',
    )


def test_views_render_is_deterministic(vault: Path, write_note: Callable[..., Path], capsys) -> None:
    _seed(vault, write_note)
    args = ["views", "render", "--vault", str(vault), "--today", "2026-01-15", "--generated-at", GENERATED_AT, "--json"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert first == second
    assert [view["name"] for view in first] == list(VIEW_NAMES)
    assert all(view["sources"] for view in first)


def test_views_write_requires_confirmation_and_writes_nothing(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = [
        "views",
        "write",
        "--vault",
        str(vault),
        "--runtime",
        str(runtime),
        "--today",
        "2026-01-15",
        "--generated-at",
        GENERATED_AT,
    ]

    assert main(base) == 1
    assert "needs_confirmation" in capsys.readouterr().err
    assert not (runtime / "views").exists()

    assert main([*base, "--confirm", "--json"]) == 0
    assert (runtime / "views" / "Today.md").is_file()
    assert not (vault / "Today.md").exists()
