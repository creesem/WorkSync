"""WP-05: the `worksync identity` CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from worksync.cli.main import main
from worksync.safety.zones import staging_root
from worksync.work.identity import MANIFEST_REL

PEOPLE = "People"


def _person(
    write_note: Callable[..., Path],
    vault: Path,
    name: str,
    title: str,
    *,
    person_id: str,
    role: str | None = None,
    team: str | None = None,
    email: str | None = None,
) -> Path:
    lines = ["---", "type: person", "status: active", f"person_id: {person_id}"]
    if role:
        lines.append(f"role: {role}")
    if team:
        lines.append(f"team: {team}")
    if email:
        lines.append(f"email: {email}")
    lines.append("---")
    return write_note(vault, f"{PEOPLE}/{name}.md", "\n".join(lines) + f"\n# {title}\n")


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", role="PM", team="IT")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b", email="carlos@example.com")


def _base(vault: Path, runtime: Path) -> list[str]:
    return ["--vault", str(vault), "--runtime", str(runtime)]


def test_cli_identity_scan_and_dismiss(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = _base(vault, runtime)

    assert main(["identity", "scan", *base, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["proposals"]) == 1
    proposal_id = payload["proposals"][0]["id"]
    assert proposal_id.startswith("person-dup:")

    assert (
        main(["identity", "dismiss", proposal_id, *base, "--reason", "keep both", "--reviewer", "Myles", "--json"]) == 0
    )
    dismissed = json.loads(capsys.readouterr().out)
    assert dismissed["proposals"][0]["status"] == "dismissed"


def test_cli_identity_scan_dry_run_does_not_persist(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"

    assert main(["identity", "scan", *_base(vault, runtime), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["proposals"]) == 1
    assert not (staging_root(runtime) / MANIFEST_REL).exists()


def test_cli_identity_show_without_manifest_fails(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    assert main(["identity", "show", *_base(vault, tmp_path / "var"), "--json"]) == 1


def test_cli_identity_apply_merges(vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = _base(vault, runtime)
    main(["identity", "scan", *base, "--json"])
    proposal_id = json.loads(capsys.readouterr().out)["proposals"][0]["id"]

    code = main(
        [
            "identity",
            "apply",
            proposal_id,
            *base,
            "--reason",
            "same person",
            "--reviewer",
            "Myles",
            "--confirm",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert payload["applied"] == [proposal_id]
    assert "type: redirect" in (vault / f"{PEOPLE}/Carlos B.md").read_text(encoding="utf-8")


def test_cli_identity_apply_requires_confirmation(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, capsys
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    base = _base(vault, runtime)
    main(["identity", "scan", *base, "--json"])
    proposal_id = json.loads(capsys.readouterr().out)["proposals"][0]["id"]

    assert main(["identity", "apply", proposal_id, *base, "--reason", "same person", "--reviewer", "Myles"]) == 1
